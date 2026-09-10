# Harness Guide

A **profiling harness** is a small standalone CUDA executable whose sole purpose is to launch the kernel you want to profile, with realistic inputs, using compile flags that ncu can consume (specifically `-lineinfo`).

You should almost always build a harness when profiling a kernel that lives inside:

- **TVM-FFI / FlashInfer solutions** — compiled via `tvm_ffi.cpp.build`, hard to add `-lineinfo`.
- **PyTorch inline-compiled CUDA** — compiled via `torch.utils.cpp_extension.load`, same problem.
- **Triton kernels** — Triton's JIT makes it hard to pin a specific compiled artifact.
- **CUTLASS JIT** — layered build system.
- **A larger binary** where the kernel of interest is buried under initialization, data loading, or networking code that makes each profile run take minutes.

You can skip the harness if the kernel already builds with `-lineinfo` *and* iterating on the full binary is fast enough.

---

## What a good harness contains

1. The kernel (verbatim copy of the device code + any `__device__` helpers it calls).
2. Explicit template instantiations for every template-parameter combination you plan to profile (e.g. `<TILE_M, TILE_N>`, `<VEC_WIDTH, BLOCK_SIZE>`, whatever the kernel is parameterized on).
3. Optional input loading — from a binary file, safetensors, or synthetic.
4. A minimal `main()` that parses CLI args, allocates GPU memory, launches the kernel, synchronizes, and exits.

Things that should NOT be in the harness:

- Framework dependencies (torch, TVM, pybind11) — they slow the build and create noise in the profile.
- Multi-kernel pipelines — profile each kernel separately unless measuring kernel-to-kernel interactions.
- Repeated warmup / timing loops — ncu replays automatically, so run the kernel exactly once (with `-c 1`).
- Correctness checks — verify correctness separately, don't couple it to profiling.

---

## Template

A complete reusable template lives at [`../scripts/harness_template.cu`](../../scripts/harness_template.cu). Customize these sections:

1. **Replace `KERNEL_INCLUDE_GOES_HERE`** with `#include` or paste the kernel source.
2. **Add explicit instantiations** for every template parameter combination you want to profile.
3. **Define the input shape parameters** (grid/block sizes, tensor shapes, any knobs).
4. **Fill in `alloc_and_fill()`** to allocate/initialize inputs correctly for your kernel.
5. **Fill in `launch_kernel()`** to do the actual kernel launch with the right arguments.

Compile with:
```bash
nvcc -O2 -std=c++17 -lineinfo \
     -gencode=arch=compute_100,code=sm_100 \
     harness.cu -o harness
```

Replace `compute_100,code=sm_100` with your target SM version (check `nvidia-smi --query-gpu=compute_cap --format=csv`).

---

## Real data vs synthetic data

There are three levels of fidelity for harness inputs:

### Level 1: Arbitrary synthetic

`float* x = cudaMalloc(...)` without initialization.

**Use when:** you only care about shape-dependent perf and the kernel has no data-dependent branches (no `if (x > threshold)` paths, no early-exit, no branch-on-NaN).

**Avoid when:** you're not sure, or the user asks for "real" profiling. Uninitialized GPU memory can contain garbage that triggers NaN paths.

### Level 2: Random-but-reasonable synthetic (shape-matched)

`std::uniform_real_distribution` with sensible ranges (e.g., weights in `[-0.5, 0.5]`, probabilities in `[0, 1]`). Set the *exact* shape (all variable axes of the workload) to match a specific real instance from the dataset.

**Use when:** the kernel has no data-dependent branches that materially affect perf, but you want stable inputs. This is the default for most perf profiling.

Example pattern:
```cpp
fill_bf16_random(h_input_main, 0xA0A0ULL, 0.5f);   // main activations in [-0.5, 0.5]
fill_bf16_random(h_input_small, 0xD0D0ULL, 0.25f); // smaller-magnitude side input
fill_f32_random(h_params, 0x22222ULL, 1.0f);       // parameters — any range that avoids NaN/Inf
for (auto& x : h_params) x = -1.0f - std::fabs(x); // squash into a specific sign/range if the kernel requires it
```

### Level 3: Actual dataset tensors (real safetensors)

Load the exact BF16/F32 bytes from a `.safetensors` file shipped with the workload.

**Use when:**
- The kernel has branches that might depend on input values (e.g., an early-exit on a magnitude threshold, or a special-case path for denormals / large values).
- The user explicitly asks to profile with real data ("必须 load real workload").
- You're comparing against a reference implementation's output for correctness.

A header-only safetensors reader (no external deps) lives at [`../scripts/safetensors_loader.h`](../../scripts/safetensors_loader.h). It parses the 8-byte header length + JSON header + raw tensor bytes — everything a safetensors file ships.

Example:
```cpp
#include "safetensors_loader.h"

SafetensorsFile st = SafetensorsFile::load("/path/to/workload.safetensors");
const uint8_t* input_bytes = st.tensor_bytes("<input_tensor_name>");
std::memcpy(h_input.data(), input_bytes, n_elems * sizeof(<dtype>));

// Shapes are parsed from the header — read what the definition says is variable:
int axis_0 = (int)st.entry("<input_tensor_name>").shape[0];
int axis_1 = (int)st.entry("<other_tensor_name>").shape[0] - 1;  // etc.
```

This is free relative to compilation time and removes all doubt about data-dependent effects.

---
