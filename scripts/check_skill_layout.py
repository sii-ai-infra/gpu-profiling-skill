#!/usr/bin/env python3
"""skill 仓骨架闸：一个仓的目录形态、轴声明与格覆盖是不是合规的。

    python3 scripts/check_skill_layout.py [<repo-root>] [--strict]
    python3 scripts/check_skill_layout.py --selftest

这道闸存在的理由，和 13 号文档里那张对比表是同一件事：四个已有的 skill 仓
在三个维度上整齐地分成两族（references/ vs reference/、scripts/ vs helpers/、
有没有 agents/），因为它们是两拨人在两个时期各自 clone 出来的。**约定写在
文档里没人守，写成闸才守得住。**

规则（R4/R7/R8 是 warn，其余是 error）：

  R1 形态    根 `SKILL.md` 与 `skills/` 二选一，不能同时有 —— 同时有会让
             同一份 skill 被 create_task.py 的扫描算两次
  R2 轴      每份 SKILL.md 的 vendor / languages / architectures 三根轴齐全 ——
             缺任意一根，_skill_axes 返回 None 然后 continue，**静默不路由**
  R3 格      仓内每份 skill 覆盖的格必须完全相同。单格仓就是一个格，
             跨格仓（profiling / autotune）也必须仓内一致
  R4 根目录  只许出现白名单里的条目（warn）
  R5 方言    不许有 reference/（单数）或 helpers/ —— 统一成 references/ 和 scripts/
  R6 接口    agents/openai.yaml 若存在，display_name 与 short_description 非空
  R7 篇幅    router ≤ 300 行；references/ 每份 ≤ 200 行（warn）
  R9 路由表  references/ 非空时，router 必须至少链到其中一份 ——
             「该读哪份」这件事要写在 router 里，不能靠文件名排序去猜

⚠️ 它判的是**形态**，判不了内容对不对。内容要人读，或者交给
score_skill_routing.py / score_knowledge_reachability.py。
"""
from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path

CELLS = (("nvidia", "cuda-cpp"), ("nvidia", "triton"),
         ("ascend", "ascendc"), ("ascend", "triton-ascend"))

ROOT_ALLOWED = {
    "README.md", "SKILL.md", "LICENSE", "CLAUDE.md", "AGENTS.md",
    ".gitignore", ".gitmodules", ".git", ".github",
    "agents", "references", "scripts", "evals", "examples", "skills", "external",
}
BANNED_DIRS = {"reference": "references", "helpers": "scripts"}

ROUTER_MAX = 300
REFERENCE_MAX = 200


def axes(skill_md: Path) -> dict | None:
    """与 create_task.py:_skill_axes 同语义：缺任意一根轴就是 None。"""
    try:
        text = skill_md.read_text(encoding="utf-8")
    except OSError:
        return None
    if not text.startswith("---"):
        return None
    front = text.split("---", 2)[1]
    out = {}
    for key in ("vendor", "languages", "architectures"):
        m = re.search(rf"(?m)^{key}:[ \t]*(.*)$", front)
        if not m:
            return None
        vals = [v.strip().strip("\"'") for v in m.group(1).strip().strip("[]").split(",") if v.strip()]
        if not vals:
            return None
        out[key] = vals
    return out


def cells_of(a: dict) -> frozenset:
    return frozenset((v, l) for (v, l) in CELLS
                     if ("*" in a["vendor"] or v in a["vendor"])
                     and ("*" in a["languages"] or l in a["languages"]))


def skill_mds(root: Path) -> tuple[list[Path], str]:
    """返回 (SKILL.md 列表, 形态)。形态 ∈ single / multi / both / empty。"""
    single = root / "SKILL.md"
    inner = root / "skills"
    multi = sorted(inner.glob("*/SKILL.md")) if inner.is_dir() else []
    if single.is_file() and multi:
        return [single, *multi], "both"
    if single.is_file():
        return [single], "single"
    if multi:
        return multi, "multi"
    return [], "empty"


def check(root: Path) -> tuple[list[str], list[str], str]:
    err: list[str] = []
    warn: list[str] = []
    mds, shape = skill_mds(root)

    # R1
    if shape == "both":
        err.append("R1 根 SKILL.md 与 skills/ 同时存在 —— 扫描会把同一份 skill 算两次，二选一")

    # R5
    for bad, good in BANNED_DIRS.items():
        if (root / bad).is_dir():
            err.append(f"R5 有 `{bad}/` —— 统一改名成 `{good}/`")

    # R4（R5 已经单独报过的方言目录不重复报）
    for item in sorted(root.iterdir()):
        if item.name not in ROOT_ALLOWED and item.name not in BANNED_DIRS:
            warn.append(f"R4 根目录多了 `{item.name}` —— 散文件应进 references/，产物应进 .gitignore")

    # R2 / R3 / R7 / R9
    seen: dict[frozenset, list[str]] = {}
    for md in mds:
        rel = md.relative_to(root)
        a = axes(md)
        if a is None:
            err.append(f"R2 {rel} 三根轴不齐 —— 静默不路由，create_task.py 会跳过它")
            continue
        cov = cells_of(a)
        if not cov:
            err.append(f"R2 {rel} 的轴不落在任何一个格里：{a['vendor']} × {a['languages']}")
            continue
        seen.setdefault(cov, []).append(str(rel))

        n = len(md.read_text(encoding="utf-8").splitlines())
        if n > ROUTER_MAX:
            warn.append(f"R7 {rel} {n} 行 > {ROUTER_MAX} —— router 装判断，手法搬去 references/")

        refs = md.parent / "references"
        if refs.is_dir() and any(refs.rglob("*.md")):
            body = md.read_text(encoding="utf-8")
            if "references/" not in body:
                err.append(f"R9 {rel} 有 references/ 却一份都没链 —— 「该读哪份」要写在 router 里")

    if len(seen) > 1:
        err.append("R3 仓内 skill 覆盖的格不一致：" + " ｜ ".join(
            f"{sorted(c)} ← {', '.join(f)}" for c, f in sorted(seen.items(), key=lambda kv: sorted(kv[0]))))

    # R7 references
    for refs in list(root.glob("references")) + list(root.glob("skills/*/references")):
        for f in sorted(refs.rglob("*.md")):
            n = len(f.read_text(encoding="utf-8").splitlines())
            if n > REFERENCE_MAX:
                warn.append(f"R7 {f.relative_to(root)} {n} 行 > {REFERENCE_MAX}")

    # R6
    for y in list(root.glob("agents/openai.yaml")) + list(root.glob("skills/*/agents/openai.yaml")):
        t = y.read_text(encoding="utf-8")
        for key in ("display_name", "short_description"):
            m = re.search(rf"(?m)^\s*{key}:\s*(.+)$", t)
            if not m or not m.group(1).strip().strip('"\''):
                err.append(f"R6 {y.relative_to(root)} 的 {key} 缺失或为空")

    return err, warn, shape


def report(root: Path, strict: bool) -> int:
    err, warn, shape = check(root)
    label = {"single": "单 skill 仓", "multi": "多 skill 仓",
             "both": "🔴 两种形态并存", "empty": "⚪ 空仓（scaffold）"}[shape]
    print(f"{root}  {label}")
    for e in err:
        print(f"  🔴 {e}")
    for w in warn:
        print(f"  ⚠️ {w}")
    if not err and not warn:
        print("  ✅ 骨架合规")
    return 1 if (err or (strict and warn)) else 0


_FM = """---
name: {n}
description: d
vendor: [{v}]
languages: [{l}]
architectures: ["*"]
---
# t
"""


def run_selftest() -> int:
    checks = []
    with tempfile.TemporaryDirectory() as td:
        # 正对照 1：合规的单 skill 仓
        ok = Path(td) / "ok"
        (ok / "references").mkdir(parents=True)
        (ok / "SKILL.md").write_text(_FM.format(n="a", v="ascend", l="ascendc")
                                     + "\n见 references/x.md。\n", encoding="utf-8")
        (ok / "references" / "x.md").write_text("# x\n", encoding="utf-8")
        e, w, sh = check(ok)
        checks.append(("合规单 skill 仓不报错", not e and not w and sh == "single"))

        # R1：两种形态并存
        both = Path(td) / "both"
        (both / "skills" / "b").mkdir(parents=True)
        (both / "SKILL.md").write_text(_FM.format(n="a", v="ascend", l="ascendc"), encoding="utf-8")
        (both / "skills" / "b" / "SKILL.md").write_text(_FM.format(n="b", v="ascend", l="ascendc"), encoding="utf-8")
        checks.append(("R1 两种形态并存被抓到", any(x.startswith("R1") for x in check(both)[0])))

        # R2：缺一根轴
        noax = Path(td) / "noax"
        noax.mkdir()
        (noax / "SKILL.md").write_text("---\nname: a\ndescription: d\nvendor: [ascend]\n---\n", encoding="utf-8")
        checks.append(("R2 缺轴被抓到", any(x.startswith("R2") for x in check(noax)[0])))

        # R3：仓内两份 skill 落不同格
        mix = Path(td) / "mix"
        for n, l in (("a", "ascendc"), ("b", "triton-ascend")):
            (mix / "skills" / n).mkdir(parents=True)
            (mix / "skills" / n / "SKILL.md").write_text(_FM.format(n=n, v="ascend", l=l), encoding="utf-8")
        checks.append(("R3 仓内跨格被抓到", any(x.startswith("R3") for x in check(mix)[0])))

        # R5：目录方言
        dia = Path(td) / "dia"
        (dia / "reference").mkdir(parents=True)
        (dia / "helpers").mkdir()
        (dia / "SKILL.md").write_text(_FM.format(n="a", v="ascend", l="ascendc"), encoding="utf-8")
        e5 = check(dia)[0]
        checks.append(("R5 reference/ 与 helpers/ 都被抓到",
                       sum(x.startswith("R5") for x in e5) == 2))

        # R4：根目录散文件
        stray = Path(td) / "stray"
        stray.mkdir()
        (stray / "SKILL.md").write_text(_FM.format(n="a", v="ascend", l="ascendc"), encoding="utf-8")
        (stray / "blackwell-guidelines.md").write_text("x\n", encoding="utf-8")
        checks.append(("R4 根目录散文件被抓到", any(x.startswith("R4") for x in check(stray)[1])))

        # R9：有 references 却不链
        nolink = Path(td) / "nolink"
        (nolink / "references").mkdir(parents=True)
        (nolink / "references" / "x.md").write_text("# x\n", encoding="utf-8")
        (nolink / "SKILL.md").write_text(_FM.format(n="a", v="ascend", l="ascendc"), encoding="utf-8")
        checks.append(("R9 有 references 不链被抓到", any(x.startswith("R9") for x in check(nolink)[0])))

        # R6：接口字段空
        bad6 = Path(td) / "bad6"
        (bad6 / "agents").mkdir(parents=True)
        (bad6 / "SKILL.md").write_text(_FM.format(n="a", v="ascend", l="ascendc"), encoding="utf-8")
        (bad6 / "agents" / "openai.yaml").write_text('interface:\n  display_name: ""\n  short_description: "s"\n', encoding="utf-8")
        checks.append(("R6 接口字段为空被抓到", any(x.startswith("R6") for x in check(bad6)[0])))

        # 跨格仓（profiling / autotune）合法：仓内一致就行
        cross = Path(td) / "cross"
        cross.mkdir()
        (cross / "SKILL.md").write_text(_FM.format(n="p", v="ascend", l='"*"'), encoding="utf-8")
        checks.append(("跨格仓（languages:*）不误报", not check(cross)[0]))

    bad = 0
    for label, ok_ in checks:
        print(f"  {'✅' if ok_ else '🔴'} {label:<30} {'正对照命中' if ok_ else '**没有命中——这条判定是坏的**'}")
        bad += 0 if ok_ else 1
    print(f"\n正对照 {len(checks) - bad}/{len(checks)} 通过")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("roots", nargs="*", type=Path, default=None)
    ap.add_argument("--strict", action="store_true", help="warn 也算失败")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return run_selftest()
    roots = args.roots or [Path(__file__).resolve().parents[1]]
    return max(report(r.resolve(), args.strict) for r in roots)


if __name__ == "__main__":
    sys.exit(main())
