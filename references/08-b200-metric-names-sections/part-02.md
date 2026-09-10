### Cache hit rates
```
l1tex__t_sector_hit_rate.pct                                       # overall L1
lts__t_sector_hit_rate.pct                                         # overall L2
l1tex__t_sector_pipe_lsu_mem_global_op_ld_hit_rate.pct             # L1 hit on global loads
l1tex__t_sector_pipe_lsu_mem_global_op_st_hit_rate.pct             # L1 hit on global stores
```

### Memory access counts & sectors
```
smsp__sass_inst_executed_op_global_ld.sum                          # global LD instruction count
smsp__sass_inst_executed_op_global_st.sum                          # global ST count
smsp__sass_inst_executed_op_local_ld.sum                           # local LD (register spill)
smsp__sass_inst_executed_op_local_st.sum                           # local ST (register spill)
smsp__sass_inst_executed_op_shared.sum                             # total shared mem ops
smsp__sass_inst_executed_op_shared_ld.sum
smsp__sass_inst_executed_op_shared_st.sum

l1tex__t_sectors_pipe_lsu_mem_global_op_ld.sum                     # L1 sectors for global LD
l1tex__t_sectors_pipe_lsu_mem_global_op_ld_lookup_hit.sum
l1tex__t_sectors_pipe_lsu_mem_global_op_ld_lookup_miss.sum
l1tex__t_sectors_pipe_lsu_mem_global_op_st.sum                     # L1 sectors for global ST
l1tex__t_requests_pipe_lsu_mem_global_op_ld.sum                    # LD request count
l1tex__t_requests_pipe_lsu_mem_global_op_st.sum                    # ST request count
# sectors/request = sectors.sum / requests.sum (ideal = 4 for 128B coalesced)
smsp__sass_average_data_bytes_per_sector_mem_global_op_st.ratio    # store efficiency (max 32)
```

### Stall reasons — aggregate ratios
```
smsp__average_warps_issue_stalled_long_scoreboard_per_issue_active.ratio
smsp__average_warps_issue_stalled_short_scoreboard_per_issue_active.ratio
smsp__average_warps_issue_stalled_wait_per_issue_active.ratio
smsp__average_warps_issue_stalled_barrier_per_issue_active.ratio
smsp__average_warps_issue_stalled_membar_per_issue_active.ratio
smsp__average_warps_issue_stalled_math_pipe_throttle_per_issue_active.ratio
smsp__average_warps_issue_stalled_mio_throttle_per_issue_active.ratio
smsp__average_warps_issue_stalled_lg_throttle_per_issue_active.ratio
smsp__average_warps_issue_stalled_tex_throttle_per_issue_active.ratio
smsp__average_warps_issue_stalled_not_selected_per_issue_active.ratio
smsp__average_warps_issue_stalled_branch_resolving_per_issue_active.ratio
smsp__average_warps_issue_stalled_dispatch_stall_per_issue_active.ratio
smsp__average_warps_issue_stalled_drain_per_issue_active.ratio
smsp__average_warps_issue_stalled_no_instruction_per_issue_active.ratio
smsp__average_warps_issue_stalled_sleeping_per_issue_active.ratio
smsp__average_warps_issue_stalled_misc_per_issue_active.ratio
smsp__average_warps_issue_stalled_selected_per_issue_active.ratio       # productive (= 1.0)
```

### Stall reasons — per-PC (requires `--set source --section SourceCounters`)
```
smsp__pcsamp_sample_count                                           # total sample count
smsp__pcsamp_warps_issue_stalled_long_scoreboard                    # per-PC counts
smsp__pcsamp_warps_issue_stalled_short_scoreboard
smsp__pcsamp_warps_issue_stalled_wait
smsp__pcsamp_warps_issue_stalled_barrier
smsp__pcsamp_warps_issue_stalled_math_pipe_throttle
smsp__pcsamp_warps_issue_stalled_mio_throttle
smsp__pcsamp_warps_issue_stalled_lg_throttle
smsp__pcsamp_warps_issue_stalled_tex_throttle
smsp__pcsamp_warps_issue_stalled_not_selected
smsp__pcsamp_warps_issue_stalled_dispatch_stall
smsp__pcsamp_warps_issue_stalled_drain
smsp__pcsamp_warps_issue_stalled_no_instructions
smsp__pcsamp_warps_issue_stalled_selected
smsp__pcsamp_warps_issue_stalled_branch_resolving
smsp__pcsamp_warps_issue_stalled_membar
```

Each of these has `num_instances() > 0` with `correlation_ids()` that map to PCs. Use `action.source_info(pc)` to map PCs to `(file, line)`.

### PM sampling (time series)
```
pmsampling:smsp__warps_issue_stalled_long_scoreboard.avg
pmsampling:smsp__warps_issue_stalled_short_scoreboard.avg
pmsampling:smsp__warps_issue_stalled_wait.avg
pmsampling:smsp__warps_issue_stalled_dispatch_stall.avg
pmsampling:smsp__warps_issue_stalled_branch_resolving.avg
pmsampling:smsp__warps_issue_stalled_math_pipe_throttle.avg
pmsampling:smsp__warps_issue_stalled_mio_throttle.avg
pmsampling:smsp__warps_issue_stalled_lg_throttle.avg
pmsampling:smsp__warps_issue_stalled_no_instruction.avg
pmsampling:smsp__warps_issue_stalled_drain.avg
pmsampling:smsp__warps_issue_stalled_sleeping.avg
pmsampling:smsp__warps_issue_stalled_misc.avg
pmsampling:smsp__warps_issue_stalled_barrier.avg
pmsampling:smsp__warps_issue_stalled_tex_throttle.avg
```

Note: some `pmsampling:` metrics (notably `pmsampling:sm__throughput.*` and `pmsampling:dram__throughput.*`) may return empty instance arrays depending on ncu version / driver / GPU pair — always check `m.num_instances() > 0` before using. When SM/DRAM timelines are empty, the stall-reason timelines (`pmsampling:smsp__warps_issue_stalled_*`) usually tell the same story and are more reliably populated.

---

## Discovering metrics for new GPUs

When running on a GPU other than B200:

```bash
# All available metrics for a given chip
ncu --query-metrics --chip gb202        # B200 = GB202 / gb202 in some docs

# Filter by name pattern
ncu --query-metrics --chip gb202 | grep -i pmsampling
ncu --query-metrics --chip gb202 | grep -i issue_stalled

# Valid chip names: gb202 (B200), gh200 (H200 / Hopper), ga102 (Ampere), etc.
```

From Python, you can also enumerate per-report:
```python
all_names = action.metric_names()      # all metrics collected in the task workspacert
```

---
