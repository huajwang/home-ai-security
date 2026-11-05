"""Sound the Elegoo Mega when Home Assistant posts a door or panic event.

The Mega stays on the lab PC USB serial port. Home Assistant calls this
process with rest_command.elegoo_event. A shared token header is required.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


def should_sound(event: dict[str, Any], armed: bool) -> bool:
    """One local burst for a remote panic, or a person at the door while armed."""
    if event.get("label") == "panic":
        return True
    if not armed:
        return False
    if event.get("camera") != "door":
        return False
    return event.get("label") == "person"


class AlertDecider:
    """Remember which events already happened so startup does not replay them."""

    def __init__(self) -> None:
        self._seen: set[Any] = set()
        self._primed = False
        self._armed = False

    def commands(self, events: list[dict[str, Any]], armed: bool) -> list[str]:
        fresh = [event for event in events if event.get("id") not in self._seen]
        for event in fresh:
            event_id = event.get("id")
            if event_id is not None:
                self._seen.add(event_id)
        if not self._primed:
            self._primed = True
            self._armed = armed
            return []
        out: list[str] = []
        if self._armed and not armed:
            out.append("OFF")
        for event in fresh:
            if should_sound(event, armed):
                out.append("ON")
        self._armed = armed
        return out


class SerialSiren:
    def __init__(self, port: str, baud: int = 9600) -> None:
        import serial

        self._port = port
        self._baud = baud
        self._serial = serial
        self._ser = serial.Serial(port, baud, timeout=1)
        time.sleep(2.0)

    def send(self, command: str) -> None:
        self._ser.write((command + "\n").encode())
        self._ser.flush()

    def reopen(self) -> None:
        try:
            self._ser.close()
        except Exception:
            pass
        self._ser = self._serial.Serial(self._port, self._baud, timeout=1)
        time.sleep(2.0)

    def close(self) -> None:
        self._ser.close()


def armed_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes"}


class EventServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], token: str, siren: SerialSiren) -> None:
        super().__init__(address, EventHandler)
        self.token = token
        self.siren = siren
        self.decider = AlertDecider()


class EventHandler(BaseHTTPRequestHandler):
    server: EventServer

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/event":
            self.send_error(404)
            return
        supplied = self.headers.get("X-Elegoo-Token", "")
        if not self.server.token or supplied != self.server.token:
            self.send_error(401)
            return
        length = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self.send_error(400)
            return
        armed = armed_flag(payload.get("armed"))
        events = [payload] if payload.get("label") else []
        commands = self.server.decider.commands(events, armed)
        for command in commands:
            try:
                self.server.siren.send(command)
            except Exception:
                self.server.siren.reopen()
                self.server.siren.send(command)
            print(command, flush=True)
        body = json.dumps({"commands": commands}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        print(fmt % args, flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Elegoo siren listener for Home Assistant")
    parser.add_argument("--port-serial", default=os.environ.get("ELEGOO_PORT", "COM6"))
    parser.add_argument("--listen", default=os.environ.get("ELEGOO_LISTEN", "0.0.0.0"))
    parser.add_argument("--listen-port", type=int, default=int(os.environ.get("ELEGOO_LISTEN_PORT", "8092")))
    parser.add_argument("--token", default=os.environ.get("ELEGOO_TOKEN", ""))
    parser.add_argument("--test", action="store_true", help="Send one ON to the board and exit")
    args = parser.parse_args()
    if args.test:
        siren = SerialSiren(args.port_serial)
        try:
            siren.send("ON")
        finally:
            siren.close()
        return
    if not args.token:
        raise SystemExit("Set ELEGOO_TOKEN")
    siren = SerialSiren(args.port_serial)
    server = EventServer((args.listen, args.listen_port), args.token, siren)
    print(f"Elegoo alert listening on {args.port_serial} and {args.listen}:{args.listen_port}", flush=True)
    try:
        server.serve_forever()
    finally:
        siren.close()


if __name__ == "__main__":
    main()
