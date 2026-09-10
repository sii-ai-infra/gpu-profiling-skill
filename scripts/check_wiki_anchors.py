#!/usr/bin/env python3
"""Check local Markdown link targets, heading anchors and locked wiki_refs.

R-A1 validates Markdown heading fragments; R-A2 validates local file/directory
targets, including links without fragments. Uninitialized declared submodules
and undeclared local paths outside the repository fail explicitly.
R-A3 resolves wiki_refs against a pinned local checkout or a versioned service
export (--wiki-snapshot). --local-only explicitly omits knowledge validation.

External URLs are counted but not fetched. Code blocks, inline code, images,
HTML comments and the contents of external/corpus trees are outside this scan.
Link reachability does not establish factual correctness or runtime support.
"""
from __future__ import annotations

import argparse
import configparser
import json
import os
import subprocess
import re
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlsplit

SKIP_DIRS = {".git", "external", "corpus", "node_modules", "__pycache__", ".venv"}

# 围栏代码块 / HTML 注释 / 行内代码 —— 先抹掉再解析，避免把示例当真链接
FENCE_RE = re.compile(r"^(\s*)(```+|~~~+)", re.M)
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
# 图片要在链接之前判：![x](y) 的 ]( 也会被链接正则吃到
LINK_RE = re.compile(r'(!)?\[[^\]\n]*\]\((<[^>\n]+>|[^)\s]+)(?:\s+"[^"\n]*")?\)')
REFDEF_RE = re.compile(r"^\s*\[[^\]]+\]:\s*(\S+)\s*$", re.M)
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$", re.M)


def strip_uncheckable(text: str, blank_inline: bool = True) -> str:
    """把围栏代码块整块换成等量空行，注释换成等长空白。

    换成等量空行而不是删掉，是为了行号还对得上——报错要能被点开。

    ⚠️ `blank_inline` 必须分开控制。抹行内代码是为了别把 `` `[x](y#z)` ``
    当成真链接；但**标题里的行内代码是标题正文的一部分**——
    `### ``--aic-metrics`` Presets (choose one)` 的锚点是
    `#--aic-metrics-presets-choose-one`，把反引号那段抹掉就变成
    `#presets-choose-one`，闸会去报一个**本来是对的**链接。
    第一次对真实仓跑就撞上了这一条，见 selftest ⑭。
    """
    text = COMMENT_RE.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)
    out, fence = [], None
    for line in text.split("\n"):
        m = re.match(r"^\s*(```+|~~~+)", line)
        if fence is None and m:
            fence = m.group(1)[0] * 3
            out.append("")
            continue
        if fence is not None:
            out.append("")
            if m and m.group(1)[0] * 3 == fence:
                fence = None
            continue
        out.append(INLINE_CODE_RE.sub(lambda mm: " " * len(mm.group(0)), line)
                   if blank_inline else line)
    return "\n".join(out)


def slug(title: str) -> str:
    """GitHub / GitCode 的 autolink-heading 规则。

    小写 → 去掉不是 word char / 空白 / 连字符的每个字符 → trim →
    **每个**空白换一个连字符（不合并）。`\\w` 在 Python 的 unicode 语义下
    含 CJK，所以中文标题的锚点自然是保留的——这一条不能漏，
    我们的文档标题一大半是中文。
    """
    s = title.strip()
    # 标题里的 markdown 语法先摘掉：`code` / [text](url) / **bold** / *em*
    s = re.sub(r"`([^`]*)`", r"\1", s)
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)
    s = s.lower()
    s = re.sub(r"[^\w\s-]", "", s, flags=re.UNICODE)
    s = s.strip()
    return re.sub(r"\s", "-", s)


def anchors_of(path: Path, cache: dict) -> set[str] | None:
    """目标文件的全部合法锚点。重复标题按 GitHub 规则加 -1 / -2。"""
    key = str(path)
    if key in cache:
        return cache[key]
    try:
        # 标题这一侧不抹行内代码 —— 见 strip_uncheckable 的注释
        text = strip_uncheckable(path.read_text(encoding="utf-8", errors="replace"),
                                 blank_inline=False)
    except OSError:
        cache[key] = None
        return None
    seen: dict[str, int] = {}
    out: set[str] = set()
    for m in HEADING_RE.finditer(text):
        base = slug(m.group(2))
        if not base:
            continue
        n = seen.get(base, 0)
        out.add(base if n == 0 else f"{base}-{n}")
        seen[base] = n + 1
    cache[key] = out
    return out


def frontmatter_wiki_refs(text: str) -> list[str]:
    """只取 `wiki_refs:` 底下的 `- ` 列表项，不引 YAML 依赖。"""
    if not text.startswith("---"):
        return []
    parts = text.split("---", 2)
    if len(parts) < 3:
        return []
    refs, inside = [], False
    for line in parts[1].split("\n"):
        if re.match(r"^wiki_refs:\s*$", line):
            inside = True
            continue
        if inside:
            m = re.match(r"^\s+-\s+(\S+)\s*$", line)
            if m:
                refs.append(m.group(1))
                continue
            if line.strip() and not line.startswith((" ", "\t")):
                inside = False
    return refs


def wiki_root(root: Path) -> Path | None:
    for cand in (root / "skills" / "KernelWiki-private", root / "KernelWiki-private", root):
        if (cand / "wiki").is_dir():
            return cand
    return None


def iter_md(root: Path):
    for p in sorted(root.rglob("*.md")):
        if any(part in SKIP_DIRS for part in p.relative_to(root).parts):
            continue
        yield p


def check(root: Path, verbose: bool = True, knowledge_root: Path | None = None,
          snapshot: dict | None = None, local_only: bool = False) -> tuple[int, list[str], set[str]]:
    root = root.resolve()
    wroot = knowledge_root.resolve() if knowledge_root else wiki_root(root)
    cache: dict = {}
    problems: list[str] = []
    referenced: set[str] = set()
    checked = 0
    external_urls = 0
    dependencies = []
    if snapshot is not None and (not isinstance(snapshot, dict) or not isinstance(snapshot.get("pages"), dict)):
        return 0, ["R-A3 knowledge snapshot requires a pages object"], set()
    lock_path = root / "DEPENDENCIES.json"
    if lock_path.exists() and not local_only:
        try:
            lock = json.loads(lock_path.read_text())["knowledge"]
            if not re.fullmatch(r"[0-9a-f]{40}", lock["revision"]):
                raise ValueError("knowledge revision must be a full commit SHA")
            if snapshot is not None:
                if (snapshot.get("revision"), snapshot.get("repository")) != (lock["revision"], lock["repository"]):
                    raise ValueError("knowledge snapshot repository/revision differs from lock")
            elif wroot:
                revision = subprocess.check_output(["git", "-C", str(wroot), "rev-parse", "HEAD"], text=True).strip()
                if revision != lock["revision"]:
                    raise ValueError(f"knowledge revision {revision} differs from {lock['revision']}")
                if subprocess.run(["git", "-C", str(wroot), "diff", "--quiet", "HEAD", "--", "wiki/"], check=False).returncode:
                    raise ValueError("knowledge wiki/ has uncommitted changes; cannot claim locked contents")
            else:
                raise ValueError("knowledge dependency missing; configure --wiki-root or --wiki-snapshot")
        except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as exc:
            problems.append(f"DEPENDENCIES.json: R-A3 {exc}")
    modules = configparser.ConfigParser()
    modules.read(root / ".gitmodules")
    for section in modules.sections():
        if modules.has_option(section, "path"):
            dependencies.append((root / modules.get(section, "path")).resolve())

    for md in iter_md(root):
        raw = md.read_text(encoding="utf-8", errors="replace")
        body = strip_uncheckable(raw)
        rel = md.relative_to(root)

        # ---- R-A3 声明式的 wiki 引用 ----
        for ref in ([] if local_only else frontmatter_wiki_refs(raw)):
            referenced.add(ref.split("#", 1)[0])
            if wroot is None and snapshot is None:
                problems.append(f"{rel}: R-A3 声明了 wiki_refs 但找不到 KernelWiki（submodule 没初始化？）")
                continue
            tgt, _, frag = ref.partition("#")
            if not tgt.startswith("wiki/") or ".." in Path(tgt).parts:
                problems.append(f"{rel}: R-A3 wiki path must stay within wiki/ → {tgt}")
                continue
            checked += 1
            if snapshot is not None:
                content = snapshot.get("pages", {}).get(tgt)
                if not isinstance(content, str):
                    problems.append(f"{rel}: R-A3 knowledge service snapshot missing page → {tgt}")
                elif frag:
                    with tempfile.TemporaryDirectory() as td:
                        sample = Path(td) / "page.md"
                        sample.write_text(content)
                        got = anchors_of(sample, {}) or set()
                    if frag not in got:
                        problems.append(f"{rel}: R-A3 snapshot anchor missing → {ref}")
                continue
            path = (wroot / tgt).resolve()
            if not path.is_relative_to((wroot / "wiki").resolve()):
                problems.append(f"{rel}: R-A3 knowledge page escapes wiki/ → {tgt}")
                continue
            if not path.is_file():
                problems.append(f"{rel}: R-A3 wiki_refs 指向不存在的页 → {tgt}")
                continue
            if lock_path.exists() and subprocess.run(
                ["git", "-C", str(wroot), "cat-file", "-e", f"HEAD:{tgt}"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False
            ).returncode:
                problems.append(f"{rel}: R-A3 page is not in the locked revision → {tgt}")
                continue
            if frag:
                got = anchors_of(path, cache) or set()
                if frag not in got:
                    problems.append(f"{rel}: R-A3 wiki_refs 锚点算不出来 → {tgt}#{frag}"
                                    + _near(frag, got))

        # ---- R-A1 / R-A2 仓内链接 ----
        targets = [(m.group(1), m.group(2)) for m in LINK_RE.finditer(body)]
        targets += [(None, m.group(1)) for m in REFDEF_RE.finditer(body)]
        for bang, target in targets:
            if bang:                                  # 图片不算引用
                continue
            target = target.strip("<>")
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or target.startswith("#!"):
                external_urls += 1
                continue
            tgt, frag = unquote(parsed.path), unquote(parsed.fragment)
            if tgt == "":
                path = md
            else:
                path = (md.parent / tgt).resolve()
                if not path.is_relative_to(root):
                    problems.append(f"{rel}: R-A2 仓外本地依赖未声明 → {tgt}")
                    continue
                pending = next((p for p in dependencies if path.is_relative_to(p) and not (p / '.git').exists()), None)
                if pending:
                    problems.append(f"{rel}: DEPENDENCY_UNINITIALIZED → {pending.relative_to(root)}（目标 {tgt}）")
                    continue
                if not path.exists():
                    problems.append(f"{rel}: R-A2 链接目标不存在 → {tgt}")
                    continue
            checked += 1
            if not frag:
                continue
            if path.suffix.lower() != ".md":
                problems.append(f"{rel}: R-A1 非 Markdown 锚点未覆盖 → {target}")
                continue
            got = anchors_of(path, cache) or set()
            if frag not in got:
                where = "本文件" if tgt == "" else tgt
                problems.append(f"{rel}: R-A1 锚点算不出来 → {where}#{frag}" + _near(frag, got))

    if verbose:
        if local_only:
            print("LOCAL ONLY: wiki_refs and DEPENDENCIES.json are not validated in this run")
        print(f"检查了 {checked} 处本地链接/知识引用；外部 URL {external_urls} 处（未联网验证）")
        if not referenced:
            print("wiki_refs: 0，跨仓知识声明未覆盖")
        for p in problems:
            print(f"  ❌ {p}")
        if not problems and checked:
            print("  ✅ 全部能解析")
        elif not problems:
            print("  未覆盖：没有本地受检引用")
    return checked, problems, referenced


def _near(frag: str, got: set[str]) -> str:
    import difflib
    near = difflib.get_close_matches(frag, sorted(got), n=1, cutoff=0.6)
    return f"（最接近的是 #{near[0]}）" if near else ""


# ---------------------------------------------------------------- selftest
def selftest() -> int:
    """13 条正对照。**每一条都是「这个输入必须被它抓住」或「必须不被它抓住」**。

    一个只在好输入上跑绿的闸，证明不了它还在工作。
    """
    cases = 0
    fails = []

    def run(name, files, expect_bad, expect_ok_at_least=0):
        nonlocal cases
        cases += 1
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for rel, content in files.items():
                p = root / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content, encoding="utf-8")
            checked, problems, _ = check(root, verbose=False)
            got = len(problems)
            if got != expect_bad:
                fails.append(f"{name}: 期望 {expect_bad} 个问题，实际 {got} —— {problems}")
            elif checked < expect_ok_at_least:
                fails.append(f"{name}: 只扫到 {checked} 处，期望至少 {expect_ok_at_least}")

    H = "# Doc\n\n## Some Heading\n\ntext\n"

    run("① 锚点存在 → 不报", {
        "a.md": "[x](b.md#some-heading)\n", "b.md": H}, 0, 1)
    run("② 标题改了 → 报 R-A1", {
        "a.md": "[x](b.md#some-heading)\n",
        "b.md": "# Doc\n\n## Renamed Heading\n"}, 1)
    run("③ 目标文件不存在 → 报 R-A2", {
        "a.md": "[x](gone.md#any)\n"}, 1)
    run("④ 同文件锚点有效 → 不报", {
        "a.md": "## Local Bit\n\n[x](#local-bit)\n"}, 0, 1)
    run("⑤ 同文件锚点无效 → 报", {
        "a.md": "## Local Bit\n\n[x](#no-such)\n"}, 1)
    run("⑥ 围栏代码块里的坏链接 → 不报（作用域）", {
        "a.md": "```\n[x](b.md#nope)\n```\n", "b.md": H}, 0)
    run("⑦ 代码块里的 # 不算标题 → 链它要报", {
        "a.md": "[x](b.md#fake-heading)\n",
        "b.md": "# Doc\n\n```\n## Fake Heading\n```\n"}, 1)
    run("⑧ 重复标题 → -1 后缀能解析", {
        "a.md": "[x](b.md#dup)\n[y](b.md#dup-1)\n",
        "b.md": "# Doc\n\n## Dup\n\n## Dup\n"}, 0, 2)
    run("⑨ 中文标题 → 锚点保留 CJK", {
        "a.md": "[x](b.md#52-frontmatter-契约)\n",
        "b.md": "# Doc\n\n### 5.2 frontmatter 契约\n"}, 0, 1)
    run("⑩ 外部 URL 带 fragment → 跳过", {
        "a.md": "[x](https://example.com/a.html#frag)\n"}, 0)
    run("⑪ 图片带 fragment → 跳过", {
        "a.md": "![x](b.md#nope)\n", "b.md": H}, 0)
    run("⑫ wiki_refs 指向不存在的页 → 报 R-A3", {
        "skills/s/SKILL.md": "---\nname: s\nwiki_refs:\n  - wiki/nvidia/gone.md\n---\n\n# S\n",
        "skills/KernelWiki-private/wiki/nvidia/here.md": H}, 1)
    run("⑭ 标题里的行内代码是标题正文 → 锚点含它才对（第一次跑真仓撞的 bug）", {
        "a.md": "[x](b.md#--aic-metrics-presets-choose-one)\n",
        "b.md": "# Doc\n\n### `--aic-metrics` Presets (choose one)\n"}, 0, 1)
    run("⑮ 但行内代码里的链接仍然不算引用（作用域没放宽）", {
        "a.md": "`[x](gone.md#nope)`\n"}, 0)
    run("⑬ wiki_refs 路径 ＋ 锚点都对 → 不报", {
        "skills/s/SKILL.md": "---\nname: s\nwiki_refs:\n  - wiki/nvidia/here.md#some-heading\n---\n\n# S\n",
        "skills/KernelWiki-private/wiki/nvidia/here.md": H}, 0, 1)
    run("普通文件目标不存在也失败", {"a.md": "[missing](gone.md)"}, 1)
    run("目录和源码目标可检查", {"a.md": "[src](lib/x.py) [dir](lib)", "lib/x.py": "pass"}, 0, 2)
    run("带空格及标题的链接", {"a.md": '[x](<some file.md>) [y](b.md "title")', "some file.md": H, "b.md": H}, 0, 2)
    run("未初始化外部树单独报缺项", {"a.md": "[x](external/up/x.md)", ".gitmodules": '[submodule "up"]\npath = external/up\nurl = https://example.com/up\n'}, 1)

    for f in fails:
        print(f"  ❌ {f}")
    print(f"selftest {cases - len(fails)}/{cases}")
    return 1 if fails else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", nargs="?", default=".")
    ap.add_argument("--strict", action="store_true", help="有问题就非零退出")
    ap.add_argument("--print-refs", action="store_true",
                    help="列出被 wiki_refs 引用到的页 —— 给 KernelWiki 侧做反向检查用")
    ap.add_argument("--selftest", action="store_true")
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--wiki-root", type=Path, help="Explicit local KernelWiki checkout")
    group.add_argument("--wiki-snapshot", type=Path, help="Versioned service export: repository, revision, pages")
    ap.add_argument("--local-only", action="store_true", help="Explicitly check only local links; knowledge coverage is reported as untested")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    snapshot = json.loads(a.wiki_snapshot.read_text()) if a.wiki_snapshot else None
    knowledge_root = a.wiki_root or (Path(os.environ['KERNELWIKI_ROOT']) if os.environ.get('KERNELWIKI_ROOT') and not snapshot else None)
    checked, problems, referenced = check(Path(a.root), verbose=not a.print_refs,
                                         knowledge_root=knowledge_root, snapshot=snapshot, local_only=a.local_only)
    if a.print_refs:
        for r in sorted(referenced):
            print(r)
        return 1 if (problems and a.strict) else 0
    return 1 if (problems and a.strict) else 0


if __name__ == "__main__":
    sys.exit(main())
