"""Answer Tailscale split-DNS queries for the Cloud Link name.

Tailnet clients that ask for rock.link.yaojiabuy.com get this machine's
Tailscale address. The phone then opens Home Assistant directly. When
Tailscale is off, the phone uses public DNS and Cloud Link instead.
"""

from __future__ import annotations

import socket
import struct
import subprocess
import time

HOST = "rock.link.yaojiabuy.com"


def tailscale_ipv4() -> str:
    output = subprocess.check_output(["tailscale", "ip", "-4"], text=True)
    return output.strip().splitlines()[0]


def read_name(data: bytes, offset: int) -> tuple[str, int]:
    labels: list[str] = []
    cursor = offset
    while True:
        length = data[cursor]
        if length == 0:
            return ".".join(labels), cursor + 1
        if length & 0xC0:
            return ".".join(labels), cursor + 2
        cursor += 1
        labels.append(data[cursor : cursor + length].decode("ascii"))
        cursor += length


def answer(query: bytes, address: str) -> bytes:
    transaction = query[:2]
    name, offset = read_name(query, 12)
    qtype = struct.unpack("!H", query[offset : offset + 2])[0]
    question = query[12 : offset + 4]
    wanted = name.lower().rstrip(".") == HOST
    if wanted and qtype == 1:
        payload = socket.inet_aton(address)
        record = b"\xc0\x0c" + struct.pack("!HHIH", 1, 1, 60, 4) + payload
        header = struct.pack("!HHHHHH", int.from_bytes(transaction, "big"), 0x8400, 1, 1, 0, 0)
        return header + question + record
    flags = 0x8400 if wanted else 0x8403
    header = struct.pack("!HHHHHH", int.from_bytes(transaction, "big"), flags, 1, 0, 0, 0)
    return header + question


def serve() -> None:
    while True:
        try:
            address = tailscale_ipv4()
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.bind((address, 53))
        except OSError:
            time.sleep(2)
            continue
        break
    print(f"split DNS for {HOST} -> {address}")
    while True:
        query, sender = sock.recvfrom(512)
        if len(query) < 12:
            continue
        try:
            sock.sendto(answer(query, address), sender)
        except Exception:
            continue


if __name__ == "__main__":
    serve()
