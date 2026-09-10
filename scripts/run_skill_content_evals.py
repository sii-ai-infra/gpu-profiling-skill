#!/usr/bin/env python3
"""`evals/content.json` 的 runner —— 两半，只有一半在这里。

    python3 scripts/run_skill_content_evals.py --selfcheck [<repo>...]
    python3 scripts/run_skill_content_evals.py --print-prompts [<repo>...]
    python3 scripts/run_skill_content_evals.py --score <results.json> [<repo>...]
    python3 scripts/run_skill_content_evals.py --selftest

## 为什么只有一半在这里

「加载之后答得对不对」这件事需要模型，**而且必须走产品真正的 skill 加载路径**。
把 `SKILL.md` 贴进 prompt 再问模型，测的是「模型会不会复述贴进去的文本」——
**那是另一个保证**。混淆这两者正是「先证明测对了格」那一条。

所以照 `score_skill_routing.py` 的形状办：**本脚本从不调模型**。
`--print-prompts` 出题，人/会话在真加载路径上跑，`--score` 给答案打分。

## `--selfcheck`：不需要模型的那一半，而它比看起来重要

R11（`check_skill_layout.py`）判的是**形状**：`must_fail_on` 这个字段在不在。
它判不了那条断言**能不能用**。三个洞：

  L1 语法    pattern 编译得过吗
             ——「(?s) 写在 alternation 中间」会让 Python 抛
             `global flags not at the start of the expression`。
             写这批判据时一次就有 **17 条**会在真 runner 上炸，
             而 R11 全绿。**形状对、跑不起来。**
  L2 会拒     `must_fail_on` 真的被它自己那条断言拒掉吗
             —— 一个不会拒的正对照，就不是正对照。
  L3 会收     `should_pass` 真的被它接受吗
             —— ⚠️ **这一条是 L2 补不了的**：`must_fail_on` 只证明这条断言
             **拒绝某个东西**，证明不了它**接受任何东西**。一条打错字的
             pattern 拒绝一切（包括正确答案），而 L2 照样通过。
             **那是一个因为错误的理由而通过的正对照。**

⚠️ L3 需要每个 case 带一份 `should_pass`（一段合理的正确回答）。
写这批判据的两条 lane 都写过这种样本、都靠它抓到了过紧的 pattern
（字符距离窗口卡死正常语序），**但样本写在临时目录里没进仓** ——
于是「这些断言是可满足的」这个证据今天不可复现。**证据不进仓等于没有。**
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPOS = ["skills/ascendc-skill", "skills/cuda-skill",
                 "skills/gpu-profiling-skill", "skills/npu-profiling-skill",
                 "skills/triton-ascend-debug-skill"]


def parse_answer(text: str) -> dict:
    """Parse the entire answer, never a quoted answer embedded in prose.

    Duplicate keys, NaN/Infinity and non-object roots are ambiguous answers.
    A single JSON code fence is accepted as a presentation choice.
    """
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate key: {key}")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError(f"non-JSON number: {value}")

    text = text.strip()
    if text.startswith("```json\n") and text.endswith("\n```"):
        text = text[8:-4]
    result = json.loads(text, object_pairs_hook=pairs, parse_constant=invalid_constant)
    if not isinstance(result, dict):
        raise ValueError("answer must be one JSON object")
    return result


def samples(value) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [value]
    if isinstance(value, list) and value and all(isinstance(x, str) and x.strip() for x in value):
        return value
    return []


# ── 断言语义（写死在这里，因为 json 里的 assert_types 只是注释）────────
def compile_patterns(a: dict) -> tuple[list, str | None]:
    """→ (matchers, 语法错)。matchers 是 (描述, 判定函数) 的列表。"""
    t = a.get("type")
    if t == "json_fields":
        fields = a.get("fields")
        if not isinstance(fields, dict) or not fields:
            return [], "json_fields requires nonempty fields"
        def matches(text):
            try:
                answer = parse_answer(text)
            except (ValueError, TypeError):
                return False
            return all(k in answer and type(answer[k]) is type(v) and answer[k] == v
                       for k, v in fields.items())
        return [(json.dumps(fields, ensure_ascii=False), matches)], None
    pats = a.get("patterns") or ([a["pattern"]] if a.get("pattern") else [])
    if not pats:
        return [], "没有 patterns"
    if t == "contains_all":
        return [(p, (lambda s, p=p: p in s)) for p in pats], None
    if t == "regex_all":
        out = []
        for p in pats:
            try:
                rx = re.compile(p)
            except re.error as exc:
                return [], f"正则编译不过：{p[:48]}… → {exc}"
            out.append((p, lambda s, rx=rx: bool(rx.search(s))))
        return out, None
    return [], f"不认识的 assert type：{t!r}"


def assert_holds(a: dict, text: str) -> tuple[bool, str]:
    ms, err = compile_patterns(a)
    if err:
        return False, err
    for desc, fn in ms:
        if not fn(text):
            return False, f"缺 `{desc[:56]}`"
    return True, ""


# ── 收集 ───────────────────────────────────────────────────────────
def collect(repos: list[str]) -> list[tuple[Path, dict]]:
    out = []
    for r in repos:
        base = ROOT / r
        if not base.is_dir():
            out.append((base, {"_parse_error": "repository directory does not exist"}))
            continue
        paths = sorted(base.glob("skills/*/evals/content.json")) + sorted(base.glob("evals/content.json"))
        if not paths:
            out.append((base, {"_parse_error": "no content.json found"}))
        for p in paths:
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("root must be an object")
                out.append((p, data))
            except Exception as exc:                     # noqa: BLE001
                out.append((p, {"_parse_error": str(exc)}))
    return out


def _show(path: Path) -> str:
    """显示用的路径。⚠️ 不许直接 relative_to(ROOT)：`--selfcheck` 收的是外部
    checkout（as-skill 还没挂成 submodule 时就是这样），那会抛 ValueError，
    而炸掉的是**打印**，不是判据 —— 用户会以为自己路径写错了。"""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def schema_errors(files) -> list[str]:
    errors, identities = [], set()
    if not files:
        return ["no evaluation files"]
    for path, data in files:
        label = _show(path)
        if "_parse_error" in data:
            errors.append(f"{label}: {data['_parse_error']}")
            continue
        unit, cases = data.get("unit"), data.get("cases")
        if not isinstance(unit, str) or not unit.strip():
            errors.append(f"{label}: missing unit")
        if not isinstance(cases, list) or not cases:
            errors.append(f"{label}: no cases")
            continue
        for c in cases:
            if not isinstance(c, dict):
                errors.append(f"{label}: case must be an object")
                continue
            cid = c.get("id")
            identity = (str(unit), str(cid))
            if not isinstance(cid, str) or not cid.strip() or identity in identities:
                errors.append(f"{label}: missing or duplicate case id {cid!r}")
            identities.add(identity)
            if not isinstance(c.get("prompt"), str) or not c["prompt"].strip():
                errors.append(f"{label}:{cid}: missing prompt")
            assertions = c.get("assert")
            if not isinstance(assertions, list) or not assertions:
                errors.append(f"{label}:{cid}: no assertions")
                continue
            for a in assertions:
                if not isinstance(a, dict):
                    errors.append(f"{label}:{cid}: assertion must be an object")
                elif not samples(a.get("must_fail_on") or (c.get("must_fail_on") if len(assertions) == 1 else None)):
                    errors.append(f"{label}:{cid}: missing negative sample")
    return errors


def selfcheck(repos: list[str]) -> int:
    files = collect(repos)
    invalid = schema_errors(files)
    if invalid:
        print("\n".join(f"L0 {e}" for e in invalid))
        return 1
    if not files:
        # 和 V1 同形：没有样本时不许报成绿。
        print("🔴 一份 content.json 都没读到 —— 这不是「全都通过了」，是没看成")
        return 1
    err, n_case, n_assert, no_pass = [], 0, 0, []
    for path, data in files:
        rel = _show(path)
        if "_parse_error" in data:
            err.append(f"L0 {rel} 解析不了：{data['_parse_error']}")
            continue
        for c in data.get("cases", []):
            n_case += 1
            cid = c.get("id") or "?"
            asserts = c.get("assert") or []
            case_mf = samples(c.get("must_fail_on"))
            sp = samples(c.get("should_pass"))
            if not sp:
                no_pass.append(f"{rel}:{cid}")
            for j, a in enumerate(asserts, 1):
                n_assert += 1
                ms, syn = compile_patterns(a)
                if syn:
                    err.append(f"L1 {rel}:{cid} assert{j} {syn}")
                    continue
                mf = samples(a.get("must_fail_on")) or (case_mf if len(asserts) == 1 else [])
                for negative in mf:
                    held, _ = assert_holds(a, negative)
                    if held:
                        err.append(f"L2 {rel}:{cid} assert{j} 的 must_fail_on **没有被它拒掉**"
                                   " —— 一个不会拒的正对照，就不是正对照")
                for positive in sp:
                    held, why = assert_holds(a, positive)
                    if not held:
                        err.append(f"L3 {rel}:{cid} assert{j} 把 should_pass 也拒了（{why}）"
                                   " —— 拒绝一切的断言，must_fail_on 照样会绿")
    print(f"\ncontent.json 自检 · {len(files)} 份 · {n_case} case · {n_assert} assert\n")
    for x in err:
        print(f"  🔴 {x}")
    if no_pass:
        # ⚠️ 这一条必须报红，不能只警告。只警告的话，把 should_pass 删掉就能让
        #    这个 case 的 L3 消失、闸照样绿 —— 那正是「一条拒绝一切的 pattern
        #    靠 must_fail_on 蒙混过关」那个洞，只不过换了个入口。
        #    豁免不设开关：今天 16/16 都有，写一份豁免名单等于给它留后门。
        print(f"  🔴 {len(no_pass)} 个 case 没有 should_pass —— L3 对它们是瞎的："
              f"{', '.join(no_pass[:4])}{' …' if len(no_pass) > 4 else ''}")
    if not err and not no_pass:
        print("  ✅ L1 语法 · L2 会拒 · L3 会收，全部通过")
    return 1 if (err or no_pass) else 0


def print_prompts(repos: list[str]) -> int:
    """出题。⚠️ 必须在**产品真正的加载路径**上作答，不是把 SKILL.md 贴进 prompt。"""
    files = collect(repos)
    invalid = schema_errors(files)
    if invalid:
        print("\n".join(invalid), file=sys.stderr)
        return 1
    items = []
    for path, data in files:
        for c in data.get("cases", []):
            items.append({"unit": data.get("unit"), "id": c.get("id"), "prompt": c.get("prompt")})
    print(json.dumps({
        "_how": "对每条：在产品的真实加载路径下（让 loader 按三根轴选中该 skill），"
                "把 prompt 交给模型，把回答原样填进 results[unit][id]。"
                "⚠️ 不要把 SKILL.md 贴进 prompt —— 那测的是复述，不是加载。",
        "items": items,
    }, ensure_ascii=False, indent=2))
    return 0


def score(results_path: str, repos: list[str]) -> int:
    files = collect(repos)
    invalid = schema_errors(files)
    if invalid:
        print("\n".join(invalid))
        return 1
    res = json.loads(Path(results_path).read_text(encoding="utf-8"))
    res = res.get("results", res)
    rows, missing = [], []
    for path, data in files:
        unit = data.get("unit")
        for c in data.get("cases", []):
            ans = (res.get(unit) or {}).get(c.get("id"))
            if not isinstance(ans, str):
                missing.append(f"{unit}:{c.get('id')}")
                continue
            bad = [why for a in (c.get("assert") or [])
                   for held, why in [assert_holds(a, ans)] if not held]
            rows.append((unit, c.get("id"), not bad, bad))
    ok = sum(1 for *_, p, _ in rows if p)
    print(f"\ncontent eval 打分 · {ok}/{len(rows)} 通过\n")
    print("仅自动判定声明的字段/断言；解释的事实、推理及与字段的一致性须另行人工评审。")
    for unit, cid, passed, bad in rows:
        print(f"  {'✅' if passed else '🔴'} {unit}:{cid}")
        for b in bad[:3]:
            print(f"        ↳ {b}")
    if missing:
        print(f"\n  ⚠️ {len(missing)} 条没有答案 —— **不许当成通过**：{', '.join(missing[:5])}")
    return 1 if (len(rows) - ok or missing) else 0


# ── 正对照 ────────────────────────────────────────────────────────
def selftest() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="cjson-"))
    d = tmp / "skills" / "x" / "evals"
    d.mkdir(parents=True)

    def write(cases):
        (d / "content.json").write_text(
            json.dumps({"unit": "x", "cases": cases}, ensure_ascii=False), encoding="utf-8")

    import contextlib, io
    def run():
        with contextlib.redirect_stdout(io.StringIO()) as b:
            rc = selfcheck([str(tmp)])          # 绝对路径 —— _show 之后这条本来就该能跑
        return rc, b.getvalue()

    global ROOT                                          # noqa: PLW0603
    saved, ROOT = ROOT, tmp
    good = {"id": "g", "prompt": "p",
            "assert": [{"type": "contains_all", "patterns": ["省 1 µs"],
                        "must_fail_on": "合并不省时间"}],
            "should_pass": "合并每个 kernel 省 1 µs 的地板"}
    checks = []
    write([good]); rc, _ = run()
    checks.append(("① 三层都过时报绿", rc == 0))

    bad_syntax = json.loads(json.dumps(good))
    bad_syntax["assert"][0] = {"type": "regex_all", "patterns": [r"a|(?s)b"],
                               "must_fail_on": "z"}
    write([bad_syntax]); rc, out = run()
    checks.append(("② (?s) 在 alternation 中间 ⇒ L1 报语法（真 runner 会抛）",
                   bool(rc) and "🔴 L1" in out))

    no_reject = json.loads(json.dumps(good))
    no_reject["assert"][0]["must_fail_on"] = "合并每个 kernel 省 1 µs"   # 反例其实过得了
    write([no_reject]); rc, out = run()
    checks.append(("③ must_fail_on 拒不掉 ⇒ L2 报「不是正对照」", bool(rc) and "🔴 L2" in out))

    too_tight = json.loads(json.dumps(good))
    too_tight["assert"][0]["patterns"] = ["省 1 µs 的地板并且不引入同步"]   # 正例也过不了
    write([too_tight]); rc, out = run()
    checks.append(("④ 断言把 should_pass 也拒了 ⇒ L3 报红", bool(rc) and "🔴 L3" in out))
    # ↓ 这一条是 L3 存在的全部理由
    del too_tight["should_pass"]
    write([too_tight]); rc, out = run()
    # ⚠️ 判据要钉「🔴 L3」不是「L3」——「L3 对它们是瞎的」那句话本身就含 L3，
    #    拿子串判会让这条正对照假阴。我第一版就是这么写的，它报了一次假失败。
    # 这一条现在同时证两件事：
    #   (a) 同一条「拒绝一切」的断言，L1/L2 一个字都说不出来 —— L2 补不了 L3；
    #   (b) 所以「没有 should_pass」本身必须报红，否则删掉它就是一条逃逸路径。
    checks.append(("⑤ 拒绝一切的断言，去掉 should_pass 后 L1/L2 全哑（反证：L2 补不了 L3）",
                   "🔴 L1" not in out and "🔴 L2" not in out and "🔴 L3" not in out))
    checks.append(("⑤' 而它照样报红 —— 因为「没有 should_pass」自己就是红的，不是警告",
                   bool(rc) and "没有 should_pass" in out))

    write([]); rc, out = run()
    checks.append(("⑥ 一个 case 都没有时不报假绿", bool(rc) and "no cases" in out))
    ROOT = saved
    import shutil; shutil.rmtree(tmp, ignore_errors=True)

    print()
    n = sum(1 for _, p in checks if p)
    for name, p in checks:
        print(f"  {'✅' if p else '❌'} {name}")
    print(f"\ncontent runner 正对照 {n}/{len(checks)}")
    return 0 if n == len(checks) else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("repos", nargs="*", default=None)
    ap.add_argument("--selfcheck", action="store_true")
    ap.add_argument("--print-prompts", action="store_true")
    ap.add_argument("--score")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    repos = a.repos or DEFAULT_REPOS
    if a.selftest:
        return selftest()
    if a.print_prompts:
        return print_prompts(repos)
    if a.score:
        return score(a.score, repos)
    return selfcheck(repos)


if __name__ == "__main__":
    sys.exit(main())
