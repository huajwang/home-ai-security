"""Cloud Link: SNI tunnel, encrypted backup, voice policy, and ICE selection."""

from __future__ import annotations

import asyncio
import os
import ssl
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi.testclient import TestClient

os.environ.setdefault("HUB_VISION_ENABLED", "0")
os.environ.setdefault("HUB_AUDIO_ENABLED", "0")
os.environ.setdefault("HUB_DOORBELL_ENABLED", "0")
os.environ.setdefault("HUB_TALKBACK_ENABLED", "0")
os.environ.setdefault("HUB_MONITOR", "0")
os.environ.setdefault("HUB_PC_CAMERA", "0")

from hub import config
from hub.app import create_app
from hub.cloudlink.backup import build_archive, decrypt_backup, encrypt_backup, load_or_create_key
from hub.cloudlink.dns01 import certbot_args, percent_encode, sign, split_hostname
from hub.cloudlink.settings import peer_host_port
from hub.cloudlink.turn import ice_servers_for_host, uses_cloud_link
from link.app import create_app as create_link_app
from link.voice import decide


def _login(client: TestClient) -> dict:
    res = client.post(
        "/v1/auth/login",
        json={
            "username": "owner",
            "password": "changeme",
            "device_name": "cloud-link",
            "device_role": "phone",
        },
    )
    assert res.status_code == 200, res.text
    return res.json()


def test_link_stays_off_until_it_is_configured() -> None:
    with TestClient(create_app()) as client:
        headers = {"Authorization": f"Bearer {_login(client)['access_token']}"}
        body = client.get("/v1/system", headers=headers).json()
        assert body["link"]["enabled"] is False
        assert body["link"]["url"] is None


def test_tailscale_and_lan_calls_do_not_get_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "TURN_HOST", "turn.example")
    monkeypatch.setattr(config, "TURN_SECRET", "secret")
    monkeypatch.setattr(config, "LINK_SUFFIX", ".link.yaojiabuy.com")
    assert ice_servers_for_host("10.0.0.83:8080") == []
    assert ice_servers_for_host("rock-5t.tailff6218.ts.net:8443") == []
    assert uses_cloud_link("link.yaojiabuy.com") is False
    issued = ice_servers_for_host("rock.link.yaojiabuy.com", now=1_700_000_000)
    assert issued[0]["urls"] == "turn:turn.example:3478"
    assert issued[0]["username"].endswith(":home")


def test_create_call_adds_ice_only_for_the_link_hostname(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "TURN_HOST", "turn.example")
    monkeypatch.setattr(config, "TURN_SECRET", "secret")
    monkeypatch.setattr(config, "LINK_SUFFIX", ".link.yaojiabuy.com")
    with TestClient(create_app()) as client:
        headers = {"Authorization": f"Bearer {_login(client)['access_token']}"}
        lan = client.post("/v1/calls", headers={**headers, "host": "10.0.0.83:8080"})
        assert lan.status_code == 200
        assert lan.json()["ice_servers"] == []
        cloud = client.post("/v1/calls", headers={**headers, "host": "rock.link.yaojiabuy.com"})
        assert cloud.status_code == 200
        assert cloud.json()["ice_servers"][0]["urls"].startswith("turn:")


def test_backup_ciphertext_does_not_contain_the_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "BACKUP_KEY_FILE", tmp_path / "backup.key")
    db = tmp_path / "hub.db"
    import sqlite3

    connection = sqlite3.connect(db)
    connection.execute("create table events (label text)")
    connection.execute("insert into events values ('SECRET-SNAPSHOT')")
    connection.commit()
    connection.close()
    shots = tmp_path / "snapshots"
    shots.mkdir()
    (shots / "door.jpg").write_bytes(b"SECRET-SNAPSHOT")
    key = load_or_create_key()
    blob = encrypt_backup(build_archive(db, shots), key)
    assert b"SECRET-SNAPSHOT" not in blob
    plain = decrypt_backup(blob, key)
    assert b"SECRET-SNAPSHOT" in plain


def test_relay_stores_ciphertext_and_refuses_a_bad_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LINK_FERNET_KEYS", "trial-token")
    monkeypatch.setenv("LINK_BACKUP_DIR", str(tmp_path))
    monkeypatch.setenv("LINK_REGION", "cn")
    with TestClient(create_link_app()) as client:
        denied = client.post("/v1/backups/rock.link.yaojiabuy.com", content=b"abc", headers={"Authorization": "Bearer no"})
        assert denied.status_code == 401
        stored = client.post(
            "/v1/backups/rock.link.yaojiabuy.com",
            content=b"ciphertext-not-a-snapshot",
            headers={"Authorization": "Bearer trial-token"},
        )
        assert stored.status_code == 200
        saved = list((tmp_path / "rock.link.yaojiabuy.com").iterdir())
        assert saved[0].read_bytes() == b"ciphertext-not-a-snapshot"
        voice = client.post("/voice/command", json={"action": "light.on", "home": "rock"})
        assert voice.status_code == 503


def test_voice_cannot_unlock_even_in_the_us() -> None:
    for action in ("lock.unlock", "system.disarm", "system.arm", "lock.lock"):
        decision = decide("us", action)
        assert decision.status == 403
    assert decide("cn", "light.on").status == 503
    allowed = decide("ca", "contacts")
    assert allowed.status == 200
    assert allowed.body["path"] == "/v1/contacts"
    us_app_env = os.environ.get("LINK_REGION")
    os.environ["LINK_REGION"] = "us"
    try:
        with TestClient(create_link_app()) as client:
            refused = client.post("/voice/command", json={"action": "lock.unlock"})
            assert refused.status_code == 403
            lights = client.post("/voice/command", json={"action": "light.on"})
            assert lights.status_code == 200
            assert lights.json()["path"] == "/v1/lights/on"
    finally:
        if us_app_env is None:
            os.environ.pop("LINK_REGION", None)
        else:
            os.environ["LINK_REGION"] = us_app_env


def test_dns01_signature_changes_with_the_secret() -> None:
    params = {"Action": "AddDomainRecord", "DomainName": "yaojiabuy.com"}
    assert sign(params, "one") != sign(params, "two")
    assert percent_encode("a b") == "a%20b"
    rr, domain = split_hostname("rock.link.yaojiabuy.com")
    assert rr == "rock.link"
    assert domain == "yaojiabuy.com"
    args = certbot_args("rock.link.yaojiabuy.com")
    assert "dns" in args
    assert args[-1] == "rock.link.yaojiabuy.com"


def test_peer_address_parses_host_and_port(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "LINK_URL", "yaojiabuy.com:443")
    assert peer_host_port() == ("yaojiabuy.com", 443)


def _certificate(hostname: str) -> tuple[bytes, bytes]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=2))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False)
        .sign(key, hashes.SHA256())
    )
    return (
        cert.public_bytes(serialization.Encoding.PEM),
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ),
    )


def test_sni_tunnel_reaches_the_hub_without_reading_the_request() -> None:
    hostname = "rock.link.yaojiabuy.com"
    cert_pem, key_pem = _certificate(hostname)
    seen: list[bytes] = []

    async def scenario() -> None:
        from snitun.client.client_peer import ClientPeer
        from snitun.client.connector import Connector
        from snitun.server.run import SniTunServerSingle
        from snitun.utils.aes import generate_aes_keyset
        from snitun.utils.server import generate_client_token

        cert_file = Path(os.environ["TEMP"]) / "link-test.pem"
        key_file = Path(os.environ["TEMP"]) / "link-test-key.pem"
        cert_file.write_bytes(cert_pem)
        key_file.write_bytes(key_pem)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert_file, key_file)

        async def backend(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            data = await reader.read(1024)
            seen.append(data)
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 4\r\n\r\nping")
            await writer.drain()
            writer.close()

        hub = await asyncio.start_server(backend, "127.0.0.1", 0, ssl=context)
        hub_port = hub.sockets[0].getsockname()[1]
        fernet_key = Fernet.generate_key().decode()
        tunnel = SniTunServerSingle([fernet_key], host="127.0.0.1", port=0)
        await tunnel.start()
        tunnel_port = tunnel._server.sockets[0].getsockname()[1]
        aes_key, aes_iv = generate_aes_keyset()
        token = generate_client_token([fernet_key], timedelta(hours=1), hostname, aes_key, aes_iv)
        peer = ClientPeer("127.0.0.1", tunnel_port)
        await peer.start(Connector("127.0.0.1", hub_port), token, aes_key, aes_iv)
        client_ssl = ssl.create_default_context()
        client_ssl.check_hostname = False
        client_ssl.verify_mode = ssl.CERT_NONE
        reader, writer = await asyncio.open_connection(
            "127.0.0.1",
            tunnel_port,
            ssl=client_ssl,
            server_hostname=hostname,
        )
        writer.write(
            b"GET /health HTTP/1.1\r\nHost: "
            + hostname.encode()
            + b"\r\nAuthorization: Bearer secret-token\r\n\r\n"
        )
        await writer.drain()
        body = await reader.read(200)
        writer.close()
        await peer.stop()
        await tunnel.stop()
        hub.close()
        await hub.wait_closed()
        assert b"ping" in body

    asyncio.run(scenario())
    assert seen and b"secret-token" in seen[0]
