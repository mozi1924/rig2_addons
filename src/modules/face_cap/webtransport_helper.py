import argparse
import asyncio
import socket
import sys
import threading
from functools import partial
from urllib.parse import parse_qs, urlsplit


SERVER_NAME = "Rig2FaceCapWT/1.0"


def _emit_stdout(message):
    print(message, flush=True)


def _load_aioquic():
    try:
        from aioquic.asyncio import serve
        from aioquic.asyncio.protocol import QuicConnectionProtocol
        from aioquic.h3.connection import H3_ALPN, H3Connection
        from aioquic.h3.events import (
            DatagramReceived,
            HeadersReceived,
            WebTransportStreamDataReceived,
        )
        from aioquic.quic.configuration import QuicConfiguration
        from aioquic.quic.events import ProtocolNegotiated, QuicEvent
    except Exception as exc:  # pragma: no cover - dependency bootstrap path
        raise RuntimeError(f"failed to import aioquic: {exc}") from exc

    return {
        "serve": serve,
        "QuicConnectionProtocol": QuicConnectionProtocol,
        "H3_ALPN": H3_ALPN,
        "H3Connection": H3Connection,
        "DatagramReceived": DatagramReceived,
        "HeadersReceived": HeadersReceived,
        "WebTransportStreamDataReceived": WebTransportStreamDataReceived,
        "QuicConfiguration": QuicConfiguration,
        "ProtocolNegotiated": ProtocolNegotiated,
        "QuicEvent": QuicEvent,
    }


class FaceCapUdpForwarder:
    def __init__(self, host, port):
        self._target = (host, port)
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send(self, payload):
        if payload:
            self._socket.sendto(payload, self._target)

    def close(self):
        try:
            self._socket.close()
        except OSError:
            pass


def _build_protocol_class(aioquic, emit):
    QuicConnectionProtocol = aioquic["QuicConnectionProtocol"]
    H3Connection = aioquic["H3Connection"]
    H3_ALPN = aioquic["H3_ALPN"]
    DatagramReceived = aioquic["DatagramReceived"]
    HeadersReceived = aioquic["HeadersReceived"]
    WebTransportStreamDataReceived = aioquic["WebTransportStreamDataReceived"]
    ProtocolNegotiated = aioquic["ProtocolNegotiated"]

    class FaceCapWebTransportSession:
        def __init__(self, connection, stream_id, session_id, forwarder, transmit):
            self.accepted = False
            self.connection = connection
            self.stream_id = stream_id
            self.session_id = session_id
            self.forwarder = forwarder
            self.transmit = transmit

        def accept(self):
            if self.accepted:
                return

            self.connection.send_headers(
                stream_id=self.stream_id,
                headers=[
                    (b":status", b"200"),
                    (b"server", SERVER_NAME.encode("ascii")),
                    (b"sec-webtransport-http3-draft", b"draft02"),
                ],
            )
            self.accepted = True
            self.transmit()

        def http_event_received(self, event):
            if not self.accepted:
                return

            if isinstance(event, DatagramReceived):
                self.forwarder.send(event.data)
                return

            if isinstance(event, WebTransportStreamDataReceived) and event.data:
                self.forwarder.send(event.data)

    class FaceCapWebTransportProtocol(QuicConnectionProtocol):
        def __init__(self, *args, forwarder, **kwargs):
            super().__init__(*args, **kwargs)
            self._forwarder = forwarder
            self._http = None
            self._sessions = {}
            self._emit = emit

        def http_event_received(self, event):
            if isinstance(event, HeadersReceived) and event.stream_id not in self._sessions:
                method = ""
                protocol = ""
                raw_path = b""

                for header, value in event.headers:
                    if header == b":method":
                        method = value.decode("utf-8", errors="replace")
                    elif header == b":protocol":
                        protocol = value.decode("utf-8", errors="replace")
                    elif header == b":path":
                        raw_path = value

                parsed = urlsplit(raw_path.decode("utf-8", errors="replace"))
                session_id = parse_qs(parsed.query).get("session", [""])[0]

                if method == "CONNECT" and protocol == "webtransport" and parsed.path == "/capture":
                    session = FaceCapWebTransportSession(
                        connection=self._http,
                        stream_id=event.stream_id,
                        session_id=session_id,
                        forwarder=self._forwarder,
                        transmit=self.transmit,
                    )
                    self._sessions[event.stream_id] = session
                    session.accept()
                    self._emit(
                        f"WT_INFO accepted WebTransport session {session_id or '<anonymous>'}"
                    )
                    return

                if self._http is not None:
                    self._http.send_headers(
                        stream_id=event.stream_id,
                        headers=[
                            (b":status", b"404"),
                            (b"server", SERVER_NAME.encode("ascii")),
                        ],
                    )
                    self._http.send_data(stream_id=event.stream_id, data=b"", end_stream=True)
                    self.transmit()
                return

            if isinstance(event, DatagramReceived):
                session = self._sessions.get(event.stream_id)
                if session:
                    session.http_event_received(event)
                return

            if isinstance(event, WebTransportStreamDataReceived):
                session = self._sessions.get(event.session_id)
                if session:
                    session.http_event_received(event)

        def quic_event_received(self, event):
            if isinstance(event, ProtocolNegotiated) and event.alpn_protocol in H3_ALPN:
                self._http = H3Connection(self._quic, enable_webtransport=True)

            if self._http is None:
                return

            for http_event in self._http.handle_event(event):
                self.http_event_received(http_event)

    return FaceCapWebTransportProtocol


async def run_server(args, ready_callback=None, emit=None, stop_future=None):
    emit = emit or _emit_stdout
    aioquic = _load_aioquic()

    configuration = aioquic["QuicConfiguration"](
        is_client=False,
        alpn_protocols=aioquic["H3_ALPN"],
        max_datagram_frame_size=65536,
    )
    configuration.load_cert_chain(args.cert, args.key)

    forwarder = FaceCapUdpForwarder(args.udp_host, args.udp_port)
    protocol_factory = partial(
        _build_protocol_class(aioquic, emit),
        forwarder=forwarder,
    )
    server = None

    try:
        server = await aioquic["serve"](
            args.host,
            args.port,
            configuration=configuration,
            create_protocol=protocol_factory,
        )

        url = f"https://{args.host}:{args.port}/capture"
        emit(f"WT_READY {url}")
        if callable(ready_callback):
            ready_callback(url)

        if stop_future is None:
            stop_future = asyncio.get_running_loop().create_future()

        await stop_future
    finally:
        if server is not None:
            server.close()
            wait_closed = getattr(server, "wait_closed", None)
            if callable(wait_closed):
                await wait_closed()
        forwarder.close()


class FaceCapWebTransportServer(threading.Thread):
    def __init__(self, args, emit=None):
        super().__init__(daemon=True)
        self.args = args
        self.emit = emit or _emit_stdout
        self._loop = None
        self._stop_future = None
        self._startup_event = threading.Event()
        self._ready_event = threading.Event()
        self._ready_url = ""

    def wait_started(self, timeout=None):
        return self._startup_event.wait(timeout=timeout)

    def wait_until_ready(self, timeout=None):
        return self._ready_event.wait(timeout=timeout)

    def stop(self):
        loop = self._loop
        stop_future = self._stop_future
        if loop and stop_future and not stop_future.done():
            loop.call_soon_threadsafe(stop_future.set_result, True)
        if self.is_alive():
            self.join(timeout=2.0)

    def run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._stop_future = self._loop.create_future()
        self._startup_event.set()

        try:
            self._loop.run_until_complete(
                run_server(
                    self.args,
                    ready_callback=self._handle_ready,
                    emit=self.emit,
                    stop_future=self._stop_future,
                )
            )
        except Exception as exc:
            self.emit(f"WT_ERROR {exc}")
        finally:
            self._ready_event.clear()
            try:
                self._loop.close()
            except Exception:
                pass
            self._loop = None
            self._stop_future = None

    def _handle_ready(self, url):
        self._ready_url = url
        self._ready_event.set()


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Rig2 FaceCap WebTransport helper")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9443)
    parser.add_argument("--udp-host", default="127.0.0.1")
    parser.add_argument("--udp-port", type=int, required=True)
    parser.add_argument("--cert", required=True)
    parser.add_argument("--key", required=True)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        asyncio.run(run_server(args))
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        _emit_stdout(f"WT_ERROR {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
