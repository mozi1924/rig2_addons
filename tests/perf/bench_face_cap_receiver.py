#!/usr/bin/env python3
import argparse
import base64
import hashlib
import importlib.machinery
import importlib.util
import json
import math
import os
import platform
import random
import socket
import statistics
import struct
import sys
import threading
import time
from datetime import datetime, timezone


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC = os.path.join(ROOT, "src")
WS_MAGIC = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
JSON_SUBPROTOCOL = "r2fmc.json.v1"
BINARY_SUBPROTOCOL = "r2fmc.bin.v1"
DEFAULT_SCHEMA_NAMES = ["jawOpen", "eyeBlinkLeft"]


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
            return module
    raise FileNotFoundError(f"Native module {module_name} not found under {NATIVE_BIN_CANDIDATES}")


def recv_exact(sock: socket.socket, size: int) -> bytes:
    buf = bytearray()
    while len(buf) < size:
        chunk = sock.recv(size - len(buf))
        if not chunk:
            raise ConnectionError("socket closed")
        buf.extend(chunk)
    return bytes(buf)


def read_ws_frame(sock: socket.socket):
    header = recv_exact(sock, 2)
    opcode = header[0] & 0x0F
    masked = (header[1] & 0x80) != 0
    payload_len = header[1] & 0x7F
    if payload_len == 126:
        payload_len = struct.unpack("!H", recv_exact(sock, 2))[0]
    elif payload_len == 127:
        payload_len = struct.unpack("!Q", recv_exact(sock, 8))[0]
    mask = recv_exact(sock, 4) if masked else b""
    payload = recv_exact(sock, payload_len) if payload_len else b""
    if masked:
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    return opcode, payload


def send_ws_frame(sock: socket.socket, payload: bytes, opcode: int, masked: bool):
    header = bytearray()
    header.append(0x80 | (opcode & 0x0F))
    length = len(payload)
    if length < 126:
        header.append((0x80 if masked else 0x00) | length)
    elif length <= 0xFFFF:
        header.append((0x80 if masked else 0x00) | 126)
        header.extend(struct.pack("!H", length))
    else:
        header.append((0x80 if masked else 0x00) | 127)
        header.extend(struct.pack("!Q", length))
    if masked:
        mask = random.randbytes(4) if hasattr(random, "randbytes") else os.urandom(4)
        header.extend(mask)
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    sock.sendall(bytes(header) + payload)


def ws_client_connect(host: str, port: int, protocol: str) -> socket.socket:
    subprotocol = JSON_SUBPROTOCOL if protocol == "json" else BINARY_SUBPROTOCOL
    sock = socket.create_connection((host, port), timeout=2.0)
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    request = (
        "GET / HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        f"Sec-WebSocket-Protocol: {subprotocol}\r\n"
        "\r\n"
    )
    sock.sendall(request.encode("utf-8"))
    response = sock.recv(4096).decode("utf-8", errors="replace")
    if "101 Switching Protocols" not in response:
        raise RuntimeError(f"handshake failed: {response}")
    return sock


def build_binary_packet(sent_id: int, jaw_open: float, eye_blink_left: float) -> bytes:
    header = bytearray(24)
    struct.pack_into("<I", header, 0, 0x5232464D)
    header[4] = 1
    header[5] = 1
    struct.pack_into("<I", header, 8, int(sent_id) & 0xFFFFFFFF)
    struct.pack_into("<H", header, 20, 1)

    face_header = bytearray(8)
    struct.pack_into("<H", face_header, 2, 2)
    face_header[4] = 0
    payload = header + face_header + struct.pack("<f", float(jaw_open)) + struct.pack("<f", float(eye_blink_left))
    return bytes(payload)


def send_binary_schema(sock: socket.socket, schema_names):
    schema_msg = {
        "type": "schema",
        "format": BINARY_SUBPROTOCOL,
        "blendshapeNames": list(schema_names),
    }
    send_ws_frame(sock, json.dumps(schema_msg, separators=(",", ":")).encode("utf-8"), opcode=0x1, masked=True)


class NativeReceiver:
    def __init__(self, native_module):
        self.native = native_module

    def start(self, host, port):
        self.native.start_receiver(host, int(port), {"drop_old_packets": True})

    def stop(self):
        self.native.stop_receiver()

    def poll(self):
        polled = self.native.poll_latest_packet()
        if not isinstance(polled, dict):
            return None
        return polled.get("packet")

    def stats(self):
        return self.native.get_receiver_stats()


class PythonRefReceiver:
    def __init__(self, native_module):
        self.native = native_module
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.Lock()
        self._host = ""
        self._port = 0
        self._server = None
        self._clients = set()
        self._latest = None
        self._packet_count = 0
        self._dropped = 0
        self._last_packet_time = 0.0
        self._status = "Stopped"
        self._last_error = ""
        self._client_address = ""
        self._poll_revision = 0
        self._packet_revision = 0

    def start(self, host, port):
        self.stop()
        self._host = host
        self._port = int(port)
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        deadline = time.time() + 2.0
        while time.time() < deadline:
            with self._lock:
                if self._status.startswith("Listening"):
                    return
            time.sleep(0.01)
        raise RuntimeError("python_ref receiver start timeout")

    def stop(self):
        self._stop.set()
        for s in list(self._clients):
            try:
                s.close()
            except OSError:
                pass
        self._clients.clear()

        for s in (self._server,):
            if s is None:
                continue
            try:
                s.close()
            except OSError:
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None
        with self._lock:
            self._status = "Stopped"

    def poll(self):
        with self._lock:
            if self._latest is None:
                return None
            if self._packet_revision == self._poll_revision:
                return None
            self._poll_revision = self._packet_revision
            return self._latest

    def stats(self):
        with self._lock:
            return {
                "host": self._host,
                "port": self._port,
                "is_listening": self._status.startswith("Listening") or self._status.startswith("Client"),
                "bind_failed": "failed" in self._status.lower(),
                "client_address": self._client_address,
                "packet_count": self._packet_count,
                "dropped_packet_count": self._dropped,
                "last_packet_time": self._last_packet_time,
                "last_sent_at": (self._latest or {}).get("sent_at", "") if isinstance(self._latest, dict) else "",
                "status_message": self._status,
                "last_error": self._last_error,
                "transport_mode": "websocket",
                "transport_encoding": "json",
            }

    def _run(self):
        try:
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind((self._host, self._port))
            srv.listen(8)
            srv.settimeout(0.2)
            self._server = srv
            with self._lock:
                self._status = f"Listening on ws://{self._host}:{self._port}"
            while not self._stop.is_set():
                try:
                    cli, addr = srv.accept()
                except socket.timeout:
                    continue
                self._clients.add(cli)
                threading.Thread(target=self._handle_client, args=(cli, addr), daemon=True).start()
        except Exception as exc:
            with self._lock:
                self._status = f"Face Capture receiver failed on ws://{self._host}:{self._port}"
                self._last_error = str(exc)

    def _handle_client(self, sock: socket.socket, addr):
        try:
            self._handle_client_inner(sock, addr)
        finally:
            try:
                sock.close()
            except OSError:
                pass
            self._clients.discard(sock)

    def _handle_client_inner(self, sock: socket.socket, addr):
        buffer = bytearray()
        while b"\r\n\r\n" not in buffer:
            chunk = sock.recv(4096)
            if not chunk:
                return
            buffer.extend(chunk)
        head_end = buffer.index(b"\r\n\r\n") + 4
        request = bytes(buffer[:head_end]).decode("utf-8", errors="replace")
        del buffer[:head_end]
        headers = {}
        for line in request.split("\r\n")[1:]:
            if ":" not in line:
                continue
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()
        key = headers.get("sec-websocket-key", "")
        if not key:
            return
        accept = base64.b64encode(hashlib.sha1((key + WS_MAGIC).encode("utf-8")).digest()).decode("ascii")
        response = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept}\r\n"
            f"Sec-WebSocket-Protocol: {JSON_SUBPROTOCOL}\r\n"
            "\r\n"
        )
        sock.sendall(response.encode("utf-8"))
        with self._lock:
            self._client_address = f"{addr[0]}:{addr[1]}"
            self._status = f"Client connected: {self._client_address}"
        while not self._stop.is_set():
            try:
                opcode, payload = read_ws_frame(sock)
            except Exception:
                return
            if opcode == 0x8:
                return
            if opcode == 0x9:
                send_ws_frame(sock, payload, opcode=0xA, masked=False)
                continue
            if opcode != 0x1:
                continue
            parsed = self.native.parse_packet_text(payload.decode("utf-8", errors="replace"))
            if parsed is None:
                continue
            with self._lock:
                if self._latest is not None and self._packet_revision != self._poll_revision:
                    self._dropped += 1
                self._latest = parsed
                self._packet_count += 1
                self._packet_revision += 1
                self._last_packet_time = time.time()


def percentile(values, p):
    if not values:
        return None
    values_sorted = sorted(values)
    idx = int(round((len(values_sorted) - 1) * p))
    return values_sorted[idx]


def mean_or_none(values):
    if not values:
        return None
    return sum(values) / len(values)


def stddev_or_none(values):
    if len(values) <= 1:
        return 0.0 if values else None
    return statistics.pstdev(values)


def _safe_round(value, digits=6):
    if value is None:
        return None
    return round(float(value), digits)


def _sender_worker(
    client_id,
    protocol,
    host,
    port,
    rounds,
    send_interval_s,
    send_timestamps,
    lock,
    errors,
):
    try:
        sock = ws_client_connect(host, port, protocol)
        if protocol == "binary":
            send_binary_schema(sock, DEFAULT_SCHEMA_NAMES)

        for i in range(rounds):
            sent_id = client_id * 1_000_000_000 + i
            sent_ns = time.perf_counter_ns()
            jaw_open = (i % 101) / 100.0
            eye_blink_left = ((i * 7) % 101) / 100.0
            if protocol == "json":
                msg = {
                    "type": "blendshapes",
                    "faces": [{"blendshapes": {"jawOpen": jaw_open, "eyeBlinkLeft": eye_blink_left}}],
                    "faceCount": 1,
                    "sentAt": str(sent_id),
                }
                payload = json.dumps(msg, separators=(",", ":")).encode("utf-8")
                send_ws_frame(sock, payload, opcode=0x1, masked=True)
            else:
                payload = build_binary_packet(sent_id=sent_id, jaw_open=jaw_open, eye_blink_left=eye_blink_left)
                send_ws_frame(sock, payload, opcode=0x2, masked=True)

            with lock:
                send_timestamps[sent_id] = sent_ns

            if send_interval_s > 0.0:
                time.sleep(send_interval_s)

        try:
            send_ws_frame(sock, b"", opcode=0x8, masked=True)
        except Exception:
            pass
        sock.close()
    except Exception as exc:
        with lock:
            errors.append(f"client#{client_id}: {exc}")


def run_once(
    mode: str,
    protocol: str,
    clients: int,
    rounds: int,
    host: str,
    port: int,
    send_interval_s: float,
    poll_timeout_s: float,
):
    native = load_native_module("rig2_face_cap")
    if mode == "python_ref" and protocol == "binary":
        return {
            "mode": mode,
            "protocol": protocol,
            "clients": clients,
            "rounds": rounds,
            "skipped": True,
            "skip_reason": "python_ref only supports json",
        }

    receiver = NativeReceiver(native) if mode == "native" else PythonRefReceiver(native)
    receiver.start(host, port)

    send_timestamps = {}
    send_lock = threading.Lock()
    sender_errors = []

    started = time.perf_counter()
    sender_threads = []
    for client_id in range(clients):
        t = threading.Thread(
            target=_sender_worker,
            args=(client_id, protocol, host, port, rounds, send_interval_s, send_timestamps, send_lock, sender_errors),
            daemon=True,
        )
        t.start()
        sender_threads.append(t)

    latencies_ms = []
    polled_count = 0
    end_deadline = time.perf_counter() + poll_timeout_s

    while time.perf_counter() < end_deadline:
        all_done = all(not t.is_alive() for t in sender_threads)
        pkt = receiver.poll()
        if isinstance(pkt, dict):
            polled_count += 1
            sent_at_raw = str(pkt.get("sent_at", "") or "")
            try:
                sent_id = int(sent_at_raw)
            except Exception:
                sent_id = None
            if sent_id is not None:
                with send_lock:
                    sent_ns = send_timestamps.get(sent_id)
                if sent_ns is not None:
                    latencies_ms.append((time.perf_counter_ns() - sent_ns) / 1_000_000.0)
            continue

        if all_done:
            stats = receiver.stats() or {}
            packet_count = int(stats.get("packet_count", 0) or 0)
            if packet_count >= clients * rounds:
                break
        time.sleep(0.0005)

    for t in sender_threads:
        t.join(timeout=2.0)

    elapsed_s = max(1e-6, time.perf_counter() - started)
    stats = receiver.stats() or {}
    receiver.stop()

    with send_lock:
        total_sent = len(send_timestamps)

    packet_count = int(stats.get("packet_count", 0) or 0)
    dropped_count = int(stats.get("dropped_packet_count", 0) or 0)

    result = {
        "mode": mode,
        "protocol": protocol,
        "clients": clients,
        "rounds": rounds,
        "elapsed_s": _safe_round(elapsed_s),
        "sent_count": int(total_sent),
        "polled_count": int(polled_count),
        "receiver_packet_count": packet_count,
        "dropped_packet_count": dropped_count,
        "send_msgs_per_s": _safe_round(total_sent / elapsed_s),
        "receiver_msgs_per_s": _safe_round(packet_count / elapsed_s),
        "poll_msgs_per_s": _safe_round(polled_count / elapsed_s),
        "p50_ms": _safe_round(percentile(latencies_ms, 0.50)),
        "p95_ms": _safe_round(percentile(latencies_ms, 0.95)),
        "p99_ms": _safe_round(percentile(latencies_ms, 0.99)),
        "sender_errors": sender_errors,
        "status_message": str(stats.get("status_message", "") or ""),
        "last_error": str(stats.get("last_error", "") or ""),
        "transport_encoding": stats.get("transport_encoding"),
    }
    return result


def summarize_repeats(repeat_results):
    valid = [r for r in repeat_results if not r.get("skipped")]
    if not valid:
        return {
            "repeat_count": len(repeat_results),
            "valid_repeats": 0,
            "skipped": True,
            "skip_reason": repeat_results[0].get("skip_reason", "all repeats skipped") if repeat_results else "",
        }

    fields = [
        "elapsed_s",
        "send_msgs_per_s",
        "receiver_msgs_per_s",
        "poll_msgs_per_s",
        "p50_ms",
        "p95_ms",
        "p99_ms",
        "receiver_packet_count",
        "dropped_packet_count",
    ]
    agg = {
        "repeat_count": len(repeat_results),
        "valid_repeats": len(valid),
        "sent_count": int(sum(r.get("sent_count", 0) for r in valid) / max(1, len(valid))),
    }

    for field in fields:
        values = [float(r[field]) for r in valid if r.get(field) is not None]
        agg[f"{field}_mean"] = _safe_round(mean_or_none(values))
        agg[f"{field}_stddev"] = _safe_round(stddev_or_none(values))

    total_errors = []
    for r in valid:
        total_errors.extend(r.get("sender_errors", []))
        if r.get("last_error"):
            total_errors.append(r["last_error"])
    agg["error_count"] = len([e for e in total_errors if e])
    return agg


def run_matrix(
    modes,
    protocols,
    client_values,
    rounds,
    repeat,
    host,
    base_port,
    send_interval,
    poll_timeout,
):
    matrix = []
    case_index = 0
    for mode in modes:
        for protocol in protocols:
            for clients in client_values:
                repeat_results = []
                for rep in range(repeat):
                    port = base_port + case_index * 50 + rep
                    one = run_once(
                        mode=mode,
                        protocol=protocol,
                        clients=clients,
                        rounds=rounds,
                        host=host,
                        port=port,
                        send_interval_s=send_interval,
                        poll_timeout_s=poll_timeout,
                    )
                    one["repeat_index"] = rep + 1
                    repeat_results.append(one)
                matrix.append(
                    {
                        "case": {
                            "mode": mode,
                            "protocol": protocol,
                            "clients": clients,
                            "rounds": rounds,
                        },
                        "summary": summarize_repeats(repeat_results),
                        "repeats": repeat_results,
                    }
                )
                case_index += 1
    return matrix


def parse_csv_ints(input_text):
    out = []
    for part in str(input_text or "").split(","):
        part = part.strip()
        if not part:
            continue
        value = int(part)
        if value <= 0:
            raise ValueError("clients must be > 0")
        out.append(value)
    if not out:
        raise ValueError("at least one clients value is required")
    return out


def main():
    parser = argparse.ArgumentParser(description="Benchmark face_cap receiver path.")
    parser.add_argument("--mode", choices=["native", "python_ref", "both"], default="both")
    parser.add_argument("--protocol", choices=["json", "binary", "both"], default="both")
    parser.add_argument("--clients", default="1,4,8", help="comma-separated client counts")
    parser.add_argument("--rounds", type=int, default=2000, help="fixed messages per client")
    parser.add_argument("--repeat", type=int, default=3, help="repeat count per case")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=19090)
    parser.add_argument("--send-interval", type=float, default=0.0, help="seconds between sends")
    parser.add_argument("--poll-timeout", type=float, default=20.0, help="max polling seconds per run")
    args = parser.parse_args()

    if args.rounds <= 0:
        raise ValueError("--rounds must be > 0")
    if args.repeat <= 0:
        raise ValueError("--repeat must be > 0")

    modes = ["native", "python_ref"] if args.mode == "both" else [args.mode]
    protocols = ["json", "binary"] if args.protocol == "both" else [args.protocol]
    client_values = parse_csv_ints(args.clients)

    started_utc = datetime.now(timezone.utc)
    matrix = run_matrix(
        modes=modes,
        protocols=protocols,
        client_values=client_values,
        rounds=args.rounds,
        repeat=args.repeat,
        host=args.host,
        base_port=args.port,
        send_interval=args.send_interval,
        poll_timeout=args.poll_timeout,
    )

    output = {
        "schema_version": 1,
        "benchmark": "face_cap_receiver",
        "started_at_utc": started_utc.isoformat(),
        "config": {
            "mode": args.mode,
            "protocol": args.protocol,
            "clients": client_values,
            "rounds": args.rounds,
            "repeat": args.repeat,
            "host": args.host,
            "base_port": args.port,
            "send_interval": args.send_interval,
            "poll_timeout": args.poll_timeout,
        },
        "environment": {
            "platform": platform.platform(),
            "python_version": sys.version,
            "machine": platform.machine(),
            "processor": platform.processor(),
        },
        "results": matrix,
    }

    print(json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
