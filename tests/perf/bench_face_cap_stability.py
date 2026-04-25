#!/usr/bin/env python3
import argparse
import json
import os
import random
import resource
import threading
import time
from datetime import datetime, timezone

from bench_face_cap_receiver import (
    NativeReceiver,
    build_binary_packet,
    load_native_module,
    send_binary_schema,
    send_ws_frame,
    ws_client_connect,
)


def _safe_round(value, digits=6):
    if value is None:
        return None
    return round(float(value), digits)


def _send_anomaly(sock, protocol):
    kind = random.randint(0, 3)
    if kind == 0:
        send_ws_frame(sock, b"{bad_json", opcode=0x1, masked=True)
        return "bad_json"
    if kind == 1:
        send_ws_frame(sock, os.urandom(7), opcode=0x2, masked=True)
        return "short_binary"
    if kind == 2:
        send_ws_frame(sock, b"[]", opcode=0x1, masked=True)
        return "non_dict_json"
    if protocol == "binary":
        malformed_schema = {
            "type": "schema",
            "format": "r2fmc.bin.v999",
            "blendshapeNames": ["jawOpen", "eyeBlinkLeft"],
        }
        send_ws_frame(sock, json.dumps(malformed_schema, separators=(",", ":")).encode("utf-8"), opcode=0x1, masked=True)
        return "bad_schema"
    send_ws_frame(sock, b"{\"type\":\"noop\"}", opcode=0x1, masked=True)
    return "noop"


def run_anomaly_test(host, port, protocol, clients, rounds, anomaly_every):
    native = load_native_module("rig2_face_cap")
    receiver = NativeReceiver(native)
    receiver.start(host, port)

    sent_valid = 0
    sent_anomaly = 0
    sender_errors = []
    anomaly_breakdown = {}
    lock = threading.Lock()

    def worker(cid):
        nonlocal sent_valid, sent_anomaly
        try:
            sock = ws_client_connect(host, port, protocol)
            if protocol == "binary":
                send_binary_schema(sock, ["jawOpen", "eyeBlinkLeft"])

            for i in range(rounds):
                if anomaly_every > 0 and i % anomaly_every == 0:
                    kind = _send_anomaly(sock, protocol)
                    with lock:
                        sent_anomaly += 1
                        anomaly_breakdown[kind] = anomaly_breakdown.get(kind, 0) + 1

                sent_id = cid * 1_000_000_000 + i
                jaw_open = (i % 101) / 100.0
                eye_blink_left = ((i * 7) % 101) / 100.0
                if protocol == "json":
                    payload = {
                        "type": "blendshapes",
                        "faces": [{"blendshapes": {"jawOpen": jaw_open, "eyeBlinkLeft": eye_blink_left}}],
                        "faceCount": 1,
                        "sentAt": str(sent_id),
                    }
                    send_ws_frame(sock, json.dumps(payload, separators=(",", ":")).encode("utf-8"), opcode=0x1, masked=True)
                else:
                    send_ws_frame(
                        sock,
                        build_binary_packet(sent_id=sent_id, jaw_open=jaw_open, eye_blink_left=eye_blink_left),
                        opcode=0x2,
                        masked=True,
                    )

                with lock:
                    sent_valid += 1

            try:
                send_ws_frame(sock, b"", opcode=0x8, masked=True)
            except Exception:
                pass
            sock.close()
        except Exception as exc:
            with lock:
                sender_errors.append(f"client#{cid}: {exc}")

    started = time.perf_counter()
    threads = [threading.Thread(target=worker, args=(cid,), daemon=True) for cid in range(clients)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30.0)

    time.sleep(1.0)
    elapsed_s = max(1e-6, time.perf_counter() - started)
    stats = receiver.stats() or {}
    receiver.stop()

    return {
        "protocol": protocol,
        "clients": clients,
        "rounds": rounds,
        "anomaly_every": anomaly_every,
        "elapsed_s": _safe_round(elapsed_s),
        "sent_valid": sent_valid,
        "sent_anomaly": sent_anomaly,
        "anomaly_breakdown": anomaly_breakdown,
        "receiver_packet_count": int(stats.get("packet_count", 0) or 0),
        "dropped_packet_count": int(stats.get("dropped_packet_count", 0) or 0),
        "last_error": str(stats.get("last_error", "") or ""),
        "status_message": str(stats.get("status_message", "") or ""),
        "sender_errors": sender_errors,
    }


def run_soak_test(host, port, protocol, clients, duration_s, send_interval_s):
    native = load_native_module("rig2_face_cap")
    receiver = NativeReceiver(native)
    receiver.start(host, port)

    stop_event = threading.Event()
    sent_valid = 0
    sender_errors = []
    lock = threading.Lock()

    rss_start_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    def worker(cid):
        nonlocal sent_valid
        try:
            sock = ws_client_connect(host, port, protocol)
            if protocol == "binary":
                send_binary_schema(sock, ["jawOpen", "eyeBlinkLeft"])

            seq = 0
            while not stop_event.is_set():
                sent_id = cid * 1_000_000_000 + seq
                jaw_open = (seq % 101) / 100.0
                eye_blink_left = ((seq * 11) % 101) / 100.0
                if protocol == "json":
                    payload = {
                        "type": "blendshapes",
                        "faces": [{"blendshapes": {"jawOpen": jaw_open, "eyeBlinkLeft": eye_blink_left}}],
                        "faceCount": 1,
                        "sentAt": str(sent_id),
                    }
                    send_ws_frame(sock, json.dumps(payload, separators=(",", ":")).encode("utf-8"), opcode=0x1, masked=True)
                else:
                    send_ws_frame(
                        sock,
                        build_binary_packet(sent_id=sent_id, jaw_open=jaw_open, eye_blink_left=eye_blink_left),
                        opcode=0x2,
                        masked=True,
                    )
                with lock:
                    sent_valid += 1
                seq += 1
                if send_interval_s > 0:
                    time.sleep(send_interval_s)

            try:
                send_ws_frame(sock, b"", opcode=0x8, masked=True)
            except Exception:
                pass
            sock.close()
        except Exception as exc:
            with lock:
                sender_errors.append(f"client#{cid}: {exc}")

    started = time.perf_counter()
    threads = [threading.Thread(target=worker, args=(cid,), daemon=True) for cid in range(clients)]
    for t in threads:
        t.start()

    end_time = started + duration_s
    while time.perf_counter() < end_time:
        _ = receiver.poll()
        time.sleep(0.001)

    stop_event.set()
    for t in threads:
        t.join(timeout=10.0)

    elapsed_s = max(1e-6, time.perf_counter() - started)
    stats = receiver.stats() or {}
    receiver.stop()

    rss_end_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    return {
        "protocol": protocol,
        "clients": clients,
        "duration_s": int(duration_s),
        "send_interval_s": send_interval_s,
        "elapsed_s": _safe_round(elapsed_s),
        "sent_valid": sent_valid,
        "receiver_packet_count": int(stats.get("packet_count", 0) or 0),
        "dropped_packet_count": int(stats.get("dropped_packet_count", 0) or 0),
        "recv_msgs_per_s": _safe_round((int(stats.get("packet_count", 0) or 0)) / elapsed_s),
        "last_error": str(stats.get("last_error", "") or ""),
        "status_message": str(stats.get("status_message", "") or ""),
        "sender_error_count": len(sender_errors),
        "rss_start_kb": int(rss_start_kb),
        "rss_end_kb": int(rss_end_kb),
        "rss_growth_kb": int(rss_end_kb - rss_start_kb),
    }


def main():
    parser = argparse.ArgumentParser(description="F3 stability benchmark for face_cap native receiver")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=19900)
    parser.add_argument("--protocol", choices=["json", "binary", "both"], default="both")
    parser.add_argument("--anomaly-clients", type=int, default=4)
    parser.add_argument("--anomaly-rounds", type=int, default=2000)
    parser.add_argument("--anomaly-every", type=int, default=10)
    parser.add_argument("--soak-clients", type=int, default=4)
    parser.add_argument("--soak-minutes", type=int, default=30)
    parser.add_argument("--soak-send-interval", type=float, default=0.001)
    args = parser.parse_args()

    protocols = ["json", "binary"] if args.protocol == "both" else [args.protocol]
    started_utc = datetime.now(timezone.utc)

    anomaly_results = []
    soak_results = []

    for idx, protocol in enumerate(protocols):
        anomaly_results.append(
            run_anomaly_test(
                host=args.host,
                port=args.port + idx * 100,
                protocol=protocol,
                clients=args.anomaly_clients,
                rounds=args.anomaly_rounds,
                anomaly_every=args.anomaly_every,
            )
        )

    for idx, protocol in enumerate(protocols):
        soak_results.append(
            run_soak_test(
                host=args.host,
                port=args.port + 1000 + idx * 100,
                protocol=protocol,
                clients=args.soak_clients,
                duration_s=max(1, args.soak_minutes * 60),
                send_interval_s=max(0.0, args.soak_send_interval),
            )
        )

    output = {
        "schema_version": 1,
        "benchmark": "face_cap_stability",
        "started_at_utc": started_utc.isoformat(),
        "config": {
            "protocol": args.protocol,
            "anomaly_clients": args.anomaly_clients,
            "anomaly_rounds": args.anomaly_rounds,
            "anomaly_every": args.anomaly_every,
            "soak_clients": args.soak_clients,
            "soak_minutes": args.soak_minutes,
            "soak_send_interval": args.soak_send_interval,
        },
        "anomaly_results": anomaly_results,
        "soak_results": soak_results,
    }

    print(json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
