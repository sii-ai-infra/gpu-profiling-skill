## Recipe 5: Targeted metrics only (fast)

If you already know which metrics you want (e.g., you're re-running after a code change and only want to check if the fix worked), collect just those:

```bash
ncu --metrics \
    sm__throughput.avg.pct_of_peak_sustained_elapsed,\
    sm__warps_active.avg.pct_of_peak_sustained_active,\
    dram__bytes_read.sum.pct_of_peak_sustained_elapsed,\
    l1tex__t_sector_hit_rate.pct,\
    gpu__time_duration.sum,\
    l1tex__t_sectors_pipe_lsu_mem_global_op_ld.sum,\
    l1tex__t_requests_pipe_lsu_mem_global_op_ld.sum \
  -k "regex:KERNEL_REGEX" -c 1 \
  ./harness [args]
```

Takes one or two replay passes. Prints a table directly to stdout. No `-o` output file.

---

## Recipe 6: A/B comparison (before vs after optimization)

```bash
# Before
ncu --set full -k "regex:my_kernel" -c 1 \
    -o $PROFILE_RUN_DIR/reports/v1 ./harness_v1 [args]

# After
ncu --set full -k "regex:my_kernel" -c 1 \
    -o $PROFILE_RUN_DIR/reports/v2 ./harness_v2 [args]
```

Then use `analyze_reports.py` with multiple tags to produce a side-by-side comparison, or manually:

```python
import ncu_report
r1 = ncu_report.load_report("$PROFILE_RUN_DIR/reports/v1.ncu-rep")
r2 = ncu_report.load_report("$PROFILE_RUN_DIR/reports/v2.ncu-rep")
a1 = r1.range_by_idx(0).action_by_idx(0)
a2 = r2.range_by_idx(0).action_by_idx(0)
t1 = a1["gpu__time_duration.sum"].value()
t2 = a2["gpu__time_duration.sum"].value()
print(f"Speedup: {t1/t2:.2f}x")
```

---

## What each `--set` contains

```bash
ncu --list-sets           # list all sets
ncu --list-sections       # list all sections
```

Rough mapping (B200, ncu 2026.1):

| Set | Sections included | Replay passes | Use when |
|---|---|---|---|
| `basic` (default) | SOL, LaunchStats, Occupancy | ~3-5 | Smoke test — is ncu working at all? |
| `detailed` | basic + Scheduler, WarpState, ComputeWorkload, MemoryWorkload, InstructionStats | ~15 | Middle-ground, often too limited |
| `full` | everything except Source | ~45 | First-pass profile. Always start here. |
| `source` | full + SourceCounters (per-PC data) | ~50 | Per-line stall attribution. Needs `-lineinfo`. |
| `pmsampling` | only PM sampling (time series) | ~3 | Already covered by `--section PmSampling` on top of full |

---

## Common section additions

```bash
# PM sampling (not in any --set)
--section PmSampling
--section PmSampling_WarpStates

# Source counters (not in --set full, is in --set source)
--section SourceCounters

# NVLink bandwidth (if profiling multi-GPU)
--section Nvlink_Topology
--section Nvlink_Tables
```

---

## Profiling multiple kernel launches

If the kernel is called multiple times and you want different iterations:

```bash
# Skip the first 5 invocations, then profile 3 consecutive launches
ncu -k "regex:my_kernel" -s 5 -c 3 -o report ./harness
```

`-s N` skips the first N matches. `-c N` limits to N matches. Useful for ignoring warmup or focusing on a steady-state iteration.

---
