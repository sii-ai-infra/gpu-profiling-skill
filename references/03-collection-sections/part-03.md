## GPU frequency locking (for reproducibility)

```bash
# Check current clocks
nvidia-smi -q -d CLOCK

# Lock to boost frequency (sudo required)
sudo nvidia-smi -lgc <boost_clock_mhz>

# Unlock when done
sudo nvidia-smi -rgc
```

For B200 this is usually unnecessary — the GPU boosts to steady-state during profiling because ncu replays the kernel 45+ times. If your results are jittery between runs, lock the clock.

---

## Gotchas

- **Profile run time blows up with `--set full`**: that's normal, each replay is a full kernel execution.
- **`regex:...` doesn't match anything**: check with `cuobjdump --dump-function-names ./harness` and make sure you're looking at the demangled name. Templates produce names like `void my_kernel<(int)8, (int)256>(...)` — the regex needs to match this string.
- **Report file is empty / 0 KB**: profile terminated before the kernel launched. Usually means `-k` regex didn't match, or the harness crashed.
- **PM Sampling returns nothing**: check you used `--section PmSampling` and the GPU isn't a vGPU (vGPU doesn't support PM sampling).
- **"Could not deploy stock section files to $HOME"**: set `HOME` to a writable directory first.
