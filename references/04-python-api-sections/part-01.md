# `ncu_report` Python API

Use the Python module, not CLI output, for anything beyond a quick look. The API lets you extract, aggregate, compare, and archive metric data cleanly.

Module path (adjust for your CUDA version):
```bash
export PYTHONPATH=$PYTHONPATH:/usr/local/cuda-13.2/nsight-compute-2026.1.0/extras/python
python3 -c "import ncu_report; print('OK')"
```

---

## Basic loading

```python
import sys
sys.path.insert(0, "/usr/local/cuda-13.2/nsight-compute-2026.1.0/extras/python")
import ncu_report

report = ncu_report.load_report("path/to/full_<tag>.ncu-rep")

# A report can contain multiple "ranges" (each range = one profiled region).
# In practice, with -c 1 you have exactly one range containing one action (= one kernel launch).
rng = report.range_by_idx(0)
action = rng.action_by_idx(0)

print(f"Kernel demangled name: {action.name()}")       # void my_kernel<8, 256>(...)
print(f"Total metrics collected: {len(action.metric_names())}")
```

---

## Reading a single metric

```python
def safe(action, name, default=None):
    """Return metric value, or default if missing / errors."""
    try:
        return action[name].value()
    except Exception:
        return default

sm_util = safe(action, "sm__throughput.avg.pct_of_peak_sustained_elapsed")
dram_read_bw = safe(action, "dram__bytes_read.sum.per_second")
duration_ns = safe(action, "gpu__time_duration.sum")     # usually in ns

print(f"SM throughput: {sm_util}%")
print(f"DRAM read BW:  {dram_read_bw/1e9:.2f} GB/s")
print(f"Duration:      {duration_ns/1e3:.2f} µs")
```

**Always wrap in a try/except or helper.** Metric names differ between GPU generations — see [`08-b200-metric-names.md`](../08-b200-metric-names.md). A metric that exists on A100 may return `KeyError` on B200.

---

## Enumerating available metrics

```python
# Full list — 2000+ metrics for --set full
all_names = action.metric_names()

# Filter by pattern
for name in sorted(all_names):
    if "warps_issue_stalled" in name and "ratio" in name:
        print(name, "=", safe(action, name))
```

This is how you discover the *actual* metric names available on your GPU instead of guessing.

---

## Per-instance (per-SM, per-PC, per-time-sample) values

Many metrics have multiple values per collection. `value()` returns the aggregate (sum / avg depending on `rollup_operation`), but you can also enumerate the individual samples.

```python
m = action["pmsampling:smsp__warps_issue_stalled_long_scoreboard.avg"]
n = m.num_instances()              # e.g., 1660 for a PM-sampled metric
print(f"instances: {n}")

vals = []
for i in range(n):
    try:
        v = m.as_double(i)
    except Exception:
        try:
            v = float(m.as_uint64(i))
        except Exception:
            v = None
    vals.append(v)
```

For PM sampling this is the timeline — index `i` is a time-ordered sample. Bucket these for an ASCII plot (see `scripts/plot_timeline.py`).

---
