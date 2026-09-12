"""Load mkcert material or generate a prototype self-signed certificate."""

from __future__ import annotations

import datetime as dt
import ipaddress
import socket
from pathlib import Path

from hub import config

_LOOPBACK = ipaddress.IPv4Address("127.0.0.1")
_OUR_CN = "home-ai-security-hub"


def local_ipv4s() -> list[ipaddress.IPv4Address]:
    found: list[ipaddress.IPv4Address] = []
    seen: set[ipaddress.IPv4Address] = set()

    def _add(raw: str) -> None:
        try:
            addr = ipaddress.IPv4Address(raw)
        except ValueError:
            return
        if addr.is_loopback or addr.is_link_local or addr.is_multicast or addr.is_unspecified:
            return
        if addr in seen:
            return
        seen.add(addr)
        found.append(addr)

    try:
        import ifaddr

        for adapter in ifaddr.get_adapters():
            for ip in adapter.ips:
                if isinstance(ip.ip, str):
                    _add(ip.ip)
    except Exception:
        pass

    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("8.8.8.8", 80))
        _add(probe.getsockname()[0])
        probe.close()
    except Exception:
        pass

    return found


def advertised_hub_urls() -> list[str]:
    urls = [f"https://127.0.0.1:{config.PORT}", f"https://localhost:{config.PORT}"]
    for addr in local_ipv4s():
        urls.append(f"https://{addr}:{config.PORT}")
    return urls


def ensure_tls_files() -> tuple[Path, Path]:
    config.ensure_dirs()
    if config.CERT_FILE.exists() and config.KEY_FILE.exists():
        if _should_keep_existing(config.CERT_FILE):
            return config.CERT_FILE, config.KEY_FILE
        print(f"Refreshing TLS cert at {config.CERT_FILE} so LAN/Android hostnames match.")
    _write_self_signed(config.CERT_FILE, config.KEY_FILE)
    print(f"Generated self-signed TLS cert at {config.CERT_FILE} (replace with mkcert for Android/Tailscale).")
    return config.CERT_FILE, config.KEY_FILE


def _should_keep_existing(cert_path: Path) -> bool:
    try:
        from cryptography import x509
    except ImportError:
        return True
    try:
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    except Exception:
        return False
    issuer = cert.issuer.rfc4514_string().lower()
    if "mkcert" in issuer:
        return True
    needed = set(local_ipv4s())
    needed.add(_LOOPBACK)
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        have = set(san.get_values_for_type(x509.IPAddress))
    except Exception:
        return False
    return needed <= have


def _write_self_signed(cert_path: Path, key_path: Path) -> None:
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
    except ImportError as exc:
        raise SystemExit(
            "TLS generation needs the 'cryptography' package (pulled in by aiortc). "
            "Or place mkcert files at certs/hub.pem and certs/hub-key.pem."
        ) from exc

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, _OUR_CN)])
    now = dt.datetime.now(dt.timezone.utc)
    names: list[x509.GeneralName] = [
        x509.DNSName("localhost"),
        x509.IPAddress(_LOOPBACK),
    ]
    hostname = socket.gethostname().strip()
    if hostname and hostname.lower() != "localhost":
        names.append(x509.DNSName(hostname))
    for addr in local_ipv4s():
        names.append(x509.IPAddress(addr))
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + dt.timedelta(days=825))
        .add_extension(x509.SubjectAlternativeName(names), critical=False)
        .sign(key, hashes.SHA256())
    )
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    print("TLS SANs: " + ", ".join(str(item.value) for item in names))
