## Reporting Requirements

When using instrumentation in a profiling report, include:

1. Whether instrumentation was compiled in (`KERNEL_PROFILING`, debug branch,
   extra buffers, extra synchronizations).
2. Which threads wrote timestamps or counters.
3. Timer source: `clock64()` or `%globaltimer`.
4. Output schema: one value per CTA, per warp, per phase, or global aggregate.
5. Expected overhead and how it might perturb scheduling.
6. Uninstrumented NCU run used to validate that the observed bottleneck still
   exists without probes.

Never compare an instrumented kernel's absolute runtime against a production
kernel unless the report explicitly accounts for probe overhead.

---

## References

- CUDA inline PTX assembly: <https://docs.nvidia.com/cuda/inline-ptx-assembly/>
- PTX ISA special registers (`%clock64`, `%globaltimer`):
  <https://docs.nvidia.com/cuda/parallel-thread-execution/>
- Nsight Compute CLI PM sampling, warp sampling, and NVTX filters:
  <https://docs.nvidia.com/nsight-compute/NsightComputeCli/>
- Triton inline assembly:
  <https://triton-lang.org/main/python-api/generated/triton.language.inline_asm_elementwise.html>
