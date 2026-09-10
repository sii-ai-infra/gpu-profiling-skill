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

  --check-vendored  各 skill 仓里 vendored 的本文件副本必须与本仓一致 ——
                    参数外置之后，「改了哪份副本」才是真正的漂移面

⚠️ 它判的是**形态**，判不了内容对不对。内容要人读，或者交给
score_skill_routing.py / score_knowledge_reachability.py。
"""
from __future__ import annotations

import argparse
import re
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
    ],
    "banned_dirs": {"reference": "references", "helpers": "scripts"},
    "router_max_lines": 300,      # R7 —— E7c 的形态判据
    "reference_max_lines": 200,   # R7
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
ROOT_ALLOWED = set(RULES["root_allowed"])
BANNED_DIRS = dict(RULES["banned_dirs"])
ROUTER_MAX = int(RULES["router_max_lines"])
REFERENCE_MAX = int(RULES["reference_max_lines"])


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
