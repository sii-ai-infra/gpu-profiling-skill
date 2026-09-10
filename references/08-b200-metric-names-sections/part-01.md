# B200 (sm_100) Metric Name Reference

The stock `ncu_profile_skill.md` in older docs references metric names that **don't exist on B200 / sm_100**. This doc lists the actual names available in Nsight Compute 2026.1 on B200 and flags which names are different from older GPUs.

If a metric returns `None` on your kernel, first check this doc, then enumerate available names:

```python
action.metric_names()
```

---

## Metric names that changed

| Stock skill name (older GPU) | B200 / sm_100 name |
|---|---|
| `smsp__inst_executed_op_global_ld.sum` | **`smsp__sass_inst_executed_op_global_ld.sum`** |
| `smsp__inst_executed_op_global_st.sum` | **`smsp__sass_inst_executed_op_global_st.sum`** |
| `smsp__inst_executed_op_local_ld.sum` | **`smsp__sass_inst_executed_op_local_ld.sum`** |
| `smsp__inst_executed_op_local_st.sum` | **`smsp__sass_inst_executed_op_local_st.sum`** |
| `smsp__inst_executed_op_shared_ld.sum` | **`smsp__sass_inst_executed_op_shared_ld.sum`** |
| `smsp__inst_executed_op_shared_st.sum` | **`smsp__sass_inst_executed_op_shared_st.sum`** |
| `l1tex__average_t_sectors_per_request_pipe_lsu_mem_global_op_ld.ratio` | (not available directly; compute from `l1tex__t_sectors_pipe_lsu_mem_global_op_ld.sum / l1tex__t_requests_pipe_lsu_mem_global_op_ld.sum`) |
| `dram__bytes.sum` | (not directly; use `dram__bytes_read.sum + dram__bytes_write.sum`) |
| `sm__inst_executed_pipe_fmaheavy.*` | *not present on B200* — use `sm__inst_executed_pipe_fma.*` instead |
| `smsp__warps_issue_stalled_<reason>_per_issue_active.pct` | **`smsp__average_warps_issue_stalled_<reason>_per_issue_active.ratio`** (note `average_` prefix and `ratio` suffix) |

---

## Canonical sm_100 metric set (curated)

These metric names have been confirmed to exist and return meaningful values on B200 / sm_100 with Nsight Compute 2026.1. Always verify for your specific ncu version by enumerating with `action.metric_names()` — NVIDIA occasionally renames metrics between releases.

### Launch geometry / occupancy
```
launch__grid_size
launch__block_size
launch__grid_dim_x, launch__grid_dim_y, launch__grid_dim_z
launch__block_dim_x, launch__block_dim_y, launch__block_dim_z
launch__thread_count
launch__waves_per_multiprocessor
launch__registers_per_thread
launch__shared_mem_per_block
launch__shared_mem_per_block_static
launch__shared_mem_per_block_dynamic
launch__occupancy_limit_blocks
launch__occupancy_limit_registers
launch__occupancy_limit_shared_mem
launch__occupancy_limit_warps
device__attribute_multiprocessor_count
device__attribute_max_warps_per_multiprocessor
sm__maximum_warps_per_active_cycle_pct              # theoretical occupancy %
```

### SOL (Speed-of-Light) / throughput
```
sm__throughput.avg.pct_of_peak_sustained_elapsed
gpu__compute_memory_throughput.avg.pct_of_peak_sustained_elapsed
gpu__compute_memory_access_throughput.avg.pct_of_peak_sustained_elapsed
gpu__compute_memory_request_throughput.avg.pct_of_peak_sustained_elapsed
l1tex__throughput.avg.pct_of_peak_sustained_active
lts__throughput.avg.pct_of_peak_sustained_elapsed
dram__bytes_read.sum
dram__bytes_read.sum.pct_of_peak_sustained_elapsed
dram__bytes_read.sum.per_second                       # achieved BW
dram__bytes_write.sum
dram__bytes_write.sum.pct_of_peak_sustained_elapsed
dram__sectors_read.sum
dram__sectors_write.sum
```

### Timing
```
gpu__time_duration.sum                                # units: ns (check .unit())
smsp__cycles_active.avg
smsp__issue_active.avg.per_cycle_active               # issue rate per scheduler
smsp__issue_active.avg.pct_of_peak_sustained_active
```

### Warp activity
```
sm__warps_active.avg.pct_of_peak_sustained_active     # achieved occupancy %
sm__warps_active.avg.per_cycle_active
sm__warps_active.max.per_cycle_active
sm__warps_active.min.per_cycle_active
smsp__warps_active.avg.per_cycle_active               # per sub-partition
smsp__warps_eligible.avg.per_cycle_active
smsp__warps_eligible.max.per_cycle_active
```

### Compute pipelines
```
sm__inst_executed.avg.per_cycle_active                # IPC
sm__inst_executed_pipe_fma.avg.pct_of_peak_sustained_active
sm__inst_executed_pipe_fma.avg.pct_of_peak_sustained_elapsed
sm__inst_executed_pipe_alu.avg.pct_of_peak_sustained_active
sm__inst_executed_pipe_alu.avg.pct_of_peak_sustained_elapsed
sm__inst_executed_pipe_lsu.avg.pct_of_peak_sustained_active
sm__inst_executed_pipe_lsu.avg.pct_of_peak_sustained_elapsed
sm__inst_executed_pipe_xu.avg.pct_of_peak_sustained_active
sm__inst_executed_pipe_fp64.avg.pct_of_peak_sustained_active
sm__inst_executed_pipe_adu.avg.pct_of_peak_sustained_active

sm__pipe_tensor_cycles_active.avg.pct_of_peak_sustained_active
sm__pipe_tensor_cycles_active.avg.pct_of_peak_sustained_elapsed
sm__pipe_tensor_subpipe_hmma_cycles_active.avg.pct_of_peak_sustained_elapsed
sm__pipe_tensor_subpipe_imma_cycles_active.avg.pct_of_peak_sustained_elapsed
sm__pipe_tensor_subpipe_dmma_cycles_active.avg.pct_of_peak_sustained_elapsed
sm__ops_path_tensor_op_hmma_src_bf16_dst_fp32_sparsity_off.avg   # raw BF16→FP32 tensor ops
```
