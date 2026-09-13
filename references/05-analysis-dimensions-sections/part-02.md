## Dimension 3 — Stall reason breakdown + per-line hotspots

**What:** when warps aren't issuing, what are they waiting for? Which source lines generate the most stalls?

**Aggregate stall metrics (SOL-adjacent, aggregated over the kernel):**
```
# Ratio per issued warp — how many of 16 active warps are in each stall state
smsp__average_warps_issue_stalled_long_scoreboard_per_issue_active.ratio
smsp__average_warps_issue_stalled_short_scoreboard_per_issue_active.ratio
smsp__average_warps_issue_stalled_wait_per_issue_active.ratio
smsp__average_warps_issue_stalled_math_pipe_throttle_per_issue_active.ratio
smsp__average_warps_issue_stalled_mio_throttle_per_issue_active.ratio
smsp__average_warps_issue_stalled_lg_throttle_per_issue_active.ratio
smsp__average_warps_issue_stalled_barrier_per_issue_active.ratio
smsp__average_warps_issue_stalled_not_selected_per_issue_active.ratio
smsp__average_warps_issue_stalled_dispatch_stall_per_issue_active.ratio
smsp__average_warps_issue_stalled_no_instruction_per_issue_active.ratio
```

**Per-line stall metrics (from `--set source`):**
```
smsp__pcsamp_sample_count                                  # total samples
smsp__pcsamp_warps_issue_stalled_long_scoreboard           # per-PC counts
smsp__pcsamp_warps_issue_stalled_short_scoreboard
smsp__pcsamp_warps_issue_stalled_wait
smsp__pcsamp_warps_issue_stalled_selected                  # productive cycles
...
```

**Stall reasons you need to know:**

| Reason | Meaning | Typical cause | Fix direction |
|---|---|---|---|
| `long_scoreboard` | waiting on long-latency dep | global memory load hasn't returned | coalesce, reuse, add ILP |
| `short_scoreboard` | waiting on short-latency dep | shared/local memory, or compute chain | add ILP, shorten dep chains |
| `wait` | waiting on fixed-latency pipe | SFU / tensor-core output | more independent ops in flight |
| `barrier` | `__syncthreads` / mbarrier wait | other threads haven't arrived | reduce syncs, fix divergence |
| `membar` | memory fence | `__threadfence` | avoid if possible |
| `math_pipe_throttle` | FMA pipe saturated | legit compute-bound | you're doing well, find other wins |
| `mio_throttle` / `lg_throttle` / `tex_throttle` | LSU/LD-ST/TEX pipe saturated | too many load/store insns | vectorize, use shared mem |
| `not_selected` | eligible but scheduler picked another | **good sign** — plenty of parallelism | ignore |
| `selected` | actually issuing this cycle | **productive** | ignore |
| `dispatch_stall` | dispatch unit busy | rare | usually minor |
| `no_instruction` | warp has nothing to issue | kernel prologue/epilogue | usually minor |
| `drain` | warp finishing last few instructions | end of kernel | ignore |
| `branch_resolving` | branch target calc in progress | tight branches | usually minor |

**Reading the ratio metric:** a value of e.g. `smsp__average_warps_issue_stalled_long_scoreboard_per_issue_active.ratio = R` means: for every cycle in which a warp issues, R other warps (on that SM sub-partition, per cycle-with-an-issue) were stalled on `long_scoreboard`. Higher values = more stalled time. On a kernel with 16 active warps per scheduler, R is bounded above by ~15 (all other warps stalled on this reason).

**Reading the `pcsamp` percentages:** normalize by `smsp__pcsamp_sample_count` to get "% of samples stalled on X". Rules of thumb:

- **`long_scoreboard` > 40% of samples**: kernel is memory-latency-bound. Check Dimension 6 (access patterns) next.
- **`short_scoreboard` > 30%**: check for long dep chains or heavy shared-memory use.
- **`barrier` > 20%**: too much synchronization, or warp divergence before a barrier.
- **`selected` < 10%**: very little actual issue — the whole kernel is stall-bound.

**Helper:** `extract_stall_hotspots.py` produces `stall_hotspots_<tag>.txt` which ranks source lines by total stall samples. This directly points at the offending `LDG`, `BAR.SYNC`, or compute op in source.

---

## Dimension 4 — Tensor Core utilization

**What:** is the kernel using tensor cores at all? If yes, how well?

**Metrics:**
```
sm__pipe_tensor_cycles_active.avg.pct_of_peak_sustained_elapsed      # overall TC activity
sm__pipe_tensor_cycles_active.avg.pct_of_peak_sustained_active       # per active SM cycle
sm__pipe_tensor_subpipe_hmma_cycles_active.avg.pct_of_peak_sustained_elapsed  # BF16/FP16 MMA
sm__pipe_tensor_subpipe_imma_cycles_active.avg.pct_of_peak_sustained_elapsed  # INT MMA
sm__pipe_tensor_subpipe_dmma_cycles_active.avg.pct_of_peak_sustained_elapsed  # FP64 MMA
sm__ops_path_tensor_op_hmma_src_bf16_dst_fp32_sparsity_off.avg       # BF16×BF16→FP32 ops
```

**Reading:**

- **`sm__pipe_tensor_cycles_active = 0%`**: no tensor core usage at all. For matmul-ish kernels (attention, GEMM, conv), this is almost always a missed optimization.
- **`... = X%` but X << 50%**: tensor cores are being used but underutilized. Usually means data isn't arriving fast enough (Dimension 6) or tile sizes are wrong.
- **`... > 50%`** on B200: kernel is doing well on the Tensor-Core front. Focus elsewhere.

**Blackwell-specific note:** B200 uses 5th-gen tensor cores with `tcgen05.mma` + TMEM accumulators. Hand-rolled kernels need `tcgen05.alloc`, `tcgen05.mma`, `tcgen05.ld`, `tcgen05.dealloc` PTX. Most projects should use CUTLASS 4.x / cuBLAS instead of hand-rolling. The instruction semantics are in KernelWiki (`wiki/nvidia/hardware/tcgen05-mma.md`, `tmem.md`, `languages/ptx-sm100.md`); which principles shift weight on Blackwell is in the `cuda-optimization` skill (`references/blackwell-shifts.md`).

**Fix direction:** if you see 0% and the workload is matrix-multiplication-shaped, redesign around MMA. This is usually a major refactor but gives 2-10× on compute-bound paths.

---

## Dimension 5 — SM utilization timeline

**What:** how does SM utilization vary over the kernel's lifetime?

**Metrics (PM sampling, time-series):**
```
pmsampling:sm__throughput.avg.pct_of_peak_sustained_elapsed
pmsampling:sm__warps_active.avg.pct_of_peak_sustained_active
pmsampling:dram__throughput.avg.pct_of_peak_sustained_elapsed
pmsampling:smsp__warps_issue_stalled_long_scoreboard.avg
pmsampling:smsp__warps_issue_stalled_short_scoreboard.avg
```

**Reading (timeline shapes):**

- **Flat high, clean drop**: ideal.
- **Flat high, long tail**: tail effect (Dimension 2).
- **Flat low**: grid too small (Dimension 1) or severely stall-bound (Dimension 3).
- **Periodic sawtooth (compute ↕ memory)**: no compute-memory overlap — missing pipeline/double-buffering.
- **Slow ramp up, flat middle, clean drop**: kernel has warmup work (prologue), then steady state. Usually fine.

**Helper:** `plot_timeline.py` — renders ASCII plots. Look at multiple series side-by-side (SM throughput + DRAM throughput + long_scoreboard stalls) to distinguish the shapes.

**Note:** PM sampling has ~2µs interval on B200. Very short kernels (< 20 µs) produce few samples — interpret with care.

---
