# Diagnosis Playbook — Pattern → Cause → Fix

For each observed NCU signal, what does it typically mean, and what's the first fix to try? This maps profiling signals to causes. The *principles* behind the fixes -- and, more importantly, which kernel types legitimately violate them -- live in the `cuda-optimization` skill (repo `cuda-skill`); the measured values and thresholds live in KernelWiki.

Read this after you've gathered the metrics (via [`05-analysis-dimensions.md`](05-analysis-dimensions.md)) — here you translate metrics into diagnoses and fix directions.

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
| `launch__waves_per_multiprocessor` | < 0.5 -> SMs idle | [A](#pattern-a--small-grid--sm-idle) |
| per-SM active-cycle spread | max/min far apart -> imbalance | [B](#pattern-b--tail-effect-variable-length-inputs) |
| `l1tex__average_t_sectors_per_request_pipe_lsu_mem_global_op_ld.ratio` | >> 4 -> uncoalesced loads | [C](#pattern-c--uncoalesced-global-loads) |
| `smsp__sass_average_data_bytes_per_sector_mem_global_op_st.ratio` | low -> sparse writes | [D](#pattern-d--sparse-writes-low-store-efficiency) |
| `smsp__average_warps_issue_stalled_long_scoreboard_per_issue_active.ratio` | high -> waiting on memory | [E](#pattern-e--latency-bound-long-scoreboard-dominated) |
| **`smsp__warps_eligible.avg.per_cycle_active`** | **~0 -> every resident warp is stalled** | [E](#pattern-e--latency-bound-long-scoreboard-dominated) |
| **`sm__inst_executed.avg.per_cycle_active`** | **low IPC with healthy occupancy -> latency, not throughput** | [E](#pattern-e--latency-bound-long-scoreboard-dominated) |
| `sm__pipe_tensor_cycles_active.avg.pct_of_peak_sustained_elapsed` | low on a GEMM -> not on tensor cores | [F](#pattern-f--compute-bound-but-not-on-tensor-cores) |
| `lts__t_sectors_op_atom.sum` / `op_red.sum` | high -> atomic contention | [G](#pattern-g--atomics-contention) |
| `l1tex__data_pipe_lsu_wavefronts.avg.pct_of_peak_sustained_elapsed` | high -> bank conflicts | [H](#pattern-h--shared-memory-bank-conflicts) |
| **`smsp__inst_executed_op_shared_ld.sum`** | **the denominator: wavefronts / shared-ld = conflict factor** | [H](#pattern-h--shared-memory-bank-conflicts) |
| `smsp__pcsamp_warps_issue_stalled_barrier` | high -> sync overhead | [I](#pattern-i--synchronization-overhead) |
| `sm__maximum_warps_per_active_cycle_pct` vs achieved | gap -> occupancy limited | [J](#pattern-j--low-achieved-vs-theoretical-occupancy) |
| `launch__occupancy_limit_*` | names *which* resource limits it | [J](#pattern-j--low-achieved-vs-theoretical-occupancy) |
| `smsp__sass_inst_executed_op_local_ld.sum` / `_st.sum` | non-zero -> register spill | [K](#pattern-k--register-spill) |
| `sm__pipe_fp64_cycles_active.avg.pct_of_peak_sustained_active` | non-zero unintentionally -> FP64 leak | [L](#pattern-l--fp64-used-unintentionally) |
| `sm__throughput` timeline shape | sawtooth -> no overlap | [M](#pattern-m--pipeline-bubbles-no-computememory-overlap) |
| `smsp__thread_inst_executed_per_inst_executed.ratio` | << 32 -> divergence | [N](#pattern-n--warp-divergence) |
| **`sm__inst_executed_pipe_lsu.avg.pct_of_peak_sustained_elapsed`** | **near peak -> the LSU issue rate is the limit; vectorising the accesses cuts the instruction count** | [E](#pattern-e--latency-bound-long-scoreboard-dominated) |
| **`gpu__time_duration.sum`** | **the denominator for ranking -- see below** | all |

**Bold rows are new**; the rest already appear in the pattern bodies. See
[`05-analysis-dimensions.md`](05-analysis-dimensions.md) for how to collect each.

---

## NCU section / SASS / stall reason → pattern

The reverse index above is keyed by **metric name**. In practice a second
entry point is just as common: NCU tells you to open a *section*, or you are
staring at the **instruction mix** or a **stall reason** rather than a counter.
Those never resolve to a metric name, so the table above cannot route them.

### Report section → what it decides

| `--section` | What you are looking for | Pattern |
|---|---|---|
| `ComputeWorkloadAnalysis` | pipeline utilisation spread — one pipe saturated while others idle | [F](#pattern-f--compute-bound-but-not-on-tensor-cores) · [L](#pattern-l--fp64-used-unintentionally) |
| `InstructionStats` | the executed instruction mix (see next table) | [F](#pattern-f--compute-bound-but-not-on-tensor-cores) · [L](#pattern-l--fp64-used-unintentionally) |
| `MemoryWorkloadAnalysis` | shared-memory wavefront count, L1/L2 hit rates | [H](#pattern-h--shared-memory-bank-conflicts) · [C](#pattern-c--uncoalesced-global-loads) |
| `WarpStateStats` | stall-reason breakdown (see third table) | [E](#pattern-e--latency-bound-long-scoreboard-dominated) · [I](#pattern-i--synchronization-overhead) |
| `SourceCounters` (Source page) | which *lines* the stall samples land on | [I](#pattern-i--synchronization-overhead) · [E](#pattern-e--latency-bound-long-scoreboard-dominated) |

### Instruction mix → what it decides

The mix answers questions a counter cannot: *which code path did the compiler
actually emit?*

| Seen in `InstructionStats` | Reads as | Pattern |
|---|---|---|
| lots of `FFMA`, no `HMMA` / `DMMA` | fell back to the CUDA-core path, tensor cores unused | [F](#pattern-f--compute-bound-but-not-on-tensor-cores) |
| `sm__inst_executed_pipe_tensor.sum` == 0 | **no tensor instruction was issued at all** — stronger than a low utilisation % | [F](#pattern-f--compute-bound-but-not-on-tensor-cores) |
| high FP64 instruction share | unintended double precision — the usual cause is an untyped literal | [L](#pattern-l--fp64-used-unintentionally) |
| `LDG` share low vs plain `LD` | read-only data is not taking the read-only path | [C](#pattern-c--uncoalesced-global-loads) |
| `LDG`/`STG` both numerous and a large share | the LSU pipe is the bottleneck — vectorising the accesses reduces the count | [E](#pattern-e--latency-bound-long-scoreboard-dominated) |
| `BAR.SYNC` carries a large share of stall samples | barriers, not the work between them | [I](#pattern-i--synchronization-overhead) |
| high SFU utilisation | transcendental-heavy — the approximate intrinsics may apply | [F](#pattern-f--compute-bound-but-not-on-tensor-cores) |

### Stall reason → what it decides

`WarpStateStats` breaks the stalls down by reason. Three of them route
differently and are easy to confuse:

| Stall reason | Reads as | Pattern |
|---|---|---|
| `stall_long_scoreboard` | waiting on **global/local memory** | [E](#pattern-e--latency-bound-long-scoreboard-dominated) |
| `stall_short_scoreboard` | waiting on **shared memory or an MIO queue** | [H](#pattern-h--shared-memory-bank-conflicts) |
| `stall_barrier` | waiting at a barrier for sibling warps | [I](#pattern-i--synchronization-overhead) |

⚠️ **`stall_short_scoreboard` and `stall_barrier` can both indicate bank
conflicts even when shared-memory traffic looks modest.** A conflicted access
serialises inside the LSU, which shows up as its siblings waiting — so the
symptom surfaces at the barrier rather than on the shared-memory counters.
If either is high and shared traffic is low, check [H](#pattern-h--shared-memory-bank-conflicts)
before concluding the kernel is synchronisation-bound.

### Two compound signals

A single reading is ambiguous in these two cases; the pair is not.

| Pair | Reads as |
|---|---|
| tensor pipe utilisation low **and** DRAM throughput high | tensor cores are **fed too slowly**, not unused — fix the data path, not the MMA ([F](#pattern-f--compute-bound-but-not-on-tensor-cores)) |
| `stall_barrier` high **and** `smsp__thread_inst_executed_per_inst_executed.ratio` << 32 | divergence is *lengthening* the barrier wait — the barrier is the symptom, divergence is the cause ([N](#pattern-n--warp-divergence) first, then [I](#pattern-i--synchronization-overhead)) |

> ⚠️ **Host-side synchronisation does not appear anywhere in this document.**
> `cudaDeviceSynchronize` / implicit `cudaMemcpy` stalls are *between* kernels;
> NCU profiles one kernel at a time and cannot see them. Use Nsight Systems
> (`nsys`) and look for CPU gaps between short kernels.

---

## Pattern A — Small grid / SM idle

**Signals:**
- `launch__waves_per_multiprocessor < 0.5`
- `launch__grid_size < device__attribute_multiprocessor_count` (e.g., 64 blocks on a 148-SM B200)
- NCU rule: *"The grid for this launch is configured to execute only N blocks, which is less than the M multiprocessors used."* with `Est. Speedup: 50-90%`

**Why:** each CTA occupies at most one SM; with fewer CTAs than SMs, some SMs are completely idle throughout the kernel.

**First-line fix:** increase grid size. Look for a dimension the kernel currently doesn't parallelize:
- Add a split along `K` (split-K for reductions / attention).
- Split across heads / channels if grouped.
- Use Grid-stride loops so one block does multiple work units — but only if work units are cheap.

**Deeper fixes:**
- **Persistent kernel**: launch one block per SM, each block dequeues work items from an atomic counter. Good for dynamic-shape cases.
- **Fuse with adjacent kernels** so more work fits in one launch.

**Exceptions:**
- LLM decode (batch=1, query_len=1) is fundamentally small. Split-K over KV length is the standard mitigation.
- Final reduction stages of a multi-level reduction are naturally small; fuse them into the producing kernel.

**Cross-ref:** `cuda-optimization` principle 1 (occupancy / waves) -- see its `references/fix-directions.md` for the fix menu and `references/legitimate-violations.md` for the kernel types where a low reading is correct. Blackwell launch/2CTA notes: `references/blackwell-shifts.md`.

---

## Pattern B — Tail effect (variable-length inputs)

**Signals:**
- Multi-workload: `max_seq_len / avg_seq_len > 3` in input distribution.
- Per-SM active cycles span 5-100× between slowest and fastest SM (from `--page details` distribution).
- PM timeline shape: long gradual tail at the end (visible via `plot_timeline.py`).
- `launch__waves_per_multiprocessor > 1.05` with partial last wave.
- NCU rule: `"partial wave may account for up to X% of the total runtime"`.

**Why:** each CTA iterates some variable-size inner loop. When sequences have vastly different lengths, a few long-sequence CTAs keep running after everyone else finished.

**First-line fix (cheap):**
- **Packed batching / sorting**: sort inputs by length (at the application level) so CTAs running concurrently do roughly equal work.
- **Split long sequences across more CTAs**: add a `split_factor` grid dimension; each CTA handles `ceil(seq_len / split_factor)` tokens, and a small post-reduction combines partials.

**Deeper fixes:**
- **Chunkwise kernel**: break each sequence into fixed-size chunks, process chunks in parallel, then stitch with a small recurrence. This is the approach of flash-linear-attention's `chunk_delta_rule_fwd` for Mamba/GLA-style recurrences.
- **Classify-and-dispatch**: short sequences go through the simple path (one CTA per seq), long sequences through the chunked path.

**Exceptions:**
- Short kernels (< 10 µs) where partial-wave cost is absolute-small.
- Workloads where you already pre-sort / pre-pack.

**Cross-ref:** `cuda-optimization` principle 11 (`references/fix-directions.md` for the fix menu, `references/legitimate-violations.md` for the kernel types where this reading is correct); `references/blackwell-shifts.md` for how B200 changes its weight.

---

## Pattern C — Uncoalesced global loads

**Signals:**
- `l1tex__t_sectors_pipe_lsu_mem_global_op_ld.sum / l1tex__t_requests_pipe_lsu_mem_global_op_ld.sum > 5` (ideal is 4).
- NCU rule: *"uncoalesced global accesses resulting in N excessive sectors (X% of the total)"*.
- NCU rule: *"On average, only Y of the 32 bytes transmitted per sector are utilized"*.
- Primary stall reason on the offending load line is `long_scoreboard`.

**Why:** lanes in a warp access non-contiguous addresses; hardware fetches extra sectors that only a few lanes use.

**First-line fix:** rework the thread ↔ data mapping:
- If current pattern is `x[lane * K + i]` (stride K), flip to `x[lane + i * 32]` (coalesced).
- Check AoS layouts: `struct { float a, b; } arr[N]` → `struct { float a[N], b[N]; }` so each field is a separate coalesced stream.

**Deeper fixes:**
- Use shared memory as a transposer: coalesced-load to shared, then arbitrary-access from shared.
- Vectorize: replace scalar `LDG.E` with `LDG.E.64` / `LDG.E.128` (use `float2` / `float4` / `ushort2` types).

**Exceptions:**
- Gather/scatter by random index (sparse matmul, embedding lookup) — fundamentally uncoalesced. Sort the indices for locality if possible.
- Graph / tree traversal.

**Cross-ref:** Blackwell principles 2, 13.

---

## Pattern D — Sparse writes (low store efficiency)

**Signals:**
- `smsp__sass_average_data_bytes_per_sector_mem_global_op_st.ratio < 16` (ideal is 32).
- `l1tex__t_sector_pipe_lsu_mem_global_op_st_hit_rate.pct` lower than expected.
- Code contains patterns like `if (lane_id < K) { output[...] = ... }`.

**Why:** only a subset of warp lanes write, so the L1 store buffer flushes half-empty sectors.

**First-line fix:** pack the write. Have the warp collectively produce `K` values first (via shuffle or shared memory reduction), then have exactly `K` contiguous lanes perform `K` consecutive writes.

If `K ≥ 32`: all lanes can write; make sure the per-lane index is contiguous.

If `K < 8`: consider batching multiple iterations' results into a vectorized write (e.g., 4 iterations' output packed into a single `float4`).

**Deeper fixes:**
- Write into shared memory first, then do a coalesced global store at the end of the block.

**Exceptions:**
- Histogram / scatter (inherently sparse) — different optimization path, see Pattern G.

---

## Pattern E — Latency-bound (long-scoreboard-dominated)

**Signals:**
- `smsp__warps_eligible.avg.per_cycle_active` near zero — **the most direct statement of the problem**: warps are resident but none is ready to issue. Occupancy can look fine and this still be ~0.
- `sm__inst_executed.avg.per_cycle_active` (IPC) low while occupancy is healthy — the SM has warps and is not issuing from them. Compare against `sm__inst_issued` to separate "not issuing" from "issuing and replaying".
- `smsp__pcsamp_warps_issue_stalled_long_scoreboard / smsp__pcsamp_sample_count > 0.40`.
- `smsp__average_warps_issue_stalled_long_scoreboard_per_issue_active.ratio > 3`.
- `dram__bytes_read.sum.pct_of_peak_sustained_elapsed < 10%` (→ not DRAM-bandwidth-bound).
- Hotspot lines are global loads (check `stall_hotspots_<tag>.txt`).

**Why:** warps issue a load, then stall waiting for it to return before the next dependent op. Usually combined with low occupancy or insufficient ILP.

**First-line fix:** increase in-flight memory requests:
- **Unroll the load loop** so 4-8 loads are issued before any value is used. Compiler + hardware reorders.
- **Add more independent warps** — raise occupancy (Pattern J).
- **`cp.async` (Ampere+) / TMA (Hopper+) / tcgen05.cp (Blackwell)** for bulk async loads that don't block issue.

**Deeper fixes:**
- Software pipelining: while tile N is being computed, pre-load tile N+1 into shared memory.
- Move reused data to shared memory so subsequent loads hit L1.

**Exceptions:**
- Pointer chasing / graph traversal — data dep chain is fundamental.

**Cross-ref:** Blackwell principles 7, 15.

---

## Pattern F — Compute-bound but not on tensor cores

**Signals:**
- `sm__inst_executed_pipe_fma.avg.pct_of_peak_sustained_active > 50%`.
- `sm__pipe_tensor_cycles_active.avg.pct_of_peak_sustained_elapsed = 0%`.
- Workload is matmul-ish (GEMM, attention, conv).

**Why:** kernel uses scalar FMA via the ALU pipe instead of tensor cores. On B200, tensor cores can do 16× the FMA throughput of scalar pipes for BF16→FP32.

**First-line fix:** use `WMMA` (Ampere+) / `wgmma` (Hopper) / `tcgen05.mma` (Blackwell). If hand-rolling is too much, use CUTLASS 4.x or cuBLAS, which are already tuned for the target arch.

**Deeper fixes:**
- Restructure data layout to meet MMA tile-shape constraints (e.g., `m16n8k16` for BF16).
- Use shared memory + TMA (Hopper) / TMEM (Blackwell) staging.

**Exceptions:**
- Non-matrix workloads (reduction, sort, element-wise) — tensor cores don't help.
- Small matrices (M, N, K < 32) — tensor-core tiles are too coarse.

**Cross-ref:** `cuda-optimization` principle 10; the tcgen05 PTX itself is in KernelWiki (`wiki/nvidia/hardware/tcgen05-mma.md`, `tmem.md`, `languages/ptx-sm100.md`).

---

## Pattern G — Atomics contention

**Signals:**
- `long_scoreboard` samples concentrate on `ATOM` / `RED` SASS instructions.
- `lts__t_sectors_op_atom.sum` or `lts__t_sectors_op_red.sum` is large.
- L2 throughput is high but compute throughput is low.

**Why:** many threads atomically updating few locations → serialization.

**First-line fix:** hierarchical reduction.
- Within-warp: `__shfl_down_sync` (no atomic).
- Within-block: shared memory reduction (no atomic).
- Between blocks: single atomic at the end per block.

**Deeper fixes:**
- Shared-memory histogram that flushes to global in one coalesced pass.
- Bucketing: thread writes to `output[tid % N_buckets]`, followed by a merge kernel.

**Exceptions:**
- NCCL-style communication — atomics are fundamental there.

**Cross-ref:** `cuda-optimization` principle 12 (`references/fix-directions.md` for the fix menu, `references/legitimate-violations.md` for the kernel types where this reading is correct); `references/blackwell-shifts.md` for how B200 changes its weight.

---

## Pattern H — Shared-memory bank conflicts

**Signals:**
- **`l1tex__data_pipe_lsu_wavefronts...` alone does not give you the conflict factor** — it is a numerator. Divide it by `smsp__inst_executed_op_shared_ld.sum` (+ `_op_shared_st.sum`): a conflict-free access is 1 wavefront per instruction, an N-way conflict is N. Reporting the wavefront count without its denominator says "there is shared traffic", not "there are conflicts".
- `l1tex__data_pipe_lsu_wavefronts.avg.pct_of_peak_sustained_elapsed` high for shared-mem ops.
- `short_scoreboard` stalls concentrated on shared-memory load lines.
- Access pattern has regular strides that align to bank boundaries.

**Why:** shared memory has 32 banks; same-bank accesses serialize.

**First-line fix:** padding. `__shared__ float tile[32][33]` instead of `[32][32]` breaks regular bank alignment.

**Deeper fixes:**
- Swizzle: XOR-scramble indices so accesses spread across banks.
- Restructure data layout so warp lanes access different banks.

**Exceptions:**
- Broadcast reads (all lanes read same address) are conflict-free.
- Low shared-mem access volume — don't bother.

**Cross-ref:** `cuda-optimization` principle 4 (`references/fix-directions.md` for the fix menu, `references/legitimate-violations.md` for the kernel types where this reading is correct); `references/blackwell-shifts.md` for how B200 changes its weight.

---

## Pattern I — Synchronization overhead

**Signals:**
- `smsp__pcsamp_warps_issue_stalled_barrier` > 20% of samples.
- Source hotspot line is `BAR.SYNC`.

**Why:** `__syncthreads()` waits for the slowest warp. Combined with any per-warp work imbalance, this amplifies.

**First-line fix:**
- Replace block-level syncs with warp-level primitives (`__shfl_sync`, `__ballot_sync`, `__syncwarp`) where only warp-scoped synchronization is needed.
- Reduce total sync count — consolidate multiple synchronized phases.

**Deeper fixes:**
- Warp-specialized execution: producer warps and consumer warps with mbarrier instead of `__syncthreads`.

**Cross-ref:** `cuda-optimization` principle 16 (`references/fix-directions.md` for the fix menu, `references/legitimate-violations.md` for the kernel types where this reading is correct); `references/blackwell-shifts.md` for how B200 changes its weight.

---

## Pattern J — Low achieved vs theoretical occupancy

**Signals:**
- `sm__maximum_warps_per_active_cycle_pct > 50` but `sm__warps_active.avg.pct_of_peak_sustained_active << 50`.
- NCU rule: *"The difference between calculated theoretical (X%) and measured achieved occupancy (Y%) ..."*.

**Why:** Theoretical occupancy is the max warps that *could* be resident. Achieved is how many are *actually* running. Gap is caused by: stalls (leaves slots empty), imbalance (some SMs empty), short kernel (warmup dominates).

**Reading:** if the gap is large AND Pattern B (tail effect) is present, fixing imbalance will close the gap. If no imbalance, look at stall reasons (Pattern E, H, I).

**First-line fix:** look for the stall reason causing the gap and address that pattern.

---

## Pattern K — Register spill

**Signals:**
- `smsp__sass_inst_executed_op_local_ld.sum > 0` or `smsp__sass_inst_executed_op_local_st.sum > 0`.
- NCU rule: *"N bytes spilled to local memory"* in Instruction Statistics.
- `launch__registers_per_thread > 128`.

**Why:** compiler couldn't fit all live variables in registers, spilled some to local memory (which is DRAM-backed).

**First-line fix:** `__launch_bounds__(maxThreadsPerBlock, minBlocksPerMultiprocessor)` on the kernel. This tells the compiler to stay within a register budget.

**Deeper fixes:**
- Reduce the number of live values: recompute values instead of caching, split the kernel into two.
- Move per-thread arrays to shared memory with explicit indexing.

**Exceptions:**
- Large fused kernels (FlashAttention) accept some spill in exchange for larger savings upstream.

**Cross-ref:** `cuda-optimization` principle 6 (`references/fix-directions.md` for the fix menu, `references/legitimate-violations.md` for the kernel types where this reading is correct); `references/blackwell-shifts.md` for how B200 changes its weight.

---

## Pattern L — FP64 used unintentionally

**Signals:**
- `sm__pipe_fp64_cycles_active.avg.pct_of_peak_sustained_active > 0` in a kernel that "should" be FP32.

**Why:** C/C++ floating-point literals (`1.0`, `0.5`, `3.14`) default to `double`. A `float x = a + 1.0 * b;` promotes `a + 1.0*b` to double.

**First-line fix:** add `f` suffix to all literals: `1.0f`, `0.5f`, `3.14f`. Add `__expf` / `__logf` / `__sinf` variants for transcendentals.

**Cross-ref:** `cuda-optimization` principle 8 (`references/fix-directions.md` for the fix menu, `references/legitimate-violations.md` for the kernel types where this reading is correct); `references/blackwell-shifts.md` for how B200 changes its weight.

---

## Pattern M — Pipeline bubbles (no compute/memory overlap)

**Signals:**
- PM timeline of `sm__throughput` and `dram__throughput` shows a sawtooth (high compute ↔ high DRAM alternating).
- `long_scoreboard` stalls high but DRAM throughput also high.

**Why:** kernel loads a tile, computes on it, loads next tile — single-buffered.

**First-line fix:** double-buffer. Use two shared-memory tiles; while computing on tile A, load tile B. `__syncthreads` between phases.

**Deeper fixes:**
- Multi-stage pipeline (3-4 stages on Blackwell — see KernelWiki `wiki/nvidia/techniques/pipeline-stages.md` for stage-count selection). Use `cp.async` / TMA for async loads.

**Cross-ref:** `cuda-optimization` principle 15 (`references/fix-directions.md` for the fix menu, `references/legitimate-violations.md` for the kernel types where this reading is correct); `references/blackwell-shifts.md` for how B200 changes its weight.

---

## Pattern N — Warp divergence

**Signals:**
- `smsp__thread_inst_executed_per_inst_executed.ratio < 32` (far from the 32 ideal).
- Branch efficiency metric low in `--page details`.
- Divergent branches cluster on specific source lines.

**Why:** lanes in a warp take different paths at a branch; hardware serializes.

**First-line fix:**
- Rearrange so all lanes in a warp take the same branch. Sort / partition data if possible.
- Convert `if (cond) a else b` to branchless `mask * a + (1-mask) * b` — cheap if both sides are cheap.

**Exceptions:**
- Tree reductions in warps (last few steps have half / quarter / ... active). Use `__shfl_down_sync` to handle cleanly.
- Boundary handling (a few warps at tensor edge) — not worth fighting.

**Cross-ref:** `cuda-optimization` principle 5 (`references/fix-directions.md` for the fix menu, `references/legitimate-violations.md` for the kernel types where this reading is correct); `references/blackwell-shifts.md` for how B200 changes its weight.

---

## Ranking template for the final report


**Rank in absolute time, not in percentages.** Every `Est. Speedup: X%` NCU prints
is a fraction *of this kernel*. Multiply it by `gpu__time_duration.sum` before
comparing patterns across kernels -- a 60% win on a 3 us kernel loses to a 5% win
on a 900 us one, and the percentage view hides that completely.

When you hand back an optimization plan, rank by `(expected speedup) × (effort ratio)`. NCU's `Est. Speedup` is your best estimator.

```
Priority 1: <pattern> — <concrete fix>
  Evidence: <metric value(s)>
  NCU Est. Speedup: X%
  Effort: <low / medium / high>
  Why now: <reason this is the highest-leverage fix>

Priority 2: ...
```

A good rule of thumb: at most 3-5 priorities in the plan. More than that dilutes the signal, and priorities > 5 usually contribute < 5% speedup each.
