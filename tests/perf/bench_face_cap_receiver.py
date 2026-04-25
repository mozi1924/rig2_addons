#!/usr/bin/env python3
import argparse
import base64
import hashlib
import importlib.machinery
import importlib.util
import json
import os
import platform
import random
import socket
import struct
import sys
import threading
import time


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC = os.path.join(ROOT, "src")
WS_MAGIC = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
JSON_SUBPROTOCOL = "r2fmc.json.v1"


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


def ws_client_connect(host: str, port: int) -> socket.socket:
    sock = socket.create_connection((host, port), timeout=2.0)
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    request = (
        "GET / HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        f"Sec-WebSocket-Protocol: {JSON_SUBPROTOCOL}\r\n"
        "\r\n"
    )
    sock.sendall(request.encode("utf-8"))
    response = sock.recv(4096).decode("utf-8", errors="replace")
    if "101 Switching Protocols" not in response:
        raise RuntimeError(f"handshake failed: {response}")
    return sock


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
        self._client = None
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
        for s in (self._client, self._server):
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
            srv.listen(1)
            srv.settimeout(0.2)
            self._server = srv
            with self._lock:
                self._status = f"Listening on ws://{self._host}:{self._port}"
            while not self._stop.is_set():
                try:
                    cli, addr = srv.accept()
                except socket.timeout:
                    continue
                self._client = cli
                try:
                    self._handle_client(cli, addr)
                finally:
                    try:
                        cli.close()
                    except OSError:
                        pass
                    self._client = None
        except Exception as exc:
            with self._lock:
                self._status = f"Face Capture receiver failed on ws://{self._host}:{self._port}"
                self._last_error = str(exc)

    def _handle_client(self, sock: socket.socket, addr):
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
    values = sorted(values)
    idx = int(round((len(values) - 1) * p))
    return values[idx]


def run_once(mode: str, duration_s: float, host: str, port: int, send_interval_s: float):
    native = load_native_module("rig2_face_cap")
    receiver = NativeReceiver(native) if mode == "native" else PythonRefReceiver(native)
    receiver.start(host, port)

    sent_count = 0
    sent_lock = threading.Lock()
    stop_sender = threading.Event()

    def sender():
        nonlocal sent_count
        sock = ws_client_connect(host, port)
        try:
            while not stop_sender.is_set():
                sent_at = time.perf_counter_ns()
                msg = {
                    "type": "blendshapes",
                    "faces": [{"blendshapes": {"jawOpen": 0.5}}],
                    "faceCount": 1,
                    "sentAt": str(sent_at),
                }
                payload = json.dumps(msg, separators=(",", ":")).encode("utf-8")
                send_ws_frame(sock, payload, opcode=0x1, masked=True)
                with sent_lock:
                    sent_count += 1
                if send_interval_s > 0.0:
                    time.sleep(send_interval_s)
        finally:
            try:
                send_ws_frame(sock, b"", opcode=0x8, masked=True)
            except Exception:
                pass
            sock.close()

    sender_thread = threading.Thread(target=sender, daemon=True)
    sender_thread.start()

    started = time.perf_counter()
    latencies_ms = []
    received_count = 0
    while time.perf_counter() - started < duration_s:
        pkt = receiver.poll()
        if isinstance(pkt, dict):
            received_count += 1
            sent_at_raw = str(pkt.get("sent_at", "") or "")
            try:
                sent_ns = int(sent_at_raw)
                latencies_ms.append((time.perf_counter_ns() - sent_ns) / 1_000_000.0)
            except Exception:
                pass
        else:
            time.sleep(0.0005)

    stop_sender.set()
    sender_thread.join(timeout=1.0)
    stats = receiver.stats() or {}
    receiver.stop()

    with sent_lock:
        total_sent = sent_count

    return {
        "mode": mode,
        "duration_s": duration_s,
        "sent_count": total_sent,
        "received_count": received_count,
        "receiver_packet_count": int(stats.get("packet_count", 0) or 0),
        "dropped_packet_count": int(stats.get("dropped_packet_count", 0) or 0),
        "send_msgs_per_s": total_sent / max(duration_s, 1e-6),
        "received_msgs_per_s": received_count / max(duration_s, 1e-6),
        "p50_ms": percentile(latencies_ms, 0.50),
        "p95_ms": percentile(latencies_ms, 0.95),
        "p99_ms": percentile(latencies_ms, 0.99),
    }


def main():
    parser = argparse.ArgumentParser(description="Benchmark face_cap receiver path.")
    parser.add_argument("--mode", choices=["native", "python_ref", "both"], default="both")
    parser.add_argument("--duration", type=float, default=8.0)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=19090)
    parser.add_argument("--send-interval", type=float, default=0.0, help="seconds between sends")
    args = parser.parse_args()

    modes = ["native", "python_ref"] if args.mode == "both" else [args.mode]
    results = []
    for i, mode in enumerate(modes):
        port = args.port + i
        results.append(run_once(mode, args.duration, args.host, port, args.send_interval))

    print(json.dumps({"results": results}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
