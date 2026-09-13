## Comparing two reports programmatically

```python
def compare(rep1_path, rep2_path, metrics):
    r1 = ncu_report.load_report(rep1_path)
    r2 = ncu_report.load_report(rep2_path)
    a1 = r1.range_by_idx(0).action_by_idx(0)
    a2 = r2.range_by_idx(0).action_by_idx(0)
    print(f"{'Metric':<75} {'v1':>15} {'v2':>15} {'change':>10}")
    for m in metrics:
        v1 = safe(a1, m)
        v2 = safe(a2, m)
        if isinstance(v1, (int, float)) and isinstance(v2, (int, float)) and v1:
            chg = (v2 - v1) / v1 * 100
            print(f"{m:<75} {v1:>15.4g} {v2:>15.4g} {chg:>+9.1f}%")
        else:
            print(f"{m:<75} {str(v1):>15} {str(v2):>15}")

compare("v1.ncu-rep", "v2.ncu-rep", [
    "gpu__time_duration.sum",
    "sm__throughput.avg.pct_of_peak_sustained_elapsed",
    "dram__bytes_read.sum.pct_of_peak_sustained_elapsed",
    "smsp__average_warps_issue_stalled_long_scoreboard_per_issue_active.ratio",
    "l1tex__t_sector_hit_rate.pct",
])
```

---

## Extracting NCU's rule suggestions

The rule engine results — the "OPT Est. Speedup: X%" bullets — are accessible as structured data:

```python
for result in action.rule_results_as_dicts():
    severity = result.get("type", "?")      # "OPT" / "INF" / "WRN"
    rule_name = result.get("rule_name", "?")
    message = result.get("message_for_display", "?")
    est_speedup = result.get("estimated_speedup_pct", None)
    print(f"[{severity}] {rule_name}: {est_speedup}%")
    print(f"    {message[:200]}")
```

Sort by `estimated_speedup_pct` descending to get the highest-impact suggestions first.

---

## Saving everything for later

Always archive the full metric dump:

```python
import json
from pathlib import Path

def dump_all(action, outpath):
    rows = []
    for name in sorted(action.metric_names()):
        try:
            m = action[name]
            rows.append({
                "name": name,
                "value": m.value(),
                "unit": m.unit() if hasattr(m, "unit") else "",
            })
        except Exception as e:
            rows.append({"name": name, "error": str(e)})
    Path(outpath).write_text(json.dumps(rows, indent=1, default=str))

dump_all(action, "analysis/metrics_all_<tag>.json")
```

This makes future re-analysis cheap: the raw data lives as JSON, you don't need to reopen the `.ncu-rep`.

---

## Gotchas

- **`KeyError` on a metric that "should" exist**: the metric has a different name on this GPU. Check [`08-b200-metric-names.md`](../08-b200-metric-names.md) or enumerate with `action.metric_names()`.
- **`num_instances() == 0`** but you expected per-instance data: the metric wasn't collected in instanced mode, or the section that produces it wasn't requested. Re-run ncu with the right `--section`.
- **`has_correlation_ids() == False`** on a source-level metric: `-lineinfo` wasn't on the compile line. Rebuild.
- **`source_info(pc)` returns None**: same as above — rebuild with `-lineinfo`.
- **Metric value is a string** like `"PolicySpread"`: it's an enum, use `m.as_string()` or `m.value()` and expect a string.
