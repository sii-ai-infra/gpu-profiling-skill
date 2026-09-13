# Kernel Internal Instrumentation

Use this document when the user asks whether a CUDA / Triton / CuTe / CUTLASS
kernel can measure a specific code region, pipeline phase, or source interval
from inside the kernel.

The short answer:

- **Region timing:** yes, with device-side timestamps such as `clock64()` or
  inline PTX reads of `%globaltimer`.
- **Region-level hardware counters:** usually no. Nsight Compute counters are
  collected by the profiler, not by normal device code. Use NCU SourceCounters,
  PM sampling, or split the code into separately profiled kernels/phases.

Instrumentation is a probe. Keep it behind a compile-time flag and remove it
from final performance measurements unless the instrumentation overhead is the
thing being studied.

Minimal copy-paste snippets live at
[`../scripts/instrumentation_snippet.cu`](../../scripts/instrumentation_snippet.cu).
Use them with a harness based on
[`../scripts/harness_template.cu`](../../scripts/harness_template.cu).

---

## Method Selection

| Method | Suitable when | Avoid when | What it tells you |
|---|---|---|---|
| `clock64()` interval timing | Timing a region within one thread, warp, or CTA on one SM | Comparing absolute times across SMs, or measuring very short regions where the timer overhead dominates | Cycle delta for the instrumented thread/CTA path |
| `%globaltimer` inline PTX | You need a device-side timer closer to global nanoseconds across SMs | Long-term portable code; PTX documents it as target-specific and intended for NVIDIA tools | Approximate global timestamp deltas |
| Per-CTA / per-warp timing buffer | You need a distribution: tail CTAs, imbalance, phase duration variance | Every thread writing timestamps; that will destroy the workload | Which CTAs/warps are slow and where phase variance appears |
| Phase markers/counters | You need to count branch path frequency, loop trip counts, queue depth, retry counts | Hot inner loops where atomics or global stores perturb scheduling | Control-flow and workload-shape evidence |
| NCU SourceCounters + PM sampling | You need stall reasons, pipe utilization, source/SASS hotspots, or bubbles | Kernels too short for sampling, missing `-lineinfo`, unsupported PM sampling | Hardware-backed attribution without editing kernel logic |
| Split-kernel / differential profiling | A region boundary is clean and can be separated without changing semantics too much | Strong producer/consumer overlap or cache-state dependence makes the split unrealistic | Approximate region cost by A/B timing and NCU comparisons |
| Host-side NVTX ranges | You need to mark launches, high-level phases, or framework regions in Nsight Systems/NCU filtering | Annotating inside `__device__` code; NVTX is not a device-code range API | Which host region launched which kernels |
| Binary instrumentation such as NVBit | Research/debug: instruction coverage, dynamic instruction tracing, special probes | Normal optimization loops; overhead and complexity are high | Instruction-level dynamic traces or custom counters |

---

## CUDA / CuTe / CUTLASS: Timing A Code Region

For CUDA C++ kernels, including CuTe/CUTLASS kernels where you can edit device
code, use `clock64()` for low-friction cycle timing.

```cpp
__device__ __forceinline__ unsigned long long read_clock64() {
    return clock64();
}

template <typename T>
__global__ void kernel_with_probe(const T* x, T* y, unsigned long long* timing) {
#if defined(KERNEL_PROFILING)
    unsigned long long t0 = 0;
    if (threadIdx.x == 0) t0 = read_clock64();
#endif

    // Region to measure.
    // For example: load tile, issue MMA group, wait, epilogue, or store.

#if defined(KERNEL_PROFILING)
    if (threadIdx.x == 0) {
        unsigned long long t1 = read_clock64();
        timing[blockIdx.x] = t1 - t0;
    }
#endif
}
```

Use this for:

- A quick per-CTA timing histogram.
- Comparing two versions of the same code region.
- Detecting tail CTAs or variable loop trip counts.

Do not use this alone to claim root cause. Pair it with NCU metrics. A slow
region could be slow due to memory dependencies, barriers, tensor pipe waits, or
scheduler starvation; the timestamp only says "how long", not "why".

### CTA-Level Region Timing

If the measured region should include all threads in a CTA, place synchronization
around the region. This changes behavior, so use it only for probes.

```cpp
#if defined(KERNEL_PROFILING)
__syncthreads();
unsigned long long t0 = 0;
if (threadIdx.x == 0) t0 = clock64();
__syncthreads();
#endif

// CTA-wide measured region.

#if defined(KERNEL_PROFILING)
__syncthreads();
if (threadIdx.x == 0) {
    unsigned long long t1 = clock64();
    timing[blockIdx.x] = t1 - t0;
}
#endif
```

Use this for:

- A phase where all threads participate, such as tile load, shared-memory
  transpose, CTA-level reduction, or epilogue store.

Avoid this when:

- The original code deliberately overlaps work across warps or uses warp
  specialization. Extra `__syncthreads()` can remove the very overlap you are
  trying to measure.
