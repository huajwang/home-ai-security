"""Cloud Link dialer address parsing, DNS-01 signature, and backup storage."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient

from link.agent import peer_host_port
from link.app import create_app as create_link_app
from link.dns01 import certbot_args, percent_encode, sign, split_hostname


def test_relay_stores_ciphertext_and_refuses_a_bad_token(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LINK_FERNET_KEYS", "trial-token")
    monkeypatch.setenv("LINK_BACKUP_DIR", str(tmp_path))
    monkeypatch.setenv("LINK_REGION", "cn")
    with TestClient(create_link_app()) as client:
        denied = client.post(
            "/v1/backups/rock.link.yaojiabuy.com",
            content=b"abc",
            headers={"Authorization": "Bearer no"},
        )
        assert denied.status_code == 401
        missing = client.post(
            "/voice/command",
            json={"action": "light.on"},
        )
        assert missing.status_code == 404
        stored = client.post(
            "/v1/backups/rock.link.yaojiabuy.com",
            content=b"ciphertext-not-a-snapshot",
            headers={"Authorization": "Bearer trial-token"},
        )
        assert stored.status_code == 200
        saved = list((tmp_path / "rock.link.yaojiabuy.com").iterdir())
        assert saved[0].read_bytes() == b"ciphertext-not-a-snapshot"


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
    assert any("link.dns01" in item for item in args)


def test_peer_address_parses_host_and_port() -> None:
    assert peer_host_port("yaojiabuy.com:443") == ("yaojiabuy.com", 443)
    assert peer_host_port("https://yaojiabuy.com/ignored") == ("yaojiabuy.com", 443)


def test_voice_module_is_gone() -> None:
    assert not Path("link/voice.py").exists()
    assert os.environ.get("LINK_REGION", "cn")
