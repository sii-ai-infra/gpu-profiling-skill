# Six Analysis Dimensions

Every kernel profile report is ambiguous until you look at it through specific lenses. These six dimensions are the ones that consistently matter. Walk through all six; don't stop at the first finding.

For each dimension this doc describes:

- **What you're answering**
- **Which metrics to read** (B200 / sm_100 names)
- **How to read them** (what's "normal", what's "bad")
- **Which `scripts/` to run**

---

## Dimension 1 — SM occupancy & launch geometry

**What:** is the grid large enough to fill the GPU? Is occupancy being limited by registers, shared memory, or block-size constraints?

**Metrics:**
```
launch__grid_size
launch__block_size
launch__grid_dim_x / _y / _z
launch__waves_per_multiprocessor
launch__registers_per_thread
launch__shared_mem_per_block
launch__occupancy_limit_blocks
launch__occupancy_limit_registers
launch__occupancy_limit_shared_mem
launch__occupancy_limit_warps
device__attribute_multiprocessor_count         (148 on B200)
sm__maximum_warps_per_active_cycle_pct          (theoretical occupancy %)
sm__warps_active.avg.pct_of_peak_sustained_active  (achieved occupancy %)
```

**Reading:**

- **Waves / SM < 1**: grid is too small to fill the chip. On B200 with 148 SMs, if `launch__grid_size < 148 × blocks_per_SM`, some SMs sit idle the entire time. `Est. Speedup` from NCU often hits 50-90% here.
- **Waves / SM in [1, 2)**: you have a tail wave (partial last wave). Tail effect magnitude is roughly `(last_wave_blocks / wave_size) × (block_exec_time / total_kernel_time)`.
- **Waves / SM > 4**: grid is plenty big, scheduling averages out.
- **Theoretical occupancy 100% but achieved << 100%**: stalls are the bottleneck, not launch config. Move to Dimension 3.
- **Theoretical occupancy < 100% and `launch__occupancy_limit_registers` is the tightest**: reduce register usage or add `__launch_bounds__`.
- **`launch__occupancy_limit_shared_mem`** the tightest: shared mem / block is too large, reduce tile size.

**Derived: wave math**

```python
blocks_per_sm = min(occ_limit_blocks, occ_limit_registers, occ_limit_shared_mem, occ_limit_warps)
wave_size = blocks_per_sm * num_sms
num_waves = (total_blocks + wave_size - 1) // wave_size
last_wave_blocks = total_blocks - (num_waves - 1) * wave_size
last_wave_utilization_pct = last_wave_blocks / wave_size * 100
```

**Helper:** `analyze_reports.py` prints all the key launch metrics under "Launch geometry" in the output txt.

---

## Dimension 2 — Thread-block balance (tail effect)

**What:** are blocks finishing at roughly the same time, or do a few outliers drag out the kernel?

**Metrics:**

There is no single "imbalance" metric — use these signals together:

```
# Per-SM active-cycle distribution (from MemoryWorkloadDistribution section)
# These show as "max XX% above average, min YY% below average" in details page
sm__cycles_active.{avg,max,min,sum}       # via action.source_info or the details page

# PM sampling (time series) — the shape matters, not just the mean
pmsampling:smsp__warps_issue_stalled_long_scoreboard.avg
pmsampling:smsp__warps_issue_stalled_short_scoreboard.avg
pmsampling:smsp__warps_issue_stalled_wait.avg
```

**Reading:**

- NCU's `details` page already says it: `"One or more SMs have a much lower number of active cycles than the average. Maximum instance value is X% above, while the minimum is Y% below."` X=51% / Y=95% (seen in practice) means severe imbalance.
- Render the PM-sampling time series (use `plot_timeline.py`). Possible shapes:
  - **Flat high → clean drop**: ideal. Well-balanced, good SM fill.
  - **Flat high → gradual tail**: tail effect. The tail's length is how much time a few slow blocks waste. Usually caused by variable-length inputs (e.g. seq_len varies per batch element).
  - **Flat low**: grid is too small (Dimension 1).
  - **Periodic waves / sawtooth**: pipeline bubbles — compute and memory alternate, nothing overlaps.

**Where imbalance typically comes from:**

1. **Variable-length per-CTA work**: when each CTA's iteration count depends on an input axis (e.g., per-element lengths driven by a prefix-sum / cumulative-length array), CTAs take very different times.
2. **Branch-and-early-exit inside the kernel**: some blocks bail early via `return`, others don't.
3. **Work-stealing without proper load balancing**: custom scheduling logic that happens to assign heavy work to a few blocks.

**Fix direction:** chunk the variable-length work (e.g., time-chunking for sequence-style workloads), or oversubscribe with work-stealing.

**Helper:** `plot_timeline.py` produces ASCII timeline plots. If you see a gradual slope on the right side, that's your tail effect.

Additionally, **always inspect the input distribution**. If per-CTA work is driven by an array like `per_element_lengths`:
```python
# Example: given a per-CTA work-count array, compute imbalance ratios
work_per_cta = [...]  # derive this from whatever drives the inner loop count
avg = sum(work_per_cta) / len(work_per_cta)
print(f"max/avg = {max(work_per_cta)/avg:.2f}x, max/min = {max(work_per_cta)/min(work_per_cta):.2f}x")
```

Ratios > 5x indicate significant potential for tail effect.

---
