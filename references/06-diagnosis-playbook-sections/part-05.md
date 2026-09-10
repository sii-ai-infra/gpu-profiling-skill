## Ranking template for the final report


**Rank in absolute time, not in percentages.** Every `Est. Speedup: X%` NCU prints
is a fraction *of this kernel*. Multiply it by `gpu__time_duration.sum` before
comparing patterns across kernels -- a 60% win on a 3 us kernel loses to a 5% win
on a 900 us one, and the percentage view hides that completely.

When you hand back an optimization plan, rank by `(expected speedup) × (effort ratio)`. NCU's `Est. Speedup` is your best estimator.

```
Priority 1: <pattern> — <concrete fix>
  Evidence: <metric value(s)>
  NCU Est. Speedup: X%
  Effort: <low / medium / high>
  Why now: <reason this is the highest-leverage fix>

Priority 2: ...
```

A good rule of thumb: at most 3-5 priorities in the plan. More than that dilutes the signal, and priorities > 5 usually contribute < 5% speedup each.
