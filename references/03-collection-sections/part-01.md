# Profile Collection Commands

This document lists the exact `ncu` commands you should run, in what order, and what each flag does.

---

## Prerequisites recap

- `-lineinfo` in the compile flags (see `02-harness-guide.md`).
- `ncu` available on PATH.
- Writable `$HOME` so ncu can cache section files.
- Kernel name known (check with `cuobjdump --dump-function-names your_binary` if unsure).

Quick permission test:
```bash
ncu --section SpeedOfLight -k "regex:YOUR_KERNEL_NAME" -c 1 ./harness [args]
# If you see ERR_NVGPUCTRPERM: need sudo or edit /etc/modprobe.d/ncu.conf (see 09-common-issues.md).
# If you see the SpeedOfLight table and "regex" matched, you're good.
```

---

## Recipe 1: Full overview (first pass)

Collects all standard sections plus PM sampling (time-series data). This is the mandatory first run.

```bash
ncu --set full \
    --section PmSampling \
    --section PmSampling_WarpStates \
    -k "regex:KERNEL_REGEX" \
    -c 1 \
    -o $PROFILE_RUN_DIR/reports/full_<tag> \
    ./harness [args]
```

| Flag | Meaning |
|---|---|
| `--set full` | Run all built-in sections — SOL, Occupancy, Memory, Compute, Scheduler, Launch, etc. |
| `--section PmSampling` | Add performance-monitor time-series data (not included in `full`). Needed to see tail effects. |
| `--section PmSampling_WarpStates` | Time-series of warp stall states. |
| `-k "regex:..."` | Only profile kernels whose demangled name matches. Reduces replay count. |
| `-c 1` | Only profile the first matching kernel launch. Avoids duplicates when the kernel is called in a loop. |
| `-o $PROFILE_RUN_DIR/reports/full_<tag>` | Output path — `.ncu-rep` is appended automatically. |

Replay count: typically 45-50 passes (5-40 seconds of wall time). Slow because each pass reruns the kernel to collect a different metric group.

---

## Recipe 2: Source-level profile (second pass)

Collects per-PC stall sampling data. Requires `-lineinfo` at compile time. Fast (~5 passes).

```bash
ncu --set source \
    --section SourceCounters \
    -k "regex:KERNEL_REGEX" \
    -c 1 \
    -o $PROFILE_RUN_DIR/reports/source_<tag> \
    ./harness [args]
```

Use Recipe 2's output with `extract_stall_hotspots.py` to get per-source-line stall samples.

---

## Recipe 3: Details page (quick rule summary)

No need to collect again — just import an existing `full_<tag>.ncu-rep`:

```bash
ncu --import $PROFILE_RUN_DIR/reports/full_<tag>.ncu-rep --page details > analysis/details_<tag>.txt
```

This produces NCU's human-readable details page, including the built-in rule-engine suggestions. Each rule looks like:

```
OPT   Est. Speedup: <pct>%
      <description of the pattern NCU detected, e.g. "On average, each warp
      spends N cycles stalled waiting for a scoreboard dependency on a L1TEX
      operation. Find the instruction producing the data being waited upon
      to identify the culprit.">
```

**Always read `details_<tag>.txt` first.** The rule engine is shockingly accurate and often points straight at the answer.

---

## Recipe 4: CSV / raw export (scripting)

```bash
# Full metric table as CSV — one row per kernel launch, one column per metric
ncu --import $PROFILE_RUN_DIR/reports/full_<tag>.ncu-rep --page raw --csv > analysis/raw_<tag>.csv

# Source page as text
ncu --import $PROFILE_RUN_DIR/reports/source_<tag>.ncu-rep --page source > analysis/source_<tag>.txt
```

Most of the time you don't need these — the Python API (`04-python-api.md`) is easier. But CSV is handy for quick `grep`/`awk` one-liners.

---
