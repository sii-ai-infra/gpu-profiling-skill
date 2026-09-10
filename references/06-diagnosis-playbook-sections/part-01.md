# Diagnosis Playbook — Pattern → Cause → Fix

For each observed NCU signal, what does it typically mean, and what's the first fix to try? This maps profiling signals to causes. The *principles* behind the fixes -- and, more importantly, which kernel types legitimately violate them -- live in the `cuda-optimization` skill (repo `cuda-skill`); the measured values and thresholds live in KernelWiki.

Read this after you've gathered the metrics (via [`05-analysis-dimensions.md`](../05-analysis-dimensions.md)) — here you translate metrics into diagnoses and fix directions.

---

## How to use this doc

For each *observation* below, read:

- **Signals** — what specific metric values flag this pattern.
- **Why** — the underlying cause.
- **First-line fix** — the cheapest change to try.
- **Deeper fixes** — when first-line isn't enough.
- **Exceptions** — kernel types where this pattern is actually *expected* and should be left alone.

Most kernels will match 2-4 patterns simultaneously. **Rank them by magnitude** using NCU's `Est. Speedup: X%` fields (from `--page details`) and the stall-percentage breakdown. Fix the biggest one first.

---

## Metric → pattern reverse index

The patterns below are organised **pattern-first**: you suspect something, you
look it up. The other direction happens more often in practice -- you are staring
at a metric that looks wrong and want to know what it implicates. That is what
this table is for.

| Metric | Reads as | Pattern |
|---|---|---|
| `launch__waves_per_multiprocessor` | < 0.5 -> SMs idle | [A](../06-diagnosis-playbook.md#pattern-a--small-grid--sm-idle) |
| per-SM active-cycle spread | max/min far apart -> imbalance | [B](../06-diagnosis-playbook.md#pattern-b--tail-effect-variable-length-inputs) |
| `l1tex__average_t_sectors_per_request_pipe_lsu_mem_global_op_ld.ratio` | >> 4 -> uncoalesced loads | [C](../06-diagnosis-playbook.md#pattern-c--uncoalesced-global-loads) |
| `smsp__sass_average_data_bytes_per_sector_mem_global_op_st.ratio` | low -> sparse writes | [D](../06-diagnosis-playbook.md#pattern-d--sparse-writes-low-store-efficiency) |
| `smsp__average_warps_issue_stalled_long_scoreboard_per_issue_active.ratio` | high -> waiting on memory | [E](../06-diagnosis-playbook.md#pattern-e--latency-bound-long-scoreboard-dominated) |
| **`smsp__warps_eligible.avg.per_cycle_active`** | **~0 -> every resident warp is stalled** | [E](../06-diagnosis-playbook.md#pattern-e--latency-bound-long-scoreboard-dominated) |
| **`sm__inst_executed.avg.per_cycle_active`** | **low IPC with healthy occupancy -> latency, not throughput** | [E](../06-diagnosis-playbook.md#pattern-e--latency-bound-long-scoreboard-dominated) |
| `sm__pipe_tensor_cycles_active.avg.pct_of_peak_sustained_elapsed` | low on a GEMM -> not on tensor cores | [F](../06-diagnosis-playbook.md#pattern-f--compute-bound-but-not-on-tensor-cores) |
| `lts__t_sectors_op_atom.sum` / `op_red.sum` | high -> atomic contention | [G](../06-diagnosis-playbook.md#pattern-g--atomics-contention) |
| `l1tex__data_pipe_lsu_wavefronts.avg.pct_of_peak_sustained_elapsed` | high -> bank conflicts | [H](../06-diagnosis-playbook.md#pattern-h--shared-memory-bank-conflicts) |
| **`smsp__inst_executed_op_shared_ld.sum`** | **the denominator: wavefronts / shared-ld = conflict factor** | [H](../06-diagnosis-playbook.md#pattern-h--shared-memory-bank-conflicts) |
| `smsp__pcsamp_warps_issue_stalled_barrier` | high -> sync overhead | [I](../06-diagnosis-playbook.md#pattern-i--synchronization-overhead) |
| `sm__maximum_warps_per_active_cycle_pct` vs achieved | gap -> occupancy limited | [J](../06-diagnosis-playbook.md#pattern-j--low-achieved-vs-theoretical-occupancy) |
| `launch__occupancy_limit_*` | names *which* resource limits it | [J](../06-diagnosis-playbook.md#pattern-j--low-achieved-vs-theoretical-occupancy) |
| `smsp__sass_inst_executed_op_local_ld.sum` / `_st.sum` | non-zero -> register spill | [K](../06-diagnosis-playbook.md#pattern-k--register-spill) |
| `sm__pipe_fp64_cycles_active.avg.pct_of_peak_sustained_active` | non-zero unintentionally -> FP64 leak | [L](../06-diagnosis-playbook.md#pattern-l--fp64-used-unintentionally) |
| `sm__throughput` timeline shape | sawtooth -> no overlap | [M](../06-diagnosis-playbook.md#pattern-m--pipeline-bubbles-no-computememory-overlap) |
| `smsp__thread_inst_executed_per_inst_executed.ratio` | << 32 -> divergence | [N](../06-diagnosis-playbook.md#pattern-n--warp-divergence) |
| **`sm__inst_executed_pipe_lsu.avg.pct_of_peak_sustained_elapsed`** | **near peak -> the LSU issue rate is the limit; vectorising the accesses cuts the instruction count** | [E](../06-diagnosis-playbook.md#pattern-e--latency-bound-long-scoreboard-dominated) |
| **`gpu__time_duration.sum`** | **the denominator for ranking -- see below** | all |

**Bold rows are new**; the rest already appear in the pattern bodies. See
[`05-analysis-dimensions.md`](../05-analysis-dimensions.md) for how to collect each.

---

## NCU section / SASS / stall reason → pattern

The reverse index above is keyed by **metric name**. In practice a second
entry point is just as common: NCU tells you to open a *section*, or you are
staring at the **instruction mix** or a **stall reason** rather than a counter.
Those never resolve to a metric name, so the table above cannot route them.

### Report section → what it decides

| `--section` | What you are looking for | Pattern |
|---|---|---|
| `ComputeWorkloadAnalysis` | pipeline utilisation spread — one pipe saturated while others idle | [F](../06-diagnosis-playbook.md#pattern-f--compute-bound-but-not-on-tensor-cores) · [L](../06-diagnosis-playbook.md#pattern-l--fp64-used-unintentionally) |
| `InstructionStats` | the executed instruction mix (see next table) | [F](../06-diagnosis-playbook.md#pattern-f--compute-bound-but-not-on-tensor-cores) · [L](../06-diagnosis-playbook.md#pattern-l--fp64-used-unintentionally) |
| `MemoryWorkloadAnalysis` | shared-memory wavefront count, L1/L2 hit rates | [H](../06-diagnosis-playbook.md#pattern-h--shared-memory-bank-conflicts) · [C](../06-diagnosis-playbook.md#pattern-c--uncoalesced-global-loads) |
| `WarpStateStats` | stall-reason breakdown (see third table) | [E](../06-diagnosis-playbook.md#pattern-e--latency-bound-long-scoreboard-dominated) · [I](../06-diagnosis-playbook.md#pattern-i--synchronization-overhead) |
| `SourceCounters` (Source page) | which *lines* the stall samples land on | [I](../06-diagnosis-playbook.md#pattern-i--synchronization-overhead) · [E](../06-diagnosis-playbook.md#pattern-e--latency-bound-long-scoreboard-dominated) |

### Instruction mix → what it decides

The mix answers questions a counter cannot: *which code path did the compiler
actually emit?*

| Seen in `InstructionStats` | Reads as | Pattern |
|---|---|---|
| lots of `FFMA`, no `HMMA` / `DMMA` | fell back to the CUDA-core path, tensor cores unused | [F](../06-diagnosis-playbook.md#pattern-f--compute-bound-but-not-on-tensor-cores) |
| `sm__inst_executed_pipe_tensor.sum` == 0 | **no tensor instruction was issued at all** — stronger than a low utilisation % | [F](../06-diagnosis-playbook.md#pattern-f--compute-bound-but-not-on-tensor-cores) |
| high FP64 instruction share | unintended double precision — the usual cause is an untyped literal | [L](../06-diagnosis-playbook.md#pattern-l--fp64-used-unintentionally) |
| `LDG` share low vs plain `LD` | read-only data is not taking the read-only path | [C](../06-diagnosis-playbook.md#pattern-c--uncoalesced-global-loads) |
| `LDG`/`STG` both numerous and a large share | the LSU pipe is the bottleneck — vectorising the accesses reduces the count | [E](../06-diagnosis-playbook.md#pattern-e--latency-bound-long-scoreboard-dominated) |
| `BAR.SYNC` carries a large share of stall samples | barriers, not the work between them | [I](../06-diagnosis-playbook.md#pattern-i--synchronization-overhead) |
| high SFU utilisation | transcendental-heavy — the approximate intrinsics may apply | [F](../06-diagnosis-playbook.md#pattern-f--compute-bound-but-not-on-tensor-cores) |

### Stall reason → what it decides

`WarpStateStats` breaks the stalls down by reason. Three of them route
differently and are easy to confuse:

| Stall reason | Reads as | Pattern |
|---|---|---|
| `stall_long_scoreboard` | waiting on **global/local memory** | [E](../06-diagnosis-playbook.md#pattern-e--latency-bound-long-scoreboard-dominated) |
| `stall_short_scoreboard` | waiting on **shared memory or an MIO queue** | [H](../06-diagnosis-playbook.md#pattern-h--shared-memory-bank-conflicts) |
| `stall_barrier` | waiting at a barrier for sibling warps | [I](../06-diagnosis-playbook.md#pattern-i--synchronization-overhead) |

⚠️ **`stall_short_scoreboard` and `stall_barrier` can both indicate bank
conflicts even when shared-memory traffic looks modest.** A conflicted access
serialises inside the LSU, which shows up as its siblings waiting — so the
symptom surfaces at the barrier rather than on the shared-memory counters.
If either is high and shared traffic is low, check [H](../06-diagnosis-playbook.md#pattern-h--shared-memory-bank-conflicts)
before concluding the kernel is synchronisation-bound.
