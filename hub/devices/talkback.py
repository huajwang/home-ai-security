"""ONVIF RTSP audio backchannel: phone mic → doorbell speaker."""

from __future__ import annotations

import hashlib
import queue
import secrets
import socket
import struct
import threading
import time
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

import numpy as np

from hub import config


BACKCHANNEL = "www.onvif.org/ver20/backchannel"
G711_FRAME = 1024  # Reolink speaker pipeline expects ~1024-byte G.711 frames.


def redact_rtsp(url: str) -> str:
    if "://" in url and "@" in url:
        scheme, rest = url.split("://", 1)
        host = rest.rsplit("@", 1)[-1]
        return f"{scheme}://***@{host}"
    return url


def linear_to_ulaw(samples: np.ndarray) -> bytes:
    out = bytearray()
    for sample in np.asarray(samples, dtype=np.int32).reshape(-1):
        value = int(sample)
        sign = 0x80 if value < 0 else 0
        if sign:
            value = -value
        if value > 32635:
            value = 32635
        value += 0x84
        exponent = 7
        mask = 0x4000
        while exponent > 0 and (value & mask) == 0:
            exponent -= 1
            mask >>= 1
        mantissa = (value >> (exponent + 3)) & 0x0F
        out.append((~(sign | (exponent << 4) | mantissa)) & 0xFF)
    return bytes(out)


def linear_to_alaw(samples: np.ndarray) -> bytes:
    out = bytearray()
    for sample in np.asarray(samples, dtype=np.int32).reshape(-1):
        value = int(sample)
        sign = 0x80 if value >= 0 else 0
        if value < 0:
            value = -value
        if value > 32767:
            value = 32767
        exponent = 7
        mask = 0x4000
        while exponent > 0 and (value & mask) == 0:
            exponent -= 1
            mask >>= 1
        mantissa = (value >> 4) & 0x0F if exponent == 0 else (value >> (exponent + 3)) & 0x0F
        out.append(((sign | (exponent << 4) | mantissa) ^ 0x55) & 0xFF)
    return bytes(out)


@dataclass
class Backchannel:
    control: str
    payload_type: int
    encoding: str


def parse_backchannel(sdp: str, base_url: str) -> Backchannel | None:
    block: list[str] = []
    blocks: list[list[str]] = []
    for line in sdp.replace("\r\n", "\n").split("\n"):
        if line.startswith("m="):
            if block:
                blocks.append(block)
            block = [line]
        elif block:
            block.append(line)
    if block:
        blocks.append(block)
    for media in blocks:
        header = media[0]
        if not header.startswith("m=audio"):
            continue
        attrs = {line[2:].split(":", 1)[0]: line[2:] for line in media if line.startswith("a=")}
        direction = ""
        for line in media:
            if line in {"a=sendonly", "a=recvonly", "a=sendrecv", "a=inactive"}:
                direction = line[2:]
        if direction != "sendonly":
            continue
        parts = header.split()
        payload = int(parts[3]) if len(parts) > 3 else 0
        encoding = "PCMU"
        for line in media:
            if line.startswith("a=rtpmap:"):
                rest = line.split(":", 1)[1]
                codec = rest.split(" ", 1)[-1].upper()
                if "PCMA" in codec:
                    encoding = "PCMA"
                elif "PCMU" in codec:
                    encoding = "PCMU"
                payload = int(rest.split(" ", 1)[0])
        control = "track3"
        for line in media:
            if line.startswith("a=control:"):
                control = line.split(":", 1)[1].strip()
        if not control.startswith("rtsp://"):
            control = base_url.rstrip("/") + "/" + control.lstrip("/")
        return Backchannel(control=control, payload_type=payload, encoding=encoding)
    return None


class DoorTalkback:
    def __init__(self, url: str) -> None:
        self.url = url
        self._sock: socket.socket | None = None
        self._session = ""
        self._auth_header = ""
        self._auth: dict[str, str] = {}
        self._cseq = 1
        self._channel = 0
        self._stop = threading.Event()
        self._io: threading.Thread | None = None
        self._out: queue.Queue[bytes | None] = queue.Queue(maxsize=40)
        self._seq = secrets.randbelow(1 << 16)
        self._ts = 0
        self._ssrc = secrets.randbelow(1 << 32)
        self._pt = 0
        self._encode = linear_to_ulaw
        self._pending = bytearray()
        parsed = urlparse(url)
        self._username = unquote(parsed.username or "")
        self._password = unquote(parsed.password or "")
        self._host = parsed.hostname or ""
        self._port = parsed.port or 554
        path = parsed.path or "/"
        self._base = f"rtsp://{self._host}:{self._port}{path}"

    def start(self) -> bool:
        if not self._host or not self._username:
            return False
        try:
            self._connect()
            return True
        except Exception as exc:  # noqa: BLE001
            print(f"Doorbell talkback failed: {type(exc).__name__}: {exc}")
            self.close()
            return False

    def write_pcm8k(self, pcm: np.ndarray) -> None:
        if self._stop.is_set():
            return
        payload = self._encode(pcm)
        self._pending.extend(payload)
        while len(self._pending) >= G711_FRAME:
            frame = bytes(self._pending[:G711_FRAME])
            del self._pending[:G711_FRAME]
            try:
                self._out.put_nowait(frame)
            except queue.Full:
                try:
                    self._out.get_nowait()
                except queue.Empty:
                    pass
                try:
                    self._out.put_nowait(frame)
                except queue.Full:
                    pass

    def close(self) -> None:
        self._stop.set()
        try:
            self._out.put_nowait(None)
        except queue.Full:
            pass
        if self._io is not None:
            self._io.join(timeout=2)
            self._io = None
        sock = self._sock
        self._sock = None
        if sock is not None:
            try:
                if self._session:
                    self._request("TEARDOWN", self._base, sock=sock)
            except Exception:
                pass
            try:
                sock.close()
            except Exception:
                pass

    def _connect(self) -> None:
        sock = socket.create_connection((self._host, self._port), timeout=8)
        sock.settimeout(8)
        self._sock = sock
        self._request("OPTIONS", self._base)
        describe = self._request(
            "DESCRIBE",
            self._base,
            extra={"Accept": "application/sdp", "Require": BACKCHANNEL},
        )
        back = parse_backchannel(describe, self._base)
        if back is None:
            raise RuntimeError("no ONVIF sendonly audio track")
        self._pt = back.payload_type
        self._encode = linear_to_alaw if back.encoding == "PCMA" else linear_to_ulaw
        setup = self._request(
            "SETUP",
            back.control,
            extra={
                "Transport": "RTP/AVP/TCP;unicast;interleaved=0-1",
                "Require": BACKCHANNEL,
            },
        )
        self._session = _header(setup, "Session").split(";")[0].strip()
        transport = _header(setup, "Transport")
        if "interleaved=" in transport:
            start = transport.split("interleaved=", 1)[1].split(";", 1)[0]
            self._channel = int(start.split("-", 1)[0])
        self._request(
            "PLAY",
            self._base,
            extra={"Require": BACKCHANNEL, "Range": "npt=0.000-"},
        )
        print(f"Doorbell talkback {back.encoding} {redact_rtsp(self._base)}")
        sock.settimeout(0.25)
        self._stop.clear()
        self._io = threading.Thread(target=self._pump, name="doorbell-talkback", daemon=True)
        self._io.start()

    def _pump(self) -> None:
        sock = self._sock
        if sock is None:
            return
        while not self._stop.is_set():
            self._drain(sock)
            try:
                frame = self._out.get(timeout=0.05)
            except queue.Empty:
                continue
            if frame is None:
                break
            packet = self._rtp(frame)
            try:
                sock.sendall(packet)
            except Exception as exc:  # noqa: BLE001
                print(f"Doorbell talkback send failed: {type(exc).__name__}")
                break

    def _rtp(self, payload: bytes) -> bytes:
        header = struct.pack(
            "!BBHII",
            0x80,
            self._pt & 0x7F,
            self._seq & 0xFFFF,
            self._ts & 0xFFFFFFFF,
            self._ssrc & 0xFFFFFFFF,
        )
        self._seq = (self._seq + 1) & 0xFFFF
        self._ts = (self._ts + len(payload)) & 0xFFFFFFFF
        body = header + payload
        return struct.pack("!BBH", 0x24, self._channel, len(body)) + body

    def _drain(self, sock: socket.socket) -> None:
        try:
            sock.settimeout(0.0)
            data = sock.recv(4096)
            if not data:
                self._stop.set()
        except BlockingIOError:
            return
        except TimeoutError:
            return
        except Exception:
            return
        finally:
            try:
                sock.settimeout(0.25)
            except Exception:
                pass

    def _request(self, method: str, url: str, extra: dict[str, str] | None = None, sock: socket.socket | None = None) -> str:
        target = sock or self._sock
        if target is None:
            raise RuntimeError("talkback socket closed")
        headers = extra or {}
        response = self._send(target, method, url, headers)
        if response.startswith("RTSP/1.0 401"):
            self._auth = _parse_digest(_header(response, "WWW-Authenticate"))
            response = self._send(target, method, url, headers)
        if not response.startswith("RTSP/1.0 200"):
            first = response.split("\r\n", 1)[0]
            raise RuntimeError(f"{method} {first or 'failed'}")
        return response

    def _send(self, sock: socket.socket, method: str, url: str, extra: dict[str, str]) -> str:
        parsed = urlparse(url)
        uri = url
        if not uri.startswith("rtsp://"):
            uri = parsed.path or "/"
            if parsed.query:
                uri += f"?{parsed.query}"
        lines = [
            f"{method} {url} RTSP/1.0",
            f"CSeq: {self._cseq}",
            "User-Agent: home-ai-security-hub",
        ]
        self._cseq += 1
        if self._session:
            lines.append(f"Session: {self._session}")
        if self._auth:
            lines.append("Authorization: " + _digest(self._username, self._password, method, uri, self._auth))
        for key, value in extra.items():
            lines.append(f"{key}: {value}")
        payload = ("\r\n".join(lines) + "\r\n\r\n").encode()
        sock.sendall(payload)
        return _read_rtsp(sock)


def _read_rtsp(sock: socket.socket) -> str:
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(4096)
        if not chunk:
            break
        data += chunk
        if data[:1] == b"$":
            if len(data) < 4:
                more = sock.recv(4 - len(data))
                data += more
            length = struct.unpack("!H", data[2:4])[0]
            need = 4 + length
            while len(data) < need:
                more = sock.recv(need - len(data))
                if not more:
                    break
                data += more
            data = data[need:]
            continue
    header, _, rest = data.partition(b"\r\n\r\n")
    text = header.decode("utf-8", "replace") + "\r\n\r\n"
    length = 0
    for line in text.split("\r\n"):
        if line.lower().startswith("content-length:"):
            length = int(line.split(":", 1)[1].strip() or "0")
    body = rest
    while len(body) < length:
        chunk = sock.recv(length - len(body))
        if not chunk:
            break
        body += chunk
    return text + body[:length].decode("utf-8", "replace")


def _header(response: str, name: str) -> str:
    key = name.lower() + ":"
    for line in response.split("\r\n"):
        if line.lower().startswith(key):
            return line.split(":", 1)[1].strip()
    return ""


def _parse_digest(header: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    if " " in header:
        header = header.split(" ", 1)[1]
    for part in header.split(","):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        fields[key.strip()] = value.strip().strip('"')
    return fields


def _digest(username: str, password: str, method: str, uri: str, auth: dict[str, str]) -> str:
    realm = auth.get("realm", "")
    nonce = auth.get("nonce", "")
    qop = (auth.get("qop") or "").split(",")[0].strip()
    ha1 = hashlib.md5(f"{username}:{realm}:{password}".encode()).hexdigest()
    ha2 = hashlib.md5(f"{method}:{uri}".encode()).hexdigest()
    if qop:
        nc = "00000001"
        cnonce = secrets.token_hex(8)
        response = hashlib.md5(f"{ha1}:{nonce}:{nc}:{cnonce}:{qop}:{ha2}".encode()).hexdigest()
        return (
            f'Digest username="{username}", realm="{realm}", nonce="{nonce}", uri="{uri}", '
            f'response="{response}", qop={qop}, nc={nc}, cnonce="{cnonce}"'
        )
    response = hashlib.md5(f"{ha1}:{nonce}:{ha2}".encode()).hexdigest()
    return (
        f'Digest username="{username}", realm="{realm}", nonce="{nonce}", uri="{uri}", '
        f'response="{response}"'
    )


def from_config() -> DoorTalkback | None:
    if not config.TALKBACK_ENABLED or not config.CAMERA_URL:
        return None
    return DoorTalkback(config.CAMERA_URL)
