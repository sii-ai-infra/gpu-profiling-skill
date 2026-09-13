## Triton Kernels

Triton does not expose CUDA C++ `clock64()` directly, but `tl.inline_asm_elementwise`
can emit inline PTX. The exact constraints can vary by Triton version, so treat
this as a probe pattern to validate in the local environment.

```python
import triton
import triton.language as tl

@triton.jit
def kernel(x, y, timing, BLOCK: tl.constexpr):
    pid = tl.program_id(0)

    t0 = tl.inline_asm_elementwise(
        "mov.u64 $0, %clock64;",
        constraints="=l",
        args=[],
        dtype=tl.uint64,
        is_pure=False,
        pack=1,
    )

    # Region to measure.

    t1 = tl.inline_asm_elementwise(
        "mov.u64 $0, %clock64;",
        constraints="=l",
        args=[],
        dtype=tl.uint64,
        is_pure=False,
        pack=1,
    )

    tl.store(timing + pid, t1 - t0)
```

Use this for:

- Quick region timing in a Triton program.
- Program-ID-level timing histograms.

Avoid this when:

- You need source-level NCU attribution. For Triton, the more robust route is
  often to dump generated PTX/SASS, or rebuild a minimal standalone CUDA
  harness when possible.

---

## NVTX And Profiler Ranges

NVTX is useful for host-side ranges:

```cpp
nvtxRangePushA("decode_step");
my_kernel<<<grid, block, smem, stream>>>(...);
nvtxRangePop();
```

Use this for:

- Marking framework phases.
- Filtering NCU/NSYS to kernels launched inside a host-side range.
- Separating data loading, preprocessing, kernel launch, and postprocessing.

Avoid this for:

- Device-side code regions. NVTX is not a `__device__` range annotation API.

NCU can use NVTX filters at the CLI level; see `ncu --help` for
`--nvtx`, `--nvtx-include`, and `--nvtx-exclude`.

---

## Prefer NCU For Hardware Cause

Internal timestamps identify a slow interval. NCU identifies why it is slow.

Use NCU when the question is:

- Which pipe is underutilized?
- Are tensor cores waiting for data?
- Is the wait on long scoreboard, short scoreboard, mbarrier, warpgroup arrive,
  MIO throttle, or no instruction?
- Is there a tail wave or phase oscillation?
- Which SASS/source line has the stall samples?

Minimum collection:

```bash
ncu --set full \
    --section PmSampling \
    --section PmSampling_WarpStates \
    -k "regex:KERNEL_REGEX" -c 1 \
    -o "$PROFILE_RUN_DIR/reports/full_<tag>" \
    ./harness [args]

ncu --set source \
    --section SourceCounters \
    -k "regex:KERNEL_REGEX" -c 1 \
    -o "$PROFILE_RUN_DIR/reports/source_<tag>" \
    ./harness [args]
```

Then correlate:

| Timestamp finding | NCU evidence to check |
|---|---|
| Long tile-load phase | global/shared load sectors, L2 hit rate, long scoreboard, LSU/L1TEX throughput |
| Long wait after async copy/TMA | mbarrier/wait stalls, TMA pipe activity, PM-sampling oscillation |
| Long wait after WGMMA/HGMMA issue | tensor pipe utilization, warpgroup arrive/wait/dependency stalls, eligible warps |
| Long epilogue | store sectors, local-memory spills, ALU/XU pipe, predicate/divergence |
| Tail CTAs much slower | PM-sampling tail, per-SM active-cycle variance, launch waves, work distribution |

---
