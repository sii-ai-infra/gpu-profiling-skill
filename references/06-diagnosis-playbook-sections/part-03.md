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
