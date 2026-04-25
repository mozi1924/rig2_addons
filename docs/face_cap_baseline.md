# Face Cap Baseline (P0/F0)

## Metadata
- Date: 2026-04-25 17:22:33 CST (UTC+08:00)
- Commit: `cc46e69389556bf28642a91008d875ea3c666606`
- Machine: Apple M4, Darwin 25.4.0 (`arm64`)
- Python: `3.14.4`
- Blender: not found in current PATH (this baseline did not run inside Blender process)
- Native build params (`native_cpp/setup.py`): `-O3`, `-std=c++17`, ABI3 on (`Py_LIMITED_API=0x03090000`, `py_limited_api=True`)

## Benchmark Command

```bash
python3 tests/perf/bench_face_cap_receiver.py \
  --mode both \
  --protocol both \
  --clients 1,4,8 \
  --rounds 2000 \
  --repeat 3 \
  --poll-timeout 30 \
  --port 19500 \
  > docs/perf/face_cap_baseline_raw.json
```

## Result Table (mean over 3 repeats)

| mode | protocol | clients | recv msgs/s | p95 latency (ms) | p99 latency (ms) | dropped packets | error count |
|---|---|---:|---:|---:|---:|---:|---:|
| native | json | 1 | 57078.943649 | 10.913375 | 11.232875 | 1976.333333 | 0 |
| native | json | 4 | 59773.453743 | 14.483430 | 16.557597 | 7913.000000 | 0 |
| native | json | 8 | 60549.843642 | 14.171458 | 14.999639 | 15824.666667 | 0 |
| native | binary | 1 | 121321.225598 | 0.536472 | 0.609778 | 1979.000000 | 0 |
| native | binary | 4 | 130871.664919 | 0.538306 | 0.702528 | 7922.000000 | 0 |
| native | binary | 8 | 125341.408899 | 1.958583 | 2.325167 | 15839.000000 | 0 |
| python_ref | json | 1 | 38712.470369 | 11.870236 | 14.198597 | 1969.666667 | 0 |
| python_ref | json | 4 | 38462.410577 | 85.964555 | 92.330875 | 7927.333333 | 0 |
| python_ref | json | 8 | 40356.599597 | 162.746764 | 198.346264 | 15912.666667 | 0 |

## Notes
- `python_ref + binary` is intentionally skipped (reference path only supports JSON).
- Full raw output: `docs/perf/face_cap_baseline_raw.json`.
- `dropped packets` is expected to be high because receiver uses latest-frame overwrite semantics (`drop_old_packets=true`) during stress tests.
