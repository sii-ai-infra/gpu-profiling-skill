## Gotchas

1. **Metric exists in ncu's list but returns `None` from Python**: the metric wasn't *collected* in the task workspacert. Rerun ncu with the right `--section` or `--set`.
2. **Metric value is `0.0`**: either the hardware counter reports zero (e.g., no tensor core activity), or the metric is synthetic and depends on other metrics that weren't collected.
3. **`.avg` vs `.sum` vs `.max`**: each aggregate is a separate metric name. `.avg` is most commonly useful for rates / percentages; `.sum` for counts; `.max` for worst-case analysis.
4. **`pct_of_peak_sustained_elapsed` vs `pct_of_peak_sustained_active`**: `_elapsed` normalizes against total kernel time (including idle SMs); `_active` normalizes against cycles where the SM was actually running. `_elapsed` is more honest for under-utilized kernels.
