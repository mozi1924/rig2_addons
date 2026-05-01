# Face Cap After Report (F3 + Pure Native)

## Metadata
- Date: 2026-04-25
- Commit: `cc46e69389556bf28642a91008d875ea3c666606` (workspace HEAD during report)
- Machine: Apple M4 / Darwin 25.4.0 (`arm64`)
- Python: `3.14.4`
- Blender: not found in PATH (tests executed outside Blender process)
- Native build params: `-O3`, `-std=c++17`, ABI3 (`Py_LIMITED_API=0x03090000`)

## Change Scope
- Fixed native receiver crash risk in websocket accept path (`compute_websocket_accept` GIL/lifetime issue).
- Completed F3 test harness:
  - `tests/perf/bench_face_cap_stability.py` for anomaly injection and long soak.
- Removed legacy Python websocket receiver implementation from runtime path:
  - `src/modules/face_cap/runtime.py` now uses native receiver only (control + poll + apply).

## F3 Command

```bash
python3 tests/perf/bench_face_cap_stability.py \
  --protocol binary \
  --anomaly-clients 4 \
  --anomaly-rounds 2000 \
  --anomaly-every 10 \
  --soak-clients 4 \
  --soak-minutes 30 \
  --soak-send-interval 0.001 \
  --port 20100 \
  > docs/perf/face_cap_after_raw.json
```

## F3 Results

### 1) 异常帧注入（binary）
- valid frames sent: `8000`
- anomaly frames sent: `800`
- anomaly mix:
  - `non_dict_json`: 217
  - `bad_json`: 183
  - `short_binary`: 189
  - `bad_schema`: 211
- receiver packet_count: `8000`
- dropped_packet_count: `7999` (latest-frame overwrite semantics)
- sender errors: none
- native last_error: empty

### 2) 长稳 30 分钟（binary）
- duration: `1800s` (实际 `1800.001233s`)
- sent_valid: `1377821`
- receiver_packet_count: `1377821`
- recv msgs/s: `765.455587`
- dropped_packet_count: `9110`
- native last_error: empty
- RSS growth: `0 KB` (ru_maxrss start/end equal)
- sender_error_count: `3` (发生在停机窗口，不影响 native receiver 端稳定运行)

## Baseline vs After (native matrix)

After command:

```bash
python3 tests/perf/bench_face_cap_receiver.py \
  --mode native \
  --protocol both \
  --clients 1,4,8 \
  --rounds 2000 \
  --repeat 3 \
  --poll-timeout 30 \
  --port 20500 \
  > docs/perf/face_cap_after_matrix_raw.json
```

| protocol | clients | baseline recv msgs/s | after recv msgs/s | baseline p99 (ms) | after p99 (ms) |
|---|---:|---:|---:|---:|---:|
| binary | 1 | 121321.225598 | 121907.823655 | 0.609778 | 0.503375 |
| binary | 4 | 130871.664919 | 120174.158601 | 0.702528 | 0.931403 |
| binary | 8 | 125341.408899 | 118730.095702 | 2.325167 | 1.287778 |
| json | 1 | 57078.943649 | 56437.306830 | 11.232875 | 11.686861 |
| json | 4 | 59773.453743 | 57709.047915 | 16.557597 | 15.567319 |
| json | 8 | 60549.843642 | 59465.214204 | 14.999639 | 15.422264 |

## Artifacts
- baseline raw: `docs/perf/face_cap_baseline_raw.json`
- F3 raw: `docs/perf/face_cap_after_raw.json`
- after matrix raw: `docs/perf/face_cap_after_matrix_raw.json`
