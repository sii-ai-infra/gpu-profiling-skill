## Dimension 6 — Memory access pattern & cache efficiency

**What:** are global loads coalesced? Are caches hit? Is DRAM actually busy?

**Metrics:**
```
# DRAM
dram__bytes_read.sum
dram__bytes_read.sum.pct_of_peak_sustained_elapsed
dram__bytes_write.sum.pct_of_peak_sustained_elapsed
dram__bytes_read.sum.per_second                    # achieved BW

# L1 / L2 hit rates
l1tex__t_sector_hit_rate.pct
lts__t_sector_hit_rate.pct
l1tex__t_sector_pipe_lsu_mem_global_op_ld_hit_rate.pct
l1tex__t_sector_pipe_lsu_mem_global_op_st_hit_rate.pct

# Sectors per request (coalescing quality)
l1tex__t_sectors_pipe_lsu_mem_global_op_ld.sum              # total sectors
l1tex__t_requests_pipe_lsu_mem_global_op_ld.sum             # total requests
# Compute sectors/request yourself — ideal is 4 (128B aligned load)

# Store efficiency
smsp__sass_average_data_bytes_per_sector_mem_global_op_st.ratio  # useful bytes/sector, max 32

# Register spill (local memory)
smsp__sass_inst_executed_op_local_ld.sum
smsp__sass_inst_executed_op_local_st.sum

# Global instruction counts
smsp__sass_inst_executed_op_global_ld.sum
smsp__sass_inst_executed_op_global_st.sum
smsp__sass_inst_executed_op_shared.sum                     # 0 if no shared memory
```

**Reading:**

- **`dram__bytes_read.sum.pct_of_peak_sustained_elapsed` ≈ 80-100%**: genuinely DRAM-bandwidth-bound. Reduce bytes / amortize reads with shared memory.
- **`... << 10%` but kernel is slow**: *not* bandwidth-bound. It's latency-bound (Dimension 3) or compute-bound (check `sm__throughput`).
- **`l1tex__t_sector_hit_rate.pct > 90%`**: good data locality, L1 is absorbing the reuse.
- **`lts__t_sector_hit_rate.pct < 50%`**: L2 is being blown through, reads fall to DRAM.
- **Sectors/request = 4.0 (ideal 128B fully-coalesced) to 5.0**: small coalescing issue but acceptable.
- **Sectors/request > 8.0**: serious non-coalesced access — big optimization opportunity.
- **`smsp__sass_average_data_bytes_per_sector_mem_global_op_st.ratio < 16`**: stores are using less than half of each 32B sector. Usually means only a subset of warp lanes write (e.g. `if (lane_id < 4)` patterns).
- **`smsp__sass_inst_executed_op_local_ld.sum > 0`**: **register spill** — very bad, local memory is DRAM-backed. Reduce register pressure with `__launch_bounds__` or kernel splitting.
- **`smsp__sass_inst_executed_op_shared.sum == 0`**: kernel uses no shared memory. Fine for element-wise kernels; often a missed optimization for data-reuse-heavy kernels.

NCU's rule engine often reports the coalescing issue directly:
```
OPT   Est. Speedup: 10.8%
      The memory access pattern for global loads from L1TEX might not be optimal.
      On average, only 7.6 of the 32 bytes transmitted per sector are utilized...
```

**Fix directions (by pattern):**

- Strided access (e.g. `x[lane * stride + i]`): change the per-thread layout so lanes access contiguous elements.
- AoS → SoA: restructure the data.
- Sparse writes: pack writes into a single coalesced store at the end of the warp.
- Register spill: add `__launch_bounds__`, reduce intermediate variables, or split kernel.

---

## Cross-dimension synthesis

After walking through all six, write a one-line diagnosis combining them. Structure: name the top 3–4 signals, each tied to a specific dimension. For example:

> "The kernel runs at X% of peak SM throughput and Y% of peak DRAM (Dim 1, 6). Stall time is dominated by `<stall_reason>` (Z% of samples, Dim 3), concentrated on <N> source lines whose access pattern is <coalesced/uncoalesced/...> (Dim 6). The PM timeline shows <flat / tail / sawtooth> shape (Dim 2/5). Tensor cores <used / unused at W%> (Dim 4)."

Fill in the X/Y/Z/W/N values and <classifications> from your own report. That sentence is the deliverable. Everything else in the report is evidence backing it.
