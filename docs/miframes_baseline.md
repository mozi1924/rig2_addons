# MIFrames Baseline (P0/M0)

## Metadata
- Date: 2026-04-25 18:37:45 CST (UTC+08:00)
- Commit: `0f44672e9fbcafcfa9909d475527e98ead02108f`
- Machine: Apple Silicon `arm64`
- Platform: `macOS-26.4.1-arm64-arm-64bit-Mach-O`
- Python: `3.14.4`
- Native module: `src/native/binaries/darwin-arm64-abi3/rig2_miframes.abi3.so`
- Native build params (`native_cpp/setup.py`): `-O3`, `-std=c++17`, ABI3 on (`Py_LIMITED_API=0x03090000`, `py_limited_api=True`)

## Fixed Fixtures
- `tests/fixtures/miframes/character_cycle_small.miframes` (`240` keyframes)
- `tests/fixtures/miframes/character_cycle_dense.miframes` (`2400` keyframes)
- `tests/fixtures/miframes/prop_motion.miobject` (`1200` keyframes)

## Benchmark Command

```bash
python3 tests/perf/bench_miframes_planner.py \
  --repeat 40 \
  --warmup 10 \
  > docs/perf/miframes_baseline_raw.json
```

## Result Table (mean over 40 repeats)

| fixture | keyframes | mean (ms) | p50 (ms) | p95 (ms) | p99 (ms) |
|---|---:|---:|---:|---:|---:|
| `character_cycle_small.miframes` | 240 | 0.461165 | 0.395583 | 0.910042 | 1.087041 |
| `character_cycle_dense.miframes` | 2400 | 4.553258 | 4.675625 | 5.454250 | 5.994459 |
| `prop_motion.miobject` | 1200 | 3.854544 | 3.287833 | 9.432500 | 10.967667 |

## Summary
- Unweighted mean elapsed: `2.956322 ms`
- Weighted mean elapsed (by keyframe count): `4.079154 ms`
- Max fixture p95 elapsed: `9.432500 ms`

## Notes
- Full raw output: `docs/perf/miframes_baseline_raw.json`.
- This document records the M0 baseline and fixed fixture set used for subsequent M1/M2/M3 comparison.
