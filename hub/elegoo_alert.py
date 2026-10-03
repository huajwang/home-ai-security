"""Drive the Elegoo Mega siren from hub events.

The Mega 2560 has no Wi-Fi. It stays on this PC's USB serial port. This
process signs in to the hub, and for each new armed person-at-the-door
event it sends one ON line. Driveway events, a disarmed system, and events
already seen at startup do not sound.

The hub still publishes the phone notice. This does not unlock the door.
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import time
import urllib.error
import urllib.request
from typing import Any


def should_sound(event: dict[str, Any], armed: bool) -> bool:
    """One local burst for a confirmed person at the door, only while armed."""
    if not armed:
        return False
    if event.get("camera") != "door":
        return False
    return event.get("label") == "person"


class AlertDecider:
    """Remember which events already happened so startup does not replay them."""

    def __init__(self) -> None:
        self._seen: set[int] = set()
        self._primed = False
        self._armed = False

    def commands(self, events: list[dict[str, Any]], armed: bool) -> list[str]:
        fresh = [event for event in events if event.get("id") not in self._seen]
        for event in fresh:
            event_id = event.get("id")
            if isinstance(event_id, int):
                self._seen.add(event_id)
        if not self._primed:
            self._primed = True
            self._armed = armed
            return []
        out: list[str] = []
        if self._armed and not armed:
            out.append("OFF")
        if armed:
            for event in fresh:
                if should_sound(event, True):
                    out.append("ON")
        self._armed = armed
        return out


class HubClient:
    def __init__(self, base_url: str, user: str, password: str, insecure: bool) -> None:
        self.base_url = base_url.rstrip("/")
        self.user = user
        self.password = password
        self.token = ""
        ctx = ssl.create_default_context()
        if insecure:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        self._ctx = ctx

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None if body is None else json.dumps(body).encode()
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(self.base_url + path, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, context=self._ctx, timeout=10) as resp:
            return json.loads(resp.read().decode())

    def login(self) -> None:
        payload = self._request(
            "POST",
            "/v1/auth/login",
            {
                "username": self.user,
                "password": self.password,
                "device_name": "elegoo-alert",
                "device_role": "station",
            },
        )
        self.token = payload["access_token"]

    def system(self) -> dict[str, Any]:
        return self._request("GET", "/v1/system")

    def events(self) -> list[dict[str, Any]]:
        return self._request("GET", "/v1/events?limit=20")["events"]


class SerialSiren:
    def __init__(self, port: str, baud: int = 9600) -> None:
        import serial

        self._ser = serial.Serial(port, baud, timeout=1)
        time.sleep(2.0)

    def send(self, command: str) -> None:
        self._ser.write((command + "\n").encode())
        self._ser.flush()

    def close(self) -> None:
        self._ser.close()


def run(port: str, hub_url: str, user: str, password: str, insecure: bool) -> None:
    client = HubClient(hub_url, user, password, insecure)
    client.login()
    siren = SerialSiren(port)
    decider = AlertDecider()
    print(f"Elegoo alert listening on {port}", flush=True)
    try:
        while True:
            try:
                armed = bool(client.system().get("armed"))
                events = client.events()
            except urllib.error.HTTPError as exc:
                if exc.code == 401:
                    client.login()
                    continue
                print(f"Hub request failed: {exc.code}", flush=True)
                time.sleep(2)
                continue
            except (urllib.error.URLError, TimeoutError, OSError):
                print("Hub request failed", flush=True)
                time.sleep(2)
                continue
            for command in decider.commands(events, armed):
                siren.send(command)
                print(command, flush=True)
            time.sleep(1)
    finally:
        siren.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Sound the Elegoo siren for an armed person at the door")
    parser.add_argument("--port", default=os.environ.get("ELEGOO_PORT", "COM6"))
    parser.add_argument("--hub", default=os.environ.get("HUB_URL", "https://10.0.0.83:8443"))
    parser.add_argument("--user", default=os.environ.get("HUB_USER", "owner"))
    parser.add_argument("--password", default=os.environ.get("HUB_PASSWORD", ""))
    parser.add_argument("--insecure", action="store_true", help="Skip TLS verify for the LAN hub certificate")
    parser.add_argument("--test", action="store_true", help="Send one ON to the board and exit")
    args = parser.parse_args()
    if args.test:
        siren = SerialSiren(args.port)
        try:
            siren.send("ON")
            reply = siren._ser.readline().decode(errors="replace").strip()
            print(reply or "no reply", flush=True)
        finally:
            siren.close()
        return
    if not args.password:
        raise SystemExit("Set HUB_PASSWORD or pass --password")
    run(args.port, args.hub, args.user, args.password, args.insecure)


if __name__ == "__main__":
    main()
