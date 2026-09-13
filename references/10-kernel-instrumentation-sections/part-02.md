### `%globaltimer`

When cross-SM timestamp comparability matters more than cycle-level overhead,
read `%globaltimer` via inline PTX.

```cpp
__device__ __forceinline__ unsigned long long read_globaltimer() {
    unsigned long long t;
    asm volatile("mov.u64 %0, %%globaltimer;" : "=l"(t));
    return t;
}
```

Use this for:

- Coarse event ordering across CTAs/SMs.
- Debugging load imbalance or persistent-kernel work-queue timing.

Avoid this when:

- You need a stable public semantic across GPU generations. The PTX ISA
  documents `%globaltimer` as target-specific and intended for NVIDIA tools.

---

## Instrumenting Async Pipelines

For `cp.async`, TMA, WGMMA/HGMMA, and Blackwell `tcgen05` pipelines, measure
phase boundaries, not just one large region.

Typical phase labels:

```text
load_issue_start
load_commit
load_wait_done
mma_issue_start
mma_commit
mma_wait_done
epilogue_start
store_done
```

For WGMMA-style code:

```cpp
#if defined(KERNEL_PROFILING)
if (threadIdx.x == 0) stamps[blockIdx.x * 4 + 0] = clock64();
#endif

// wgmma.mma_async / cute::gemm tiled mma issue

#if defined(KERNEL_PROFILING)
if (threadIdx.x == 0) stamps[blockIdx.x * 4 + 1] = clock64();
#endif

// wgmma.commit_group
// independent work, if any
// wgmma.wait_group

#if defined(KERNEL_PROFILING)
if (threadIdx.x == 0) stamps[blockIdx.x * 4 + 2] = clock64();
#endif
```

Interpretation:

- `issue` interval: front-end / instruction issue cost of the async operation.
- `wait` interval: exposed latency after overlap opportunities.
- High wait time plus NCU `mbarrier`, `wait`, `warpgroup_arrive`, `long_scoreboard`,
  or tensor-pipe oscillation is evidence of a pipeline bubble.

Use this for:

- Checking whether prefetch depth is enough.
- Comparing 2-stage vs 3-stage vs 4-stage pipelines.
- Verifying that producer/consumer or warp-specialized phases overlap.

Avoid this when:

- The timestamp store itself disrupts register allocation or scheduling. Always
  compare an uninstrumented build after forming the hypothesis.

---

## Phase Counters

Sometimes the right probe is a count, not a timestamp.

```cpp
struct KernelDebugCounters {
    unsigned long long branch_a;
    unsigned long long branch_b;
    unsigned long long loop_iters;
};

__device__ __forceinline__ void debug_add(unsigned long long* p,
                                          unsigned long long v) {
#if defined(KERNEL_PROFILING)
    atomicAdd(p, v);
#endif
}
```

Use this for:

- Data-dependent branches.
- Loop trip count distributions.
- Work stealing or persistent-kernel queue behavior.
- Verifying that a supposedly rare slow path is actually rare.

Avoid atomics in the hot inner loop. Prefer one write per CTA or one write per
warp to a preallocated debug buffer, then reduce on the host.

---
