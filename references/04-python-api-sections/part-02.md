## Per-PC → per-source-line mapping

The source-level report (collected with `--set source --section SourceCounters`) has per-PC samples. Map them to source lines via `action.source_info(pc)`:

```python
def per_pc_stalls(action, stall_metric):
    m = action[stall_metric]
    n = m.num_instances()
    if n == 0 or not m.has_correlation_ids():
        return []
    cor = m.correlation_ids()
    out = []
    for i in range(n):
        pc = cor.as_uint64(i)
        val = m.as_uint64(i)
        si = action.source_info(pc)
        if si is None:
            file, line = "?", 0
        else:
            file, line = si.file_name(), si.line()
        out.append((file, line, val))
    return out

stalls = per_pc_stalls(action, "smsp__pcsamp_warps_issue_stalled_long_scoreboard")
```

Aggregate by `(file, line)` and sort by total to get hottest stall lines. See `scripts/extract_stall_hotspots.py` for a complete implementation.

---

## Discovering Value Kind

Each metric has a value kind (uint64, double, float, string). Use `m.kind()` to check before calling the right accessor:

```python
def metric_val(m, i=None):
    k = m.kind()
    VK = m.ValueKind_UINT64, m.ValueKind_DOUBLE, m.ValueKind_FLOAT, m.ValueKind_STRING
    if i is None:
        return m.value()          # aggregate
    if k == m.ValueKind_UINT64:
        return m.as_uint64(i)
    if k in (m.ValueKind_DOUBLE, m.ValueKind_FLOAT):
        return m.as_double(i)
    if k == m.ValueKind_STRING:
        return m.as_string(i)
    # Try generic conversions as fallbacks
    try:
        return m.as_uint64(i)
    except Exception:
        return m.as_double(i)
```

---

## Useful `action` / `metric` methods

```python
# Action (= one kernel launch's profile data)
action.name()                   # demangled kernel name
action.metric_names()           # list of all metrics
action.metric_by_name(name)     # same as action[name]
action.source_info(pc)          # IPC → SourceInfo (file, line) — only if -lineinfo was used
action.sass_by_pc()             # dict {pc → SASS instruction string}
action.ptx_by_pc()              # dict {pc → PTX} — only if --keep was used
action.rule_results_as_dicts()  # NCU rule-engine output as list of dicts

# Metric
m.value()                       # aggregate value
m.unit()                        # string, e.g. "%" or "cycle"
m.kind()                        # value kind (UINT64 / DOUBLE / ...)
m.rollup_operation()            # AVG / MAX / MIN / SUM / NONE
m.num_instances()               # per-instance count (0 if aggregate only)
m.has_correlation_ids()         # True for per-PC metrics
m.correlation_ids()             # parallel array for num_instances
m.description()                 # human-readable metric description
```

---

## Exploring when you don't know the right metric name

```python
# Print all metric names sorted
for n in sorted(action.metric_names()):
    print(n)

# Print metrics matching a pattern with their current value
import re
pat = re.compile(r"dram__bytes.*sum")
for n in sorted(action.metric_names()):
    if pat.search(n):
        try:
            v = action[n].value()
            print(f"{n} = {v}  (unit: {action[n].unit()})")
        except Exception as e:
            print(f"{n} = ERROR {e}")
```

This is how I built [`08-b200-metric-names.md`](../08-b200-metric-names.md) — by enumerating everything available on sm_100.

---
