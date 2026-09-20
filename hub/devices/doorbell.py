"""Local doorbell-button listener via ONVIF events (Reolink Visitor topic)."""

from __future__ import annotations

import base64
import hashlib
import os
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any
from urllib.parse import unquote, urlparse
from xml.etree import ElementTree as ET

from hub import config
from hub.notify import EventBus
from hub.storage import Store
from hub.vision.worker import VisionWorker


def camera_login(url: str) -> tuple[str, str, str] | None:
    parsed = urlparse(url)
    if not parsed.hostname or not parsed.username:
        return None
    return parsed.hostname, unquote(parsed.username), unquote(parsed.password or "")


def visitor_state(topic: str, items: dict[str, str]) -> bool | None:
    if "visitor" not in topic.lower():
        return None
    raw = items.get("State") or items.get("IsVisitor") or items.get("LogicalState") or ""
    if raw.lower() == "true":
        return True
    if raw.lower() == "false":
        return False
    return None


def _xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _parse_notification(message: ET.Element) -> tuple[str, dict[str, str]]:
    topic = ""
    items: dict[str, str] = {}
    for elem in message.iter():
        tag = elem.tag.split("}")[-1]
        if tag == "Topic" and elem.text:
            topic = elem.text.strip()
        elif tag == "SimpleItem":
            name = elem.attrib.get("Name", "")
            if name:
                items[name] = elem.attrib.get("Value", "")
    return topic, items


class DoorbellWorker:
    def __init__(self, store: Store, bus: EventBus, vision: VisionWorker) -> None:
        self.store = store
        self.bus = bus
        self.vision = vision
        self.loop = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, loop: Any) -> None:
        self.loop = loop
        url = os.getenv("HUB_CAMERA_URL", config.CAMERA_URL).strip()
        enabled = os.getenv("HUB_DOORBELL_ENABLED")
        if enabled is None:
            enabled = "1" if url else "0"
        if enabled in {"0", "false", "False"}:
            return
        login = camera_login(url)
        if login is None:
            print("Doorbell listener idle (set HUB_CAMERA_URL).")
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            args=login,
            name="doorbell-onvif",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=6)

    def _run(self, host: str, username: str, password: str) -> None:
        print(f"Doorbell listening on ONVIF {host}:{config.ONVIF_PORT}")
        last_visitor: bool | None = None
        while not self._stop.is_set():
            try:
                last_visitor = self._session(host, username, password, last_visitor)
            except Exception as exc:  # noqa: BLE001
                print(f"Doorbell ONVIF error: {type(exc).__name__}")
                self._stop.wait(5)

        print("Doorbell listener stopped.")

    def _session(self, host: str, username: str, password: str, last_visitor: bool | None) -> bool | None:
        client = _OnvifClient(host, config.ONVIF_PORT, username, password)
        address = client.create_pull_point()
        if not address:
            time.sleep(5)
            return last_visitor
        while not self._stop.is_set():
            xml = client.pull_messages(address)
            if xml is None:
                return last_visitor
            for topic, items in client.iter_events(xml):
                state = visitor_state(topic, items)
                if state is None:
                    continue
                if state and last_visitor is not True:
                    self._ring()
                last_visitor = state
        return last_visitor

    def _ring(self) -> None:
        frame = self.vision.latest_bgr()
        snapshot_path = None
        if frame is not None:
            snapshot_path = self.vision._save_snapshot(frame)
        event = self.store.add_event("doorbell", 1.0, snapshot_path)
        print(f"Doorbell pressed event {event['id']}")
        if self.loop is None:
            return
        payload = {
            "type": "doorbell_pressed",
            "event": {
                "id": event["id"],
                "ts": event["ts"],
                "label": event["label"],
                "confidence": event["confidence"],
                "snapshot_url": f"/v1/events/{event['id']}/snapshot" if snapshot_path else None,
            },
        }
        self.bus.publish_threadsafe(self.loop, payload)


class _OnvifClient:
    def __init__(self, host: str, port: int, username: str, password: str) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password

    def create_pull_point(self) -> str | None:
        body = (
            '<tev:CreatePullPointSubscription xmlns:tev="http://www.onvif.org/ver10/events/wsdl">'
            "<tev:InitialTerminationTime>PT300S</tev:InitialTerminationTime>"
            "</tev:CreatePullPointSubscription>"
        )
        xml = self._post("/onvif/event_service", body)
        if xml is None:
            return None
        root = ET.fromstring(xml)
        for elem in root.iter():
            if elem.tag.split("}")[-1] == "Address" and elem.text:
                return elem.text.strip()
        return None

    def pull_messages(self, address: str) -> str | None:
        parsed = urlparse(address)
        path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        action = "http://www.onvif.org/ver10/events/wsdl/PullPointSubscription/PullMessagesRequest"
        extra = f"<wsa:To>{_xml_escape(address)}</wsa:To><wsa:Action>{action}</wsa:Action>"
        body = (
            '<tev:PullMessages xmlns:tev="http://www.onvif.org/ver10/events/wsdl">'
            "<tev:Timeout>PT15S</tev:Timeout>"
            "<tev:MessageLimit>16</tev:MessageLimit>"
            "</tev:PullMessages>"
        )
        return self._post(path, body, action=action, extra_header=extra, timeout=22)

    def iter_events(self, xml: str) -> list[tuple[str, dict[str, str]]]:
        root = ET.fromstring(xml)
        events: list[tuple[str, dict[str, str]]] = []
        for elem in root.iter():
            if elem.tag.split("}")[-1] == "NotificationMessage":
                events.append(_parse_notification(elem))
        return events

    def _token(self) -> str:
        nonce_bytes = os.urandom(16)
        nonce = base64.b64encode(nonce_bytes).decode()
        created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        digest = base64.b64encode(
            hashlib.sha1(nonce_bytes + created.encode() + self.password.encode()).digest()
        ).decode()
        user = _xml_escape(self.username)
        return (
            '<wsse:Security xmlns:wsse="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd" '
            'xmlns:wsu="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd">'
            "<wsse:UsernameToken>"
            f"<wsse:Username>{user}</wsse:Username>"
            '<wsse:Password Type="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest">'
            f"{digest}</wsse:Password>"
            '<wsse:Nonce EncodingType="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary">'
            f"{nonce}</wsse:Nonce>"
            f"<wsu:Created>{created}</wsu:Created>"
            "</wsse:UsernameToken></wsse:Security>"
        )

    def _post(
        self,
        path: str,
        body: str,
        action: str | None = None,
        extra_header: str = "",
        timeout: float = 8,
    ) -> str | None:
        header = self._token() + extra_header
        payload = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" '
            'xmlns:wsa="http://www.w3.org/2005/08/addressing">'
            f"<s:Header>{header}</s:Header><s:Body>{body}</s:Body></s:Envelope>"
        ).encode()
        headers = {"Content-Type": "application/soap+xml; charset=utf-8"}
        if action:
            headers["Content-Type"] = f'application/soap+xml; charset=utf-8; action="{action}"'
            headers["SOAPAction"] = f'"{action}"'
        req = urllib.request.Request(
            f"http://{self.host}:{self.port}{path}",
            data=payload,
            method="POST",
            headers=headers,
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError:
            return None
        except Exception:  # noqa: BLE001
            return None
