#!/usr/bin/env python3
"""skill 仓骨架闸：一个仓的目录形态、轴声明与格覆盖是不是合规的。

    python3 scripts/check_skill_layout.py [<repo-root>] [--strict]
    python3 scripts/check_skill_layout.py --selftest

这道闸存在的理由，和 13 号文档里那张对比表是同一件事：四个已有的 skill 仓
在三个维度上整齐地分成两族（references/ vs reference/、scripts/ vs helpers/、
有没有 agents/），因为它们是两拨人在两个时期各自 clone 出来的。**约定写在
文档里没人守，写成闸才守得住。**

规则（R4/R7 是 warn，其余是 error）：

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
  R10 二级   references/ 超过阈值份数、**或**起了第二层目录 ⇒ 该层要有
             index.md，且 router 只链 index 不链叶子（13 §3.2）
  R11 判据   evals/content.json 存在、非空、每条 assert 带 must_fail_on（13 §3.4）
  R12 白名单 产品线仓要有 PACKAGE.txt，且**双向**自洽（13 §5 / §2）

  --check-vendored  各 skill 仓里 vendored 的本文件副本必须与本仓一致 ——
                    参数外置之后，「改了哪份副本」才是真正的漂移面

⚠️ 它判的是**形态**，判不了内容对不对。内容要人读，或者交给
score_skill_routing.py / score_knowledge_reachability.py。


R10：作用域是 **per-skill**，不是按仓合计
─────────────────────────────────────────────────────────────────────────
一棵 references/ 树，归**和它同级的那份 SKILL.md**（router）所有 ——
和 R9 的 `md.parent / "references"` 同一个模型。多 skill 仓里
`skills/a/references/` 与 `skills/b/references/` 分别计数，不相加。

**为什么不是按仓合计**：13 §3.2 给这条阈值的论证是「router 那张表的规模有
上限 —— SKILL.md 只有 300 行，路由表最多占十几行」。**受这个上限约束的是
一份 router 要指向多少个条目**，而多 skill 仓里每份 skill 有自己的 router，
所以数的是 per-skill 的份数。两个 skill 各 5 份（合计 10）不触发，
一个 skill 自己 9 份才触发。selftest 有一条正对照钉住这一点。

同理，「起了第二层目录」数的是 `<router 所在目录>/references/<sub>/`，
不是仓根的 `references/<sub>/`。

⚠️ **已知盲区**：多 skill 仓的**仓根** references/（旁边没有 SKILL.md）
没有 router，R10 看不见它 —— R9 今天就有同一个盲区。它仍被 R4/R7 看着。
父仓 kernel-opt-pipeline 的根 references/ 装的是 task 模板不是手法层，
所以这个盲区目前没有代价；哪天仓根 references/ 真的变成手法层，这条要改。


R11：判「有没有把判据写下来」，不判「答案对不对」
─────────────────────────────────────────────────────────────────────────
只看三件事：文件在不在、有没有内容、**每条 assert 有没有配一个必须被它判挂的
must_fail_on**。断言写得对不对是 eval 跑出来的，不是这里判的。

⚠️ 13 §3.4 的两条规矩里，只有①（正对照）在这道闸里。②（「不许只写单个
contains 的技术名词」）**故意没做**：那是内容判断，做进来这道闸就会变成一个
半吊子的内容检查器 —— 而华为 cannbot-skills 那条 `{type: contains,
pattern: "NpuArch"}` 的教训恰恰是「判据落在不是内容的那一层上」，
不能用同一个错误去修它。

⚠️ must_fail_on 的位置：13 §5 写「每条 assert 带 must_fail_on」，而 §3.4 的
样例把它放在 case 一级（那个样例只有一条 assert）。这里两种都收，但**只有
case 里恰好一条 assert 时才允许放 case 一级** —— 一个 case 挂三条 assert
配一个反例，证明不了那三条各自还在工作。


R12：它断言的是「白名单自洽」，**不是「发布已经安全了」**
─────────────────────────────────────────────────────────────────────────
两条反向断言，缺一条就等于没有（对照 cannbot 的 DG-10 / DG-11）：

  A 方向：PACKAGE.txt 里写的每条路径都要在仓里存在 —— 挡「幽灵条目」；
  B 方向：被 SKILL.md / references 引用到的仓内文件都要在白名单里 —— 挡
          「该发的没写进白名单」。只做 A 会漏掉 B，反过来也一样。

⚠️ **别把它读成发布保证**（13 §8 U6）。白名单写在 skill 仓里，**打包发生在
产品侧**（01 §2.4 是一次无白名单的 copytree）。这道闸看得见的只有仓内这份
声明自不自洽；**它证明不了打包那一侧真的读了这份白名单**。真正的闭环要产品
侧配合；在那之前 R12 是「声明 ＋ 自洽检查」。

**怎么判「产品线仓」**：13 §3.1 定的标记是 —— 冲榜线仓的 README **开头**
写死「不上产品线」。所以判据是「README 前 N 行里有没有这个标记」，
**默认倒向产品线仓**（没标记 ⇒ 当成要发布的，R12 生效）。

⚠️ 这个方向是故意选的。两种误判的代价不对称：
  · 冲榜线仓忘了写标记 ⇒ 被当成产品线仓 ⇒ 多报一条红。**响的**，
    而且修法正是 §3.1 要的那件事（把标记写上）；
  · 产品线仓被当成冲榜线仓 ⇒ R12 整条静默跳过 ⇒ 一个真的会随产品发出去的仓
    没有任何东西在看它的白名单。**这正是 R12 存在的理由**。
⇒ 宁可误伤冲榜线仓，不可放过产品线仓。selftest 里两个方向各有一条正对照。


老仓豁免：LEGACY_EXEMPT，**每条都由闸自己去验**
─────────────────────────────────────────────────────────────────────────
R10/R11/R12 一上，今天所有仓立刻红（evals/content.json 全仓 0 份、
PACKAGE.txt 全仓 0 份、三个仓的 references/ 已经越线）。没有豁免，
--strict 在 main 上直接全红，这道闸根本上不了线。

但白名单就是第二个真源，所以它自带反向断言（13 §5.2：**没有反向断言的白名单，
就是下一个静默漂移；你不能靠一份名单证明名单本身还是对的**）：

  **一个仓被豁免、但它其实已经合规了 ⇒ 闸报 BAD_EXCEPTION，点名要求删条目。**

做法照 scripts/check_merged_prs_landed.py 的 EXCEPTIONS：豁免不是「跳过检查」，
是「照跑，跑完拿结果去验这条豁免还成不成立」。

⚠️ 两个已知边界，写在这里免得下一个人以为它更强：
  · 名单里那些**本仓看不见**的条目（submodule 没初始化 / 那个仓在别处）
    只能打到 stderr 的 note，不能算红 —— 否则每个 skill 仓单独跑 vendored
    副本时都会因为「看不见别的仓」而红。过期条目要靠父仓这一侧跑出来。
  · shape == empty 的 scaffold 仓整体跳过 R10/R11/R12（13 §6.5 要它们报绿），
    所以针对空仓的豁免条目也验不了。
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

# ═══════════════════════════════════════════════════════════════════════
# 规则参数 —— 要调阈值或白名单改这里，不要去改下面的判断逻辑
# ═══════════════════════════════════════════════════════════════════════
# 13 §5.0 说要「像 cannbot 那样把阈值外置成 rules.yaml」。**照抄会让情况更糟**：
# 他们的闸只有一份（tests/lib/），外置就是把 1 个文件变成 2 个、同步面不变；
# 我们这份是 **vendored 进每个 skill 仓的**（今天 8 份副本，字节相同），
# 外置成 YAML 等于把同步面从 8 变成 16，而且没有任何东西在看它们一致。
#
# 所以这里做的是**同一个目的的另一种实现**：
#   ① 所有可调项集中在下面这个 RULES 字典 —— cannbot 那句
#      "edit this rather than hacking the code" 的实质就达到了；
#   ② 真需要按仓改阈值时，放一份 skill_rules.yaml 在本文件旁边即可覆盖
#      （PyYAML 缺失就跳过并说出来，不静默）；
#   ③ 顺手补上今天真正缺的那道闸：`--check-vendored` 断言各仓的副本一致。
#      **没有这一条，"外置"只是把漂移换了个位置。**
RULES = {
    "cells": [["nvidia", "cuda-cpp"], ["nvidia", "triton"],
              ["ascend", "ascendc"], ["ascend", "triton-ascend"]],
    "root_allowed": [
        "README.md", "SKILL.md", "LICENSE", "CLAUDE.md", "AGENTS.md",
        ".gitignore", ".gitmodules", ".git", ".github",
        "agents", "references", "scripts", "evals", "examples", "skills", "external",
        "DEPENDENCIES.json",     # versioned external knowledge contract
        "PACKAGE.txt",            # R12 的白名单文件，见下面 package_file
    ],
    "banned_dirs": {"reference": "references", "helpers": "scripts"},
    "router_max_lines": 300,      # R7 —— E7c 的形态判据
    "reference_max_lines": 200,   # R7
    # R10 —— 一份 router 的路由表指向多少个条目还撑得住（13 §3.2）
    "references_index_threshold": 8,
    # R11 —— 判据文件叫什么、放在 skill 单元的哪个子目录下
    "evals_dir": "evals",
    "evals_content_file": "content.json",
    # R12 —— 白名单文件名，以及「冲榜线仓」的标记（13 §3.1）
    "package_file": "PACKAGE.txt",
    "offline_marker": "不上产品线",
    # 标记只认 README 开头这几行：写在正文深处的一句话不算「写死在第一行」
    "offline_marker_lines": 3,
}


def _load_overrides() -> None:
    """可选：本文件旁边的 skill_rules.yaml 覆盖 RULES 里的同名键。

    缺 PyYAML 或缺文件都不算错，但**要说出来**——一个静默失效的覆盖机制
    比没有覆盖机制更坏。
    """
    path = Path(__file__).with_name("skill_rules.yaml")
    if not path.is_file():
        return
    try:
        import yaml
    except ImportError:
        print(f"warning: 有 {path.name} 但没装 PyYAML，按内置 RULES 跑", file=sys.stderr)
        return
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:                       # noqa: BLE001
        print(f"warning: {path.name} 解析失败（{exc}），按内置 RULES 跑", file=sys.stderr)
        return
    unknown = set(data) - set(RULES)
    if unknown:
        print(f"warning: {path.name} 里有 RULES 不认识的键：{sorted(unknown)}", file=sys.stderr)
    for k in set(data) & set(RULES):
        RULES[k] = data[k]
        print(f"note: {path.name} 覆盖 {k} = {data[k]!r}", file=sys.stderr)


_load_overrides()

CELLS = tuple(tuple(c) for c in RULES["cells"])
# PACKAGE_FILE 一定在白名单里：改了 package_file 却忘了改 root_allowed，
# 结果会是 R12 要求的那个文件被 R4 报成「根目录散文件」。
ROOT_ALLOWED = set(RULES["root_allowed"]) | {str(RULES["package_file"])}
BANNED_DIRS = dict(RULES["banned_dirs"])
ROUTER_MAX = int(RULES["router_max_lines"])
REFERENCE_MAX = int(RULES["reference_max_lines"])
REFS_INDEX_MAX = int(RULES["references_index_threshold"])
EVALS_DIR = str(RULES["evals_dir"])
EVALS_CONTENT = str(RULES["evals_content_file"])
PACKAGE_FILE = str(RULES["package_file"])
OFFLINE_MARKER = str(RULES["offline_marker"])
OFFLINE_MARKER_LINES = int(RULES["offline_marker_lines"])

# ═══════════════════════════════════════════════════════════════════════
# 老仓豁免 —— 每条都必须能被下面的反向断言验过（见文件头 docstring）
# ═══════════════════════════════════════════════════════════════════════
# key 是「谁」：skills/<name>/ 就是 <name>；仓根用 git origin 的仓名
# （拿不到就退回目录名 —— 工作树的目录名不一定等于仓名）。
# 同一个仓在两种跑法下可能有两个名字（父仓里是 submodule 路径名，单独 clone
# 是远端仓名，而且三个仓远端已改名），所以每条可以带 aliases。
LEGACY_EXEMPT: dict[str, dict] = {
    # ── R11：evals/content.json 今天全仓 0 份 ──────────────────────────
    "kernel-autotune": {
        "rules": ["R11", "R12"], "aliases": ["kernel-autotune-skill"],
        "why": "13 §6.4：这个仓的改动本来就排在最后",
    },
    "KernelWiki-private": {"rules": ["R11", "R12"], "why": "知识库仓，判据随 E16 一起写"},
    # 三份 ascendc-* 的 R11 豁免已删（2026-09-10）：它们随 13 §7 第 4 步迁进
    # ascendc-skill，content.json 一落地，反向断言当场点名「豁免已经作废，
    # 它现在是合规的」。**名单自己会过期，而它会说出来** —— 13 §5.2。
    "agent-harness-ops": {"rules": ["R11"], "why": "父仓自带的 skill，判据待写"},
    "pipeline": {"rules": ["R11"], "why": "父仓自带的 skill，判据待写"},
    "scaffold": {"rules": ["R11"], "why": "父仓自带的 skill，判据待写"},
    # ── R12：PACKAGE.txt 今天全仓 0 份 ─────────────────────────────────
    "kernel-opt-pipeline": {
        "rules": ["R11", "R12"],
        "why": "父仓是产品侧本身，不是被打包进产品的 skill 仓；"
               "PACKAGE.txt 该不该有要等 U6（打包侧读不读白名单）有结论",
    },
}


def _exempt_entry(key: str) -> tuple[str, dict] | None:
    for name, ent in LEGACY_EXEMPT.items():
        if key == name or key in ent.get("aliases", ()):
            return name, ent
    return None


def _is_exempt(key: str, rule: str) -> bool:
    hit = _exempt_entry(key)
    return bool(hit and rule in hit[1]["rules"])


def repo_key(root: Path) -> str:
    """仓的身份。优先 git origin 的仓名 —— 工作树目录名不一定等于仓名。"""
    try:
        p = subprocess.run(["git", "-C", str(root), "config", "--get", "remote.origin.url"],
                           capture_output=True, text=True, timeout=5)
        url = p.stdout.strip()
    except Exception:                                  # noqa: BLE001
        url = ""
    if url:
        return url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
    return root.name


def unit_key(root: Path, md: Path) -> str:
    """一份 SKILL.md 归谁：skills/<name>/ 就是 <name>，仓根就是仓名。"""
    rel = md.relative_to(root).parts
    if len(rel) >= 2 and rel[0] == "skills":
        return rel[1]
    return repo_key(root)


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


_FENCE = re.compile(r"(?ms)^[ \t]*```.*?^[ \t]*```[ \t]*$")
_INLINE_CODE = re.compile(r"`[^`\n]*`")
_MD_LINK = re.compile(r"!?\[[^\]]*\]\(\s*([^)\s]+)")


def md_links(path: Path) -> list[str]:
    """一份 .md 里的 markdown 链接目标（去掉 #fragment）。

    围栏代码块和行内代码里的不算 —— 那是**示例**不是引用。这条作用域是
    check_wiki_anchors.py 撞出来的（13 §5.3）：抹行内代码只能用在「找链接」
    这一侧，不能用在算锚点那一侧。
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    text = _INLINE_CODE.sub(" ", _FENCE.sub("\n", text))
    out = []
    for t in _MD_LINK.findall(text):
        t = t.split("#", 1)[0].strip().strip("<>")
        if t and "://" not in t and not t.startswith(("#", "mailto:", "/")):
            out.append(t)
    return out


def referenced_files(root: Path, mds: list[Path]) -> list[str]:
    """仓内被 SKILL.md / references 引用到的文件，相对仓根的 posix 路径。

    SKILL.md 自己也算 —— 它是引用图的根，白名单漏了它就等于什么都没发。
    """
    sources = list(mds)
    for refs in list(root.glob("references")) + list(root.glob("skills/*/references")):
        sources += sorted(refs.rglob("*.md"))
    hit: set[str] = set()
    rootr = root.resolve()
    for src in sources:
        try:
            hit.add(src.relative_to(root).as_posix())
        except ValueError:
            continue
        for link in md_links(src):
            tgt = (src.parent / link).resolve()
            try:
                rel = tgt.relative_to(rootr).as_posix()
            except ValueError:
                continue          # 指到仓外去了，那是别的闸的事
            if tgt.is_file():
                hit.add(rel)
    return sorted(hit)


def covered_by(rel: str, entries: list[str]) -> bool:
    for e in entries:
        e = e.strip()
        if not e:
            continue
        if rel == e or rel.startswith(e.rstrip("/") + "/"):
            return True
        if any(ch in e for ch in "*?[") and fnmatch.fnmatch(rel, e):
            return True
    return False


def is_offline_repo(root: Path) -> bool:
    """冲榜线仓的标记：README **开头** 写死「不上产品线」（13 §3.1）。

    只认前 RULES["offline_marker_lines"] 行 —— 正文深处提一句不算「写死」。
    ⚠️ 判不出来就当成产品线仓（见文件头 docstring 的方向论证）。
    """
    rd = root / "README.md"
    if not rd.is_file():
        return False
    try:
        head = rd.read_text(encoding="utf-8").splitlines()[:OFFLINE_MARKER_LINES]
    except OSError:
        return False
    return any(OFFLINE_MARKER in ln for ln in head)


def layer_entries(d: Path) -> int:
    """这一层要路由到几个条目：直接躺着的 .md（不含 index.md）＋ 装着 .md 的子目录。

    只有一个条目的层不需要 index.md —— 那张表会只有一行。
    ⚠️ 这条是对真仓跑出来的：triton-ascend 的
    `references/low-level-api-details/al/<API>/README.md` 是 30 个**只装一页**的
    目录。不加这一条，闸会要求它们各写一份只有一行的 index.md ——
    那时候红的是尺子，不是被测的仓。
    """
    n = len([f for f in d.glob("*.md") if f.name != "index.md"])
    n += len([sub for sub in d.iterdir() if sub.is_dir() and any(sub.rglob("*.md"))])
    return n


def r10_problems(md: Path, root: Path) -> list[str]:
    """R10：这一份 router 自己的 references/ 树够不够格要一层 index.md。

    作用域 per-skill，见文件头 docstring。
    """
    refs = md.parent / "references"
    if not refs.is_dir():
        return []
    here = refs.relative_to(root).as_posix()
    leaves = sorted(p for p in refs.rglob("*.md") if p.name != "index.md")
    subdirs = sorted({p.parent for p in leaves if p.parent != refs})
    why = []
    if len(leaves) > REFS_INDEX_MAX:
        why.append(f"{len(leaves)} 份 > {REFS_INDEX_MAX}")
    if subdirs:
        why.append(f"起了第二层（{len(subdirs)} 个子目录装着 .md）")
    if not why:
        return []
    because = f"{here} " + "、".join(why)
    layers = [refs] + sorted(d for d in refs.rglob("*") if d.is_dir() and any(d.rglob("*.md")))
    missing = [d for d in layers if layer_entries(d) > 1 and not (d / "index.md").is_file()]
    if missing:
        names = [d.relative_to(root).as_posix() + "/index.md" for d in missing]
        shown = "，".join(names[:5]) + (f" …（共 {len(names)} 处）" if len(names) > 5 else "")
        # ⚠️ 有些层已经有一份 README.md 在做同一件事（npu 的 references/msopprof/
        # 就是一张 8 行的文件表），只是名字不叫 index.md、而且 router 没链它。
        # **先说出来**，免得下一个人在旁边再写一份第二真源。
        dup = [d.relative_to(root).as_posix() + "/README.md" for d in missing
               if (d / "README.md").is_file()]
        tail = (f"（⚠️ {'、'.join(dup[:3])} 看起来已经在做这件事了 —— "
                f"是改名成 index.md，还是让这条规则也认 README.md？先判一下，别写第二份）"
                if dup else "")
        return [f"R10 {because} —— 该层要有 index.md，router 只链 index 不链叶子：缺 {shown}{tail}"]
    body = md.read_text(encoding="utf-8")
    out = []
    if (refs / "index.md").is_file() and "references/index.md" not in body:
        out.append(f"R10 {because}，index.md 有了但 router 没链它 —— 路由表要指向 index")
    linked = [p.relative_to(md.parent).as_posix() for p in leaves
              if p.relative_to(md.parent).as_posix() in body]
    if linked:
        shown = "，".join(linked[:5]) + (f" …（共 {len(linked)} 条）" if len(linked) > 5 else "")
        out.append(f"R10 {because}，router 直接链了叶子：{shown} —— 收进 index.md，"
                   f"router 那张表有 {ROUTER_MAX} 行的上限，撑不到二三十份")
    # Every published reference must be reachable through the index graph.
    seen, pending = set(), [refs / "index.md"]
    while pending:
        page = pending.pop().resolve()
        if page in seen or not page.is_file() or not page.is_relative_to(refs.resolve()):
            continue
        seen.add(page)
        pending.extend((page.parent / target).resolve() for target in md_links(page))
    orphans = [p.relative_to(md.parent).as_posix() for p in refs.rglob("*.md")
               if p.resolve() not in seen]
    if orphans:
        out.append(f"R10 index 不可达的 reference：{', '.join(sorted(orphans)[:8])}"
                   f"（共 {len(orphans)} 份）")
    return out


def r11_problems(md: Path, root: Path) -> list[str]:
    """R11：这个 skill 单元有没有把自己的判据写下来，写下来的有没有正对照。

    ⚠️ 不判答案对不对 —— 那是 eval 跑出来的。见文件头 docstring。
    """
    label = md.parent.relative_to(root).as_posix() or "."
    path = md.parent / EVALS_DIR / EVALS_CONTENT
    if not path.is_file():
        hint = ""
        d = md.parent / EVALS_DIR
        if d.is_dir() and not [p for p in d.iterdir() if p.name != ".gitkeep"]:
            hint = "（evals/ 里只躺着 .gitkeep —— **有目录没内容，比没有目录更容易骗人**）"
        return [f"R11 {label} 缺 {EVALS_DIR}/{EVALS_CONTENT}{hint} —— 判据要写在 skill 自己旁边（13 §3.4）"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:                            # noqa: BLE001
        return [f"R11 {label}/{EVALS_DIR}/{EVALS_CONTENT} 解析不了：{exc}"]
    if not isinstance(data, dict):
        return [f"R11 {label}/{EVALS_DIR}/{EVALS_CONTENT} 顶层不是对象 —— 照 13 §3.4 的形状写"]
    out = []
    if not str(data.get("unit") or "").strip():
        out.append(f"R11 {label} 的 unit 为空 —— 判据要能归因到哪个 skill 单元")
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        out.append(f"R11 {label} 一条 case 都没有 —— 「文件存在」不等于「非空」")
        return out
    for i, c in enumerate(cases):
        cid = (isinstance(c, dict) and str(c.get("id") or "").strip()) or f"#{i + 1}"
        if not isinstance(c, dict):
            out.append(f"R11 {label} case {cid} 不是对象")
            continue
        if not str(c.get("prompt") or "").strip():
            out.append(f"R11 {label} case {cid} 没有 prompt —— 没有输入的判据跑不起来")
        asserts = c.get("assert")
        if not isinstance(asserts, list) or not asserts:
            out.append(f"R11 {label} case {cid} 没有 assert")
            continue
        case_mf = str(c.get("must_fail_on") or "").strip()
        for j, a in enumerate(asserts):
            own = str((a.get("must_fail_on") if isinstance(a, dict) else "") or "").strip()
            if own or (case_mf and len(asserts) == 1):
                continue
            tail = ("（case 一级那条只在这个 case 恰好一条 assert 时算数）" if case_mf else "")
            out.append(f"R11 {label} case {cid} 第 {j + 1} 条 assert 没有 must_fail_on{tail}"
                       " —— 没有正对照的断言，证明不了它还在工作")
    return out


def r12_problems(root: Path, mds: list[Path]) -> list[str]:
    """R12：产品线仓的 PACKAGE.txt 自不自洽（两个方向都要）。

    ⚠️ 它断言的是白名单自洽，**不是发布已经安全了**。见文件头 docstring 与 13 §8 U6。
    """
    if is_offline_repo(root):
        return []
    pkg = root / PACKAGE_FILE
    if not pkg.is_file():
        return [f"R12 缺 {PACKAGE_FILE} —— 产品线仓要声明随产品发布的文件白名单；"
                f"若是冲榜线仓，请在 README 前 {OFFLINE_MARKER_LINES} 行写死"
                f"「{OFFLINE_MARKER}」（13 §3.1）"]
    entries = []
    for ln in pkg.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        entries.append(re.sub(r"\s+#.*$", "", ln).strip())
    entries = [e for e in entries if e]
    out = []
    if not entries:
        out.append(f"R12 {PACKAGE_FILE} 一条都没写 —— 空白名单等于什么都不发")
    # A 方向：白名单里的路径都要存在
    for e in entries:
        ok = bool(list(root.glob(e))) if any(ch in e for ch in "*?[") else (root / e).exists()
        if not ok:
            out.append(f"R12 {PACKAGE_FILE} 的 `{e}` 在仓里找不到 —— 幽灵条目")
    # B 方向：被引用到的文件都要在白名单里
    for rel in referenced_files(root, mds):
        if not covered_by(rel, entries):
            out.append(f"R12 `{rel}` 被 SKILL.md/references 引用到，却不在 {PACKAGE_FILE} 里"
                       " —— 打包会漏掉它")
    return out


def check(root: Path) -> tuple[list[str], list[str], str, set[str]]:
    err: list[str] = []
    warn: list[str] = []
    mds, shape = skill_mds(root)

    # R13: declarations and their version lock form one dependency contract.
    if any(re.search(r"(?m)^wiki_refs:", md.read_text()) for md in mds):
        try:
            lock = json.loads((root / "DEPENDENCIES.json").read_text())
            knowledge = lock["knowledge"]
            if lock.get("schema_version") != 1 or not knowledge.get("repository") or not re.fullmatch(r"[0-9a-f]{40}", knowledge.get("revision", "")):
                raise ValueError("expected schema_version=1, repository and full revision SHA")
        except (OSError, ValueError, TypeError, KeyError) as exc:
            err.append(f"R13 wiki_refs requires a valid DEPENDENCIES.json: {exc}")

    # R10/R11/R12 走豁免通道：先按 (谁, 哪条规则) 记下来，最后再决定
    # 「压住」还是「报出来」，以及**这条豁免自己还成不成立**。
    raw: dict[tuple[str, str], list[str]] = {}
    graded: set[tuple[str, str]] = set()

    def run(key: str, rule: str, msgs: list[str]) -> None:
        graded.add((key, rule))
        if msgs:
            raw.setdefault((key, rule), []).extend(msgs)

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

        # R10 / R11 —— 都以「这份 SKILL.md 所属的 skill 单元」为作用域
        key = unit_key(root, md)
        run(key, "R10", r10_problems(md, root))
        run(key, "R11", r11_problems(md, root))

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

    # R12 —— 仓一级。空壳 scaffold 跳过（13 §6.5 要它们报绿）
    if shape != "empty":
        run(repo_key(root), "R12", r12_problems(root, mds))

    for (key, rule), msgs in sorted(raw.items()):
        if _is_exempt(key, rule):
            continue
        err.extend(msgs)

    # 豁免的反向断言：**被豁免、但其实已经合规 ⇒ 这条豁免该删了**。
    # 没有这一条，LEGACY_EXEMPT 就是下一个静默漂移（13 §5.2）。
    for key, rule in sorted(graded):
        hit = _exempt_entry(key)
        if not hit or rule not in hit[1]["rules"] or raw.get((key, rule)):
            continue
        name, ent = hit
        err.append(f"BAD_EXCEPTION `{name}` 的 {rule} 豁免已经作废 —— 它现在是合规的，"
                   f"把这条从 LEGACY_EXEMPT 里删掉（当初写的理由：{ent['why']}）")

    return err, warn, shape, {k for k, _ in graded}


def report(root: Path, strict: bool) -> int:
    err, warn, shape, present = check(root)
    label = {"single": "单 skill 仓", "multi": "多 skill 仓",
             "both": "🔴 两种形态并存", "empty": "⚪ 空仓（scaffold）"}[shape]
    # 名单里本仓看不见的条目：只能是 note，不能是红 —— 每个 skill 仓跑自己那份
    # vendored 副本时本来就看不见别的仓。过期条目要靠父仓这一侧跑出来。
    # ⚠️ 只在多 skill 仓（＝父仓那种跑法）上说 —— 单个 skill 仓跑自己那份
    # vendored 副本时，本来就看不见别的仓，在那儿说等于每次都刷一屏噪声。
    unseen = [n for n, e in LEGACY_EXEMPT.items()
              if n not in present and not (set(e.get("aliases", ())) & present)]
    if unseen and shape == "multi":
        print(f"note: 豁免名单里有本仓看不见的条目（submodule 没初始化？还是这条过期了？）："
              f"{unseen}", file=sys.stderr)
    print(f"{root}  {label}")
    for e in err:
        print(f"  🔴 {e}")
    for w in warn:
        print(f"  ⚠️ {w}")
    if not err and not warn:
        print("  ✅ 骨架合规")
    return 1 if (err or (strict and warn)) else 0


# 13 §3.4 的样例，原样搬进来当正对照 —— 文档里写得出来的形状，闸必须放行。
_CONTENT_OK = """{
  "unit": "cuda-optimization",
  "cases": [{
    "id": "gather-scatter-not-a-bug",
    "prompt": "我的 kernel 是 gather，ncu 报 uncoalesced global access，要不要改成连续访问？",
    "assert": [
      { "type": "contains_all", "patterns": ["gather", "本来就"],
        "why": "要说出这类 kernel 天然违反合并访问" }
    ],
    "must_fail_on": "改成连续访问就能修好这个告警。"
  }]
}
"""


def _mkrepo(base: Path, name: str, *, refs: list[str] = (), index: bool = False,
            router_links: list[str] = (), skills: dict | None = None,
            content: str | None = _CONTENT_OK, package: str | None = "SKILL.md\nreferences/\n",
            readme: str | None = None) -> Path:
    """搭一个临时 skill 仓。默认是 v2 合规的单 skill 仓。"""
    root = base / name
    root.mkdir(parents=True)
    if readme is not None:
        (root / "README.md").write_text(readme, encoding="utf-8")
    if package is not None:
        (root / PACKAGE_FILE).write_text(package, encoding="utf-8")
    if skills is not None:
        for sname, srefs in skills.items():
            d = root / "skills" / sname
            (d / "references").mkdir(parents=True)
            for f in srefs:
                (d / "references" / f).write_text("# x\n", encoding="utf-8")
            body = "".join(f"见 references/{f}。\n" for f in srefs)
            (d / "SKILL.md").write_text(_FM.format(n=sname, v="ascend", l="ascendc") + body,
                                        encoding="utf-8")
            if content is not None:
                (d / "evals").mkdir()
                (d / "evals" / EVALS_CONTENT).write_text(content, encoding="utf-8")
        return root
    for f in refs:
        p = root / "references" / f
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# x\n", encoding="utf-8")
    if index:
        (root / "references" / "index.md").write_text("# index\n" + "".join(f"- [reference]({f})\n" for f in refs), encoding="utf-8")
    body = "".join(f"见 references/{f}。\n" for f in router_links)
    (root / "SKILL.md").write_text(_FM.format(n=name, v="ascend", l="ascendc") + body,
                                   encoding="utf-8")
    if content is not None:
        (root / "evals").mkdir()
        (root / "evals" / EVALS_CONTENT).write_text(content, encoding="utf-8")
    return root


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
        # 正对照 1：合规的单 skill 仓（v2：带 evals/content.json ＋ PACKAGE.txt）
        ok = _mkrepo(Path(td), "ok", refs=["x.md"], router_links=["x.md"])
        e, w, sh, _p = check(ok)
        checks.append(("v2 合规单 skill 仓不报错", not e and not w and sh == "single"))

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
        (cross / PACKAGE_FILE).write_text("SKILL.md\n", encoding="utf-8")
        (cross / "evals").mkdir()
        (cross / "evals" / EVALS_CONTENT).write_text(_CONTENT_OK, encoding="utf-8")
        checks.append(("跨格仓（languages:*）不误报", not check(cross)[0]))

        # ── R10 ──────────────────────────────────────────────────────
        nine = [f"{i:02d}-a.md" for i in range(9)]
        over = _mkrepo(Path(td), "r10_over", refs=nine, router_links=nine,
                       package="SKILL.md\nreferences/\n")
        checks.append(("R10 >8 份且没有 index.md 被抓到",
                       any(x.startswith("R10") for x in check(over)[0])))

        # 份数没超，但起了第二层 —— 两个触发条件是 or，不是 and
        sub2 = _mkrepo(Path(td), "r10_sub", refs=["a.md", "b.md", "deep/c.md"],
                       router_links=["a.md"])
        checks.append(("R10 起了第二层目录就要 index.md（份数没超也算）",
                       any(x.startswith("R10") for x in check(sub2)[0])))

        # index.md 有了，但 router 还在链叶子
        ten = [f"{i:02d}-a.md" for i in range(10)]
        leaf = _mkrepo(Path(td), "r10_leaf", refs=ten, index=True,
                       router_links=["index.md", "00-a.md"])
        e10 = [x for x in check(leaf)[0] if x.startswith("R10")]
        checks.append(("R10 router 链叶子不链 index 被抓到",
                       any("叶子" in x for x in e10)))

        # 阈值的另一侧：8 份平铺不许报 —— 钉住 references_index_threshold 在数什么
        eight = [f"{i:02d}-a.md" for i in range(8)]
        under = _mkrepo(Path(td), "r10_eight", refs=eight, router_links=eight)
        checks.append(("R10 8 份平铺不误报（阈值边界）",
                       not any(x.startswith("R10") for x in check(under)[0])))

        # 作用域：per-skill，不是按仓合计。两个 skill 各 5 份（合计 10 > 8）不许报。
        # ⚠️ 改这条的人请先读文件头 docstring 里 R10 那段的论证。
        percell = _mkrepo(Path(td), "r10_multi", skills={
            "a": [f"a{i}.md" for i in range(5)], "b": [f"b{i}.md" for i in range(5)]},
            package="skills/\n")
        checks.append(("R10 作用域是 per-skill 不是按仓合计",
                       not any(x.startswith("R10") for x in check(percell)[0])))

        # 尺子标定：只装一页的子目录不要 index.md。
        # ⚠️ 这条是对真仓跑出来的 —— triton-ascend 的
        # references/low-level-api-details/al/<API>/ 是 30 个只装一页的目录，
        # 早一版的闸要求它们各写一份只有一行的 index.md，**那是尺子坏了**。
        onepage = _mkrepo(Path(td), "r10_onepage",
                          refs=[f"{i:02d}-a.md" for i in range(10)] + ["one/only.md"],
                          index=True, router_links=["index.md"])
        checks.append(("R10 只装一页的子目录不要 index.md（尺子标定）",
                       not any(x.startswith("R10") for x in check(onepage)[0])))

        orphan = _mkrepo(Path(td), "r10_orphan", refs=ten, index=True, router_links=["index.md"])
        (orphan / "references/index.md").write_text("# empty index\n")
        checks.append(("R10 空索引无法到达叶子时失败",
                       any("不可达" in x for x in check(orphan)[0])))

        # ── R11 ──────────────────────────────────────────────────────
        gk = _mkrepo(Path(td), "r11_gitkeep", refs=["x.md"], router_links=["x.md"],
                     content=None)
        (gk / "evals").mkdir()
        (gk / "evals" / ".gitkeep").write_text("", encoding="utf-8")
        e11 = [x for x in check(gk)[0] if x.startswith("R11")]
        checks.append(("R11 只有 0 字节 .gitkeep 的 evals/ 被抓到",
                       any(".gitkeep" in x for x in e11)))

        nocase = _mkrepo(Path(td), "r11_empty", refs=["x.md"], router_links=["x.md"],
                         content='{"unit": "u", "cases": []}')
        checks.append(("R11 content.json 存在但零 case 被抓到",
                       any(x.startswith("R11") for x in check(nocase)[0])))

        # 一个 case 挂两条 assert、只配一个 case 一级的 must_fail_on ——
        # 一个反例证明不了两条断言各自还在工作
        two = ('{"unit": "u", "cases": [{"id": "c", "prompt": "p", '
               '"assert": [{"type": "contains_all", "patterns": ["a"]}, '
               '{"type": "contains_all", "patterns": ["b"]}], "must_fail_on": "x"}]}')
        nomf = _mkrepo(Path(td), "r11_nomf", refs=["x.md"], router_links=["x.md"], content=two)
        checks.append(("R11 assert 没有各自的 must_fail_on 被抓到",
                       any(x.startswith("R11") for x in check(nomf)[0])))

        twok = ('{"unit": "u", "cases": [{"id": "c", "prompt": "p", "assert": ['
                '{"type": "contains_all", "patterns": ["a"], "must_fail_on": "x"}, '
                '{"type": "contains_all", "patterns": ["b"], "must_fail_on": "y"}]}]}')
        mfok = _mkrepo(Path(td), "r11_ok", refs=["x.md"], router_links=["x.md"], content=twok)
        checks.append(("R11 每条 assert 各带 must_fail_on 不误报",
                       not any(x.startswith("R11") for x in check(mfok)[0])))

        # ── R12 ──────────────────────────────────────────────────────
        nopkg = _mkrepo(Path(td), "r12_missing", refs=["x.md"], router_links=["x.md"],
                        package=None)
        checks.append(("R12 产品线仓缺 PACKAGE.txt 被抓到",
                       any(x.startswith("R12") for x in check(nopkg)[0])))

        # 方向 A：白名单里写了仓里没有的路径
        ghost = _mkrepo(Path(td), "r12_ghost", refs=["x.md"], router_links=["x.md"],
                        package="SKILL.md\nreferences/\nscripts/gone.py\n")
        checks.append(("R12 方向A：幽灵条目（白名单里的路径不存在）被抓到",
                       any("幽灵" in x for x in check(ghost)[0])))

        # 方向 B：仓里被引用到的文件没写进白名单。**只做 A 抓不到这个**
        omit = _mkrepo(Path(td), "r12_omit", refs=["x.md"], router_links=["x.md"],
                       package="SKILL.md\n")
        checks.append(("R12 方向B：被引用到却不在白名单被抓到",
                       any(x.startswith("R12") and "references/x.md" in x
                           for x in check(omit)[0])))

        clean = _mkrepo(Path(td), "r12_clean", refs=["x.md"], router_links=["x.md"],
                        package="SKILL.md\nreferences/x.md\n")
        checks.append(("R12 白名单两个方向都自洽时不误报",
                       not any(x.startswith("R12") for x in check(clean)[0])))

        # 冲榜线仓：README 开头写死「不上产品线」⇒ 不要 PACKAGE.txt
        off = _mkrepo(Path(td), "r12_offline", refs=["x.md"], router_links=["x.md"],
                      package=None, readme="# leaderboard-skill\n\n**不上产品线。**\n")
        checks.append(("R12 冲榜线仓（README 开头有标记）不要 PACKAGE.txt",
                       not any(x.startswith("R12") for x in check(off)[0])))

        # ⚠️ 方向：忘了把标记写在开头的冲榜线仓，会被当成产品线仓报红。
        # 这是**故意**的 —— 反过来（产品线仓被当成冲榜线仓）会让 R12 整条静默失效。
        late = _mkrepo(Path(td), "r12_offline_late", refs=["x.md"], router_links=["x.md"],
                       package=None,
                       readme="# s\n\n" + "\n" * 8 + "顺带一提，它不上产品线。\n")
        checks.append(("R12 标记没写在开头 ⇒ 倒向产品线仓（宁可误伤冲榜线）",
                       any(x.startswith("R12") for x in check(late)[0])))

        # ── 豁免机制 ─────────────────────────────────────────────────
        LEGACY_EXEMPT["r12_missing"] = {"rules": ["R12"], "why": "selftest"}
        checks.append(("豁免能压住红",
                       not any(x.startswith("R12") for x in check(nopkg)[0])))

        # 反向断言：豁免了一个其实已经合规的仓 ⇒ 必须报 BAD_EXCEPTION 要求删条目
        LEGACY_EXEMPT["r12_clean"] = {"rules": ["R12"], "why": "selftest：这个仓其实已经合规"}
        stale = [x for x in check(clean)[0] if x.startswith("BAD_EXCEPTION")]
        checks.append(("豁免反向断言：已合规的仓仍在名单里被点名",
                       any("r12_clean" in x and "R12" in x for x in stale)))
        del LEGACY_EXEMPT["r12_missing"], LEGACY_EXEMPT["r12_clean"]

        # V1：vendored 副本漂了要被抓到
        vend = Path(td) / "vend"
        (vend / "skills" / "s1" / "scripts").mkdir(parents=True)
        (vend / "skills" / "s2" / "scripts").mkdir(parents=True)
        me = Path(__file__).resolve()
        (vend / "skills" / "s1" / "scripts" / me.name).write_bytes(me.read_bytes())
        (vend / "skills" / "s2" / "scripts" / me.name).write_bytes(me.read_bytes() + b"# drift\n")
        vb = check_vendored(vend, verbose=False)
        checks.append(("V1 vendored 副本漂移被抓到",
                       len(vb) == 1 and "s2" in vb[0]))

        # V1 的另一半：一份都没有时不许报成绿
        empty = Path(td) / "vend_empty"
        empty.mkdir()
        checks.append(("V1 没有副本时不误报为不一致", check_vendored(empty, verbose=False) == []))

    bad = 0
    for label, ok_ in checks:
        print(f"  {'✅' if ok_ else '🔴'} {label:<30} {'正对照命中' if ok_ else '**没有命中——这条判定是坏的**'}")
        bad += 0 if ok_ else 1
    print(f"\n正对照 {len(checks) - bad}/{len(checks)} 通过")
    return 1 if bad else 0


def check_vendored(root: Path, verbose: bool = True) -> list[str]:
    """各 skill 仓里 vendored 的本文件副本，必须与本仓这一份逐字节相同。

    参数集中到 RULES 之后，「改哪一份副本」就成了唯一的漂移面。
    今天 8 份副本字节相同，但**没有任何东西在看**——所以补这一条。

    ⚠️ 它只看得见**已 checkout 的 submodule**。submodule 没初始化时
    副本数是 0，那不叫「全都一致」——所以下面会把看到几份说出来，
    别让「0 份不一致」被读成绿灯。
    """
    me = Path(__file__).resolve()
    mine = me.read_bytes()
    seen, bad = [], []
    for cp in sorted(root.glob("skills/*/scripts/check_skill_layout.py")):
        if cp.resolve() == me:
            continue
        seen.append(cp)
        if cp.read_bytes() != mine:
            bad.append(f"V1 {cp.relative_to(root)} 与本仓的 scripts/{me.name} 不一致 —— "
                       f"闸的副本漂了，两边的规则参数可能已经不是一套")
    if verbose:
        print(f"vendored 副本：看到 {len(seen)} 份"
              + ("（submodule 没初始化？）" if not seen else ""))
        for b in bad:
            print(f"  ❌ {b}")
        if seen and not bad:
            print("  ✅ 全部与本仓一致")
    return bad


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("roots", nargs="*", type=Path, default=None)
    ap.add_argument("--strict", action="store_true", help="warn 也算失败")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--check-vendored", action="store_true",
                    help="断言各 skill 仓里的本文件副本与本仓一致")
    args = ap.parse_args()
    if args.selftest:
        return run_selftest()
    roots = args.roots or [Path(__file__).resolve().parents[1]]
    if args.check_vendored:
        return 1 if check_vendored(roots[0].resolve()) else 0
    return max(report(r.resolve(), args.strict) for r in roots)


if __name__ == "__main__":
    sys.exit(main())
