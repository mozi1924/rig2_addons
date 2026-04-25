#!/usr/bin/env python3
import argparse
import importlib.machinery
import importlib.util
import json
import os
import platform
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC = os.path.join(ROOT, "src")
FIXTURE_DIR = os.path.join(ROOT, "tests", "fixtures", "miframes")
DEFAULT_FIXTURES = (
    os.path.join(FIXTURE_DIR, "character_cycle_small.miframes"),
    os.path.join(FIXTURE_DIR, "character_cycle_dense.miframes"),
    os.path.join(FIXTURE_DIR, "prop_motion.miobject"),
)


def arch_tag() -> str:
    machine = (platform.machine() or "").strip().lower()
    if machine in {"x86_64", "amd64", "x64"}:
        return "x86_64"
    if machine in {"arm64", "aarch64"}:
        return "arm64"
    return machine or "unknown"


NATIVE_BIN_CANDIDATES = (
    os.path.join(SRC, "native", "binaries", f"{sys.platform}-{arch_tag()}-abi3"),
    os.path.join(SRC, "native", "binaries", f"{sys.platform}-abi3"),
    os.path.join(SRC, "native", "binaries", f"{sys.platform}-{arch_tag()}-{sys.version_info.major}{sys.version_info.minor}"),
    os.path.join(SRC, "native", "binaries", f"{sys.platform}-{sys.version_info.major}{sys.version_info.minor}"),
)


def load_native_module(module_name: str):
    suffixes = getattr(importlib.machinery, "EXTENSION_SUFFIXES", None) or [".so", ".pyd", ".dylib"]
    for base_dir in NATIVE_BIN_CANDIDATES:
        for suffix in suffixes:
            module_path = os.path.join(base_dir, module_name + suffix)
            if not os.path.exists(module_path):
                continue
            spec = importlib.util.spec_from_file_location(module_name, module_path)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module, module_path
    raise FileNotFoundError(f"Native module {module_name} not found under {NATIVE_BIN_CANDIDATES}")


def percentile(values, p):
    if not values:
        return None
    ordered = sorted(values)
    idx = int(round((len(ordered) - 1) * p))
    return ordered[idx]


def _safe_round(value, digits=6):
    if value is None:
        return None
    return round(float(value), digits)


def _mean(values):
    if not values:
        return None
    return sum(values) / len(values)


def _stddev(values):
    if len(values) <= 1:
        return 0.0 if values else None
    return statistics.pstdev(values)


def git_commit() -> str:
    try:
        out = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        return out
    except Exception:
        return "unknown"


def read_fixture(path: str):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"fixture is not an object: {path}")
    keyframes = data.get("keyframes")
    if not isinstance(keyframes, list):
        raise ValueError(f"fixture missing keyframes[]: {path}")
    return data, len(keyframes)


def run_fixture(native, fixture_path, config, start_frame, fps_scale, warmup, repeat):
    data, keyframe_count = read_fixture(fixture_path)

    for _ in range(max(0, warmup)):
        native.plan_miframes_keyframe_ops(data, config, start_frame, fps_scale)

    runs = []
    operation_counts = []
    transition_bucket_counts = []
    for _ in range(max(1, repeat)):
        started_ns = time.perf_counter_ns()
        plan = native.plan_miframes_keyframe_ops(data, config, start_frame, fps_scale)
        elapsed_ms = (time.perf_counter_ns() - started_ns) / 1_000_000.0
        runs.append(elapsed_ms)

        operations = plan.get("operations", []) if isinstance(plan, dict) else []
        transitions = plan.get("transitions", {}) if isinstance(plan, dict) else {}
        operation_counts.append(len(operations) if isinstance(operations, list) else 0)
        transition_bucket_counts.append(len(transitions) if isinstance(transitions, dict) else 0)

    stats = {
        "fixture": os.path.relpath(fixture_path, ROOT),
        "keyframe_count": keyframe_count,
        "repeat": max(1, repeat),
        "warmup": max(0, warmup),
        "elapsed_ms": [_safe_round(v) for v in runs],
        "elapsed_ms_mean": _safe_round(_mean(runs)),
        "elapsed_ms_stddev": _safe_round(_stddev(runs)),
        "elapsed_ms_p50": _safe_round(percentile(runs, 0.50)),
        "elapsed_ms_p95": _safe_round(percentile(runs, 0.95)),
        "elapsed_ms_p99": _safe_round(percentile(runs, 0.99)),
        "ops_per_call_mean": _safe_round(_mean(operation_counts)),
        "transition_buckets_mean": _safe_round(_mean(transition_bucket_counts)),
    }
    return stats


def parse_args():
    parser = argparse.ArgumentParser(description="Benchmark rig2_miframes.plan_miframes_keyframe_ops")
    parser.add_argument("--fixtures", default=",".join(DEFAULT_FIXTURES), help="Comma-separated fixture paths")
    parser.add_argument("--model", default="steve", help="Model key for get_model_config")
    parser.add_argument("--start-frame", type=float, default=1.0)
    parser.add_argument("--fps-scale", type=float, default=1.0)
    parser.add_argument("--warmup", type=int, default=8)
    parser.add_argument("--repeat", type=int, default=30)
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    native, module_path = load_native_module("rig2_miframes")
    config = native.get_model_config(args.model)
    if not isinstance(config, dict):
        raise RuntimeError(f"get_model_config({args.model!r}) returned invalid config")

    fixture_paths = [p.strip() for p in args.fixtures.split(",") if p.strip()]
    if not fixture_paths:
        raise RuntimeError("no fixtures provided")

    per_fixture = []
    aggregate_means = []
    aggregate_weighted_numerator = 0.0
    aggregate_weighted_denominator = 0

    for path in fixture_paths:
        abs_path = path if os.path.isabs(path) else os.path.join(ROOT, path)
        result = run_fixture(
            native=native,
            fixture_path=abs_path,
            config=config,
            start_frame=args.start_frame,
            fps_scale=args.fps_scale,
            warmup=args.warmup,
            repeat=args.repeat,
        )
        per_fixture.append(result)
        mean_ms = float(result["elapsed_ms_mean"])
        aggregate_means.append(mean_ms)
        aggregate_weighted_numerator += mean_ms * int(result["keyframe_count"])
        aggregate_weighted_denominator += int(result["keyframe_count"])

    output = {
        "metadata": {
            "date_utc": datetime.now(timezone.utc).isoformat(),
            "commit": git_commit(),
            "machine": platform.machine(),
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "module_path": module_path,
            "api_version": getattr(native, "RIG2_MIFRAMES_API_VERSION", None),
            "args": {
                "model": args.model,
                "start_frame": args.start_frame,
                "fps_scale": args.fps_scale,
                "warmup": args.warmup,
                "repeat": args.repeat,
            },
        },
        "fixtures": per_fixture,
        "summary": {
            "fixture_count": len(per_fixture),
            "mean_elapsed_ms_unweighted": _safe_round(_mean(aggregate_means)),
            "mean_elapsed_ms_weighted_by_keyframes": _safe_round(
                aggregate_weighted_numerator / max(1, aggregate_weighted_denominator)
            ),
            "max_elapsed_ms_p95": _safe_round(max(float(r["elapsed_ms_p95"]) for r in per_fixture)),
        },
    }

    print(json.dumps(output, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
