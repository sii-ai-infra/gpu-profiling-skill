### Two compound signals

A single reading is ambiguous in these two cases; the pair is not.

| Pair | Reads as |
|---|---|
| tensor pipe utilisation low **and** DRAM throughput high | tensor cores are **fed too slowly**, not unused — fix the data path, not the MMA ([F](../06-diagnosis-playbook.md#pattern-f--compute-bound-but-not-on-tensor-cores)) |
| `stall_barrier` high **and** `smsp__thread_inst_executed_per_inst_executed.ratio` << 32 | divergence is *lengthening* the barrier wait — the barrier is the symptom, divergence is the cause ([N](../06-diagnosis-playbook.md#pattern-n--warp-divergence) first, then [I](../06-diagnosis-playbook.md#pattern-i--synchronization-overhead)) |

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
