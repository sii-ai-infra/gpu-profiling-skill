## Sanity check before profiling

Always run the harness once without ncu to confirm it launches correctly:

```bash
./harness --workload /path/to/workload.safetensors
# expected stderr (exact text depends on the harness you wrote):
# [harness] loaded workload: <axis1>=... <axis2>=...
# [harness] grid=(...) block=(...) launching <variant>...
# [harness] done.
```

If it crashes or hangs, fix that *before* adding ncu to the mix — ncu errors are far less descriptive than plain CUDA runtime errors.

If feasible, also spot-check correctness with `cuda-memcheck` or a golden-output test — but not inside the profiling harness itself.

---

## When NOT to harness

Sometimes the kernel's perf genuinely depends on surrounding code — e.g., the kernel reuses a specific L2 state set up by a prior kernel, or the kernel's launch configuration depends on a runtime dispatch step. In that case profile through the original binary (even if it's slower to iterate) and make sure the build system has `-lineinfo`. Check the nvcc invocation with `ninja -v` or `make V=1`.

Alternatively, you can build a harness that runs the *prior* kernel too, to reproduce the right L2 state. But this is rare — most kernels are essentially independent of prior state once a warmup pass has happened.
