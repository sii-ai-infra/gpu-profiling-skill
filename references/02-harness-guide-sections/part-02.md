## Choosing representative workloads

If the user's dataset has many workloads, you cannot profile them all. Pick 2-3 workloads that together cover:

1. **Each active dispatch path.** If the kernel's host-side dispatcher picks different template instantiations / grid configs based on input shape, profile one workload per path. Identify the dispatch rules by reading the launcher code, not by guessing.
2. **The largest realistic workload** in the hot-path dispatch — usually the most performance-sensitive.
3. **A worst-case-imbalance workload** if the kernel has a variable-length inner loop (one where different CTAs perform different amounts of work based on the input). Pick an input whose per-CTA work distribution has a high max/min ratio — that's your tail-effect probe.

Example selection approach (for a kernel whose dispatcher picks between two template instantiations by batch size):
- A canonical large-batch workload — exercises the primary dispatch path.
- A small-batch workload — small grid, often reveals SM idleness or under-fill.
- If the large-batch workload has highly uneven per-element work (check the relevant axis in the dataset), that's your tail-effect probe; if every element has the same work, hunt for a separately-imbalanced workload.

### Discovering workload shapes in a flashinfer-trace dataset

When the project uses `flashinfer-bench`, the workloads live in a "flashinfer-trace" dataset with this layout:

```
<dataset_root>/                                 # $FIB_DATASET_PATH
├── definitions/<category>/<definition>.json    # axes (const vs var), input/output shapes, dtypes, reference impl
├── workloads/<category>/<definition>.jsonl     # one line per workload: uuid + concrete axis values + input paths
└── blob/workloads/<category>/<definition>/
    └── <definition>_<uuid>.safetensors         # raw tensors for that workload
```

Each `.jsonl` line looks like:

```json
{
  "definition": "<name>",
  "workload": {
    "uuid": "...",
    "axes": { "<var_axis_1>": <value>, "<var_axis_2>": <value>, ... },
    "inputs": {
      "<tensor_input>": { "type": "safetensors", "path": "./blob/.../<...>.safetensors", "tensor_key": "<tensor_input>" },
      ...
      "<scalar_input>":  { "type": "scalar", "value": <number> }
    }
  }
}
```

Scalars are inline; tensors live in the safetensors blob at the given relative path (relative to the dataset root).

**Helper: [`../scripts/list_flashinfer_workloads.py`](../../scripts/list_flashinfer_workloads.py).**

```bash
export FIB_DATASET_PATH=/abs/path/to/flashinfer-trace

# (1) Inspect the definition: axes (which are const vs var), input/output shapes, dtypes
python3 list_flashinfer_workloads.py --definition <name> --show-definition

# (2) See the shape distribution across all workloads (default mode)
python3 list_flashinfer_workloads.py --definition <name>
#  → prints a histogram keyed by the 'var' axes, so you can see which shapes
#    actually appear in the dataset and how often.

# (3) List all workloads matching a filter — gives UUIDs + absolute safetensors paths
python3 list_flashinfer_workloads.py --definition <name> --list --filter <axis>=<value>

# (4) One representative per unique (axis1, axis2, ...) combination —
#     useful for dispatch coverage
python3 list_flashinfer_workloads.py --definition <name> --unique-axes <axis1>,<axis2>

# (5) Look up a specific UUID — prints axes, scalar inputs, absolute safetensors path
python3 list_flashinfer_workloads.py --definition <name> --uuid <uuid>
```

Use steps (1-2) to understand the shape space, then (3) or (4) to pick a few representative UUIDs. Copy the absolute safetensors path straight into your harness's `--workload` CLI argument, or hardcode it in a small launcher script.

If `FIB_DATASET_PATH` is not set, pass `--dataset /path/to/root` explicitly.

### If the user's dataset is NOT flashinfer-trace

The principles still apply — you need to learn the dataset's layout and locate:

1. A schema / definition (what axes are variable, which are const, what the tensor shapes/dtypes are).
2. A list of concrete workload instances (what values the var axes take).
3. The raw tensor bytes for each instance.

Write a short inspector script equivalent to `list_flashinfer_workloads.py` for that format, drop it under `$PROFILE_RUN_DIR/harness/` if it's one-shot, or generalize it under `scripts/` if you'll reuse it.

---

## Explicit template instantiation

If the kernel is a template, you must force the compiler to emit each variant you'll profile. Without this, instantiations that aren't used by `main()` will be stripped, and ncu's `-k "regex:..."` won't find them.

```cpp
template __global__ void my_kernel<8, 256>(
    const __nv_bfloat16*, const __nv_bfloat16*, /* ... other args ... */,
    float*, float*);

template __global__ void my_kernel<4, 256>(
    const __nv_bfloat16*, const __nv_bfloat16*, /* ... other args ... */,
    float*, float*);
```

The launch site in `main()` picks the right instantiation based on a CLI flag.

---
