"""Alexa Smart Home: signed light control, and no lock or alarm actions."""

from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from fastapi.testclient import TestClient

os.environ.setdefault("HUB_VISION_ENABLED", "0")
os.environ.setdefault("HUB_AUDIO_ENABLED", "0")
os.environ.setdefault("HUB_DOORBELL_ENABLED", "0")
os.environ.setdefault("HUB_TALKBACK_ENABLED", "0")
os.environ.setdefault("HUB_MONITOR", "0")
os.environ.setdefault("HUB_PC_CAMERA", "0")

from hub import config
from hub.alexa import signature
from hub.alexa.directives import handle
from hub.app import create_app

_REDIRECT = "https://pitangui.amazon.com/api/skill/link/amzn1.ask.skill.test"
_CERT_URL = "https://s3.amazonaws.com/echo.api/echo-api-cert.pem"


class _Lights:
    def __init__(self) -> None:
        self.calls: list[tuple[bool, str | None]] = []
        self.on = False

    def list_lights(self) -> list[dict[str, str]]:
        return [
            {"ieee": "aa:bb:cc", "name": "Kitchen"},
            {"ieee": "dd:ee:ff", "name": "Kitchen"},
            {"ieee": "b0:ce:18:14:03:68:1a:64", "name": "E11-G13"},
            {"ieee": "b0:ce:18:14:03:68:1a:64", "name": "E11-G13"},
            {"ieee": "a4:c1:38:66:63:5f:14:1f", "name": "TS0044"},
        ]

    def set_on(self, turn_on: bool, ieee: str | None = None) -> dict[str, str]:
        self.calls.append((turn_on, ieee))
        self.on = turn_on
        return {"state": "on" if turn_on else "off"}

    def is_on(self) -> bool:
        return self.on


def _certificate() -> tuple[x509.Certificate, rsa.RSAPrivateKey, bytes]:
    now = datetime.now(timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test-alexa-ca")])
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=2))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_cert_sign=True,
                crl_sign=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    leaf_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "echo-api.amazon.com")])
    leaf = (
        x509.CertificateBuilder()
        .subject_name(leaf_name)
        .issuer_name(ca_name)
        .public_key(leaf_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=2))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("echo-api.amazon.com")]),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_cert_sign=False,
                crl_sign=False,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(leaf_key.public_key()), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    pem = leaf.public_bytes(serialization_pem())
    return ca_cert, leaf_key, pem


def serialization_pem():
    from cryptography.hazmat.primitives import serialization

    return serialization.Encoding.PEM


def test_certificate_url_must_be_amazons() -> None:
    assert signature.certificate_url_allowed(_CERT_URL) is True
    assert signature.certificate_url_allowed("https://s3.us-east-1.amazonaws.com/echo.api/cert.pem") is True
    assert signature.certificate_url_allowed("http://s3.amazonaws.com/echo.api/cert.pem") is False
    assert signature.certificate_url_allowed("https://evil.example/echo.api/cert.pem") is False
    assert signature.certificate_url_allowed("https://s3.amazonaws.com/other/cert.pem") is False


def test_directives_turn_one_light_and_refuse_the_lock() -> None:
    lights = _Lights()
    turned = handle(_directive("Alexa.PowerController", "TurnOn", "aa:bb:cc"), lights)
    assert turned["event"]["header"]["name"] == "Response"
    assert turned["context"]["properties"][0]["value"] == "ON"
    assert lights.calls == [(True, "aa:bb:cc")]
    locked = handle(_directive("Alexa.LockController", "Lock", "aa:bb:cc"), lights)
    assert locked["event"]["header"]["name"] == "ErrorResponse"
    assert locked["event"]["payload"]["type"] == "INVALID_DIRECTIVE"
    armed = handle(_directive("Alexa.SecurityPanelController", "Arm", "panel"), lights)
    assert "cannot unlock" in armed["event"]["payload"]["message"]
    assert lights.calls == [(True, "aa:bb:cc")]
    found = handle({"directive": {"header": {"namespace": "Alexa.Discovery", "name": "Discover"}, "payload": {}}}, lights)
    endpoints = found["event"]["payload"]["endpoints"]
    names = [item["friendlyName"] for item in endpoints]
    assert names == ["Kitchen bbcc", "Kitchen eeff", "E11 G13", "TS0044"]
    assert len({item["endpointId"] for item in endpoints}) == len(endpoints)


def test_unsigned_alexa_post_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _skill(monkeypatch)
    with TestClient(create_app()) as client:
        denied = client.post("/alexa", json={"directive": {"header": {"namespace": "Alexa.Discovery", "name": "Discover"}}})
        assert denied.status_code == 400
        bad_url = client.post(
            "/alexa",
            content=b"{}",
            headers={
                "Signature": "aa",
                "SignatureCertChainUrl": "https://evil.example/echo.api/cert.pem",
            },
        )
        assert bad_url.status_code == 400


def test_forwarder_secret_can_control_a_light_but_not_the_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    _skill(monkeypatch)
    monkeypatch.setattr(config, "ALEXA_FORWARD_SECRET", "forward-secret")
    with TestClient(create_app()) as client:
        lights = _Lights()
        client.app.state.lights = lights
        token, _refresh = _linked_token(client)
        wrong = client.post(
            "/alexa",
            content=json.dumps(_directive("Alexa.Discovery", "Discover", "", token)).encode(),
            headers={"Content-Type": "application/json", "X-Home-Ai-Forwarder": "wrong"},
        )
        assert wrong.status_code == 400
        discovered = client.post(
            "/alexa",
            content=json.dumps(
                {
                    "directive": {
                        "header": {"namespace": "Alexa.Discovery", "name": "Discover", "payloadVersion": "3", "messageId": "1"},
                        "payload": {"scope": {"type": "BearerToken", "token": token}},
                    }
                }
            ).encode(),
            headers={"Content-Type": "application/json", "X-Home-Ai-Forwarder": "forward-secret"},
        )
        assert discovered.status_code == 200
        assert discovered.json()["event"]["payload"]["endpoints"][0]["endpointId"] == "aa:bb:cc"
        turned = client.post(
            "/alexa",
            content=json.dumps(_directive("Alexa.PowerController", "TurnOn", "aa:bb:cc", token)).encode(),
            headers={"Content-Type": "application/json", "X-Home-Ai-Forwarder": "forward-secret"},
        )
        assert turned.status_code == 200
        assert lights.calls == [(True, "aa:bb:cc")]
        locked = client.post(
            "/alexa",
            content=json.dumps(_directive("Alexa.LockController", "Unlock", "aa:bb:cc", token)).encode(),
            headers={"Content-Type": "application/json", "X-Home-Ai-Forwarder": "forward-secret"},
        )
        assert locked.json()["event"]["header"]["name"] == "ErrorResponse"
        assert lights.calls == [(True, "aa:bb:cc")]


def test_signed_discovery_and_light_and_locked_token(monkeypatch: pytest.MonkeyPatch) -> None:
    _skill(monkeypatch)
    ca_cert, leaf_key, pem = _certificate()
    monkeypatch.setattr(signature, "fetch_certificate", lambda _url: pem)
    monkeypatch.setattr(signature, "current_anchors", lambda: [ca_cert])
    with TestClient(create_app()) as client:
        lights = _Lights()
        client.app.state.lights = lights
        token, refresh = _linked_token(client)
        refreshed = client.post(
            "/alexa/oauth/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh,
                "client_id": "alexa-client",
                "client_secret": "alexa-secret",
            },
        )
        assert refreshed.status_code == 200, refreshed.text
        token = refreshed.json()["access_token"]
        discovered = _speak(
            client,
            leaf_key,
            {
                "directive": {
                    "header": {"namespace": "Alexa.Discovery", "name": "Discover", "payloadVersion": "3", "messageId": "1"},
                    "payload": {"scope": {"type": "BearerToken", "token": token}},
                }
            },
        )
        assert discovered.status_code == 200
        endpoints = discovered.json()["event"]["payload"]["endpoints"]
        assert endpoints[0]["endpointId"] == "aa:bb:cc"
        assert "Alexa.LockController" not in json.dumps(endpoints)
        turned = _speak(client, leaf_key, _directive("Alexa.PowerController", "TurnOff", "dd:ee:ff", token))
        assert turned.status_code == 200
        assert turned.json()["context"]["properties"][0]["value"] == "OFF"
        assert lights.calls == [(False, "dd:ee:ff")]
        locked = _speak(client, leaf_key, _directive("Alexa.LockController", "Unlock", "aa:bb:cc", token))
        assert locked.json()["event"]["header"]["name"] == "ErrorResponse"
        assert lights.calls == [(False, "dd:ee:ff")]
        reported = _speak(client, leaf_key, _directive("Alexa", "ReportState", "aa:bb:cc", token))
        assert reported.json()["event"]["header"]["name"] == "StateReport"
        unlock = client.post(
            "/v1/lock/unlock",
            headers={"Authorization": f"Bearer {token}"},
            json={"confirm": True},
        )
        assert unlock.status_code == 403
        arm = client.post("/v1/system/arm", headers={"Authorization": f"Bearer {token}"})
        assert arm.status_code == 403
        phone = client.post(
            "/v1/auth/login",
            json={"username": "owner", "password": "changeme", "device_name": "phone", "device_role": "phone"},
        )
        owner = phone.json()["access_token"]
        armed = client.post("/v1/system/arm", headers={"Authorization": f"Bearer {owner}"})
        assert armed.status_code == 200


def test_account_link_rejects_a_foreign_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    _skill(monkeypatch)
    with TestClient(create_app()) as client:
        foreign = client.get(
            "/alexa/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": "alexa-client",
                "redirect_uri": "https://evil.example/api/skill/link/x",
                "state": "state",
            },
        )
        assert foreign.status_code == 400
        long_state = client.get(
            "/alexa/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": "alexa-client",
                "redirect_uri": _REDIRECT,
                "state": "A" * 1079,
            },
        )
        assert long_state.status_code == 200
        assert "Link Alexa" in long_state.text
        wrong = client.post(
            "/alexa/oauth/authorize",
            data={
                "response_type": "code",
                "client_id": "alexa-client",
                "redirect_uri": _REDIRECT,
                "state": "state",
                "username": "owner",
                "password": "nope",
            },
            follow_redirects=False,
        )
        assert wrong.status_code == 401


def _skill(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "ALEXA_CLIENT_ID", "alexa-client")
    monkeypatch.setattr(config, "ALEXA_CLIENT_SECRET", "alexa-secret")


def _linked_token(client: TestClient) -> str:
    started = client.post(
        "/alexa/oauth/authorize",
        data={
            "response_type": "code",
            "client_id": "alexa-client",
            "redirect_uri": _REDIRECT,
            "state": "state-1",
            "username": "owner",
            "password": "changeme",
        },
        follow_redirects=False,
    )
    assert started.status_code == 302, started.text
    location = started.headers["location"]
    assert location.startswith(_REDIRECT)
    code = location.split("code=", 1)[1].split("&", 1)[0]
    issued = client.post(
        "/alexa/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": "alexa-client",
            "client_secret": "alexa-secret",
            "redirect_uri": _REDIRECT,
        },
    )
    assert issued.status_code == 200, issued.text
    body = issued.json()
    assert body["token_type"] == "bearer"
    assert body["refresh_token"]
    return body["access_token"], body["refresh_token"]


def _speak(client: TestClient, leaf_key: rsa.RSAPrivateKey, payload: dict) -> object:
    body = json.dumps(payload).encode()
    signed = leaf_key.sign(body, padding.PKCS1v15(), hashes.SHA1())
    return client.post(
        "/alexa",
        content=body,
        headers={
            "Content-Type": "application/json",
            "Signature": base64.b64encode(signed).decode(),
            "SignatureCertChainUrl": _CERT_URL,
        },
    )


def _directive(namespace: str, name: str, endpoint_id: str, token: str | None = None) -> dict:
    endpoint: dict = {"endpointId": endpoint_id}
    if token:
        endpoint["scope"] = {"type": "BearerToken", "token": token}
    return {
        "directive": {
            "header": {
                "namespace": namespace,
                "name": name,
                "payloadVersion": "3",
                "messageId": "m",
                "correlationToken": "corr",
            },
            "endpoint": endpoint,
            "payload": {},
        }
    }
