"""Verify that a request body was signed by Alexa."""

from __future__ import annotations

import base64
import re
import ssl
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import urlopen

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from cryptography.x509.verification import PolicyBuilder, Store

_CERT_HOST = re.compile(
    r"^(?:s3\.amazonaws\.com|s3\.amazonaws\.com\.cn|s3[.-][a-z0-9-]+\.amazonaws\.com(?:\.cn)?)$",
    re.IGNORECASE,
)
_CACHE: dict[str, bytes] = {}


class SignatureError(Exception):
    """The request is not a signed Alexa request."""


def certificate_url_allowed(url: str) -> bool:
    if not url or any(char in url for char in "\r\n\\"):
        return False
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.username or parts.password:
        return False
    if parts.port not in {None, 443}:
        return False
    host = parts.hostname or ""
    if _CERT_HOST.match(host) is None:
        return False
    return parts.path.startswith("/echo.api/")


def fetch_certificate(url: str) -> bytes:
    cached = _CACHE.get(url)
    if cached is not None:
        return cached
    if not certificate_url_allowed(url):
        raise SignatureError("Certificate URL is not an Alexa signing URL")
    context = ssl.create_default_context()
    with urlopen(url, timeout=5, context=context) as response:  # noqa: S310
        if response.geturl() != url and not certificate_url_allowed(response.geturl()):
            raise SignatureError("Certificate URL redirected away from Alexa")
        pem = response.read(65_536)
    if not pem or len(pem) >= 65_536:
        raise SignatureError("Signing certificate was empty")
    _CACHE[url] = pem
    return pem


def current_anchors() -> list[x509.Certificate]:
    try:
        import certifi
    except ImportError:
        cafile = ssl.get_default_verify_paths().cafile
        if not cafile:
            raise SignatureError("No certificate authority store is available")
        data = Path(cafile).read_bytes()
    else:
        data = Path(certifi.where()).read_bytes()
    return list(x509.load_pem_x509_certificates(data))


def verify_signed_body(
    body: bytes,
    signature_b64: str,
    certificate_pem: bytes,
    anchors: list[x509.Certificate] | None = None,
) -> None:
    try:
        signature = base64.b64decode(signature_b64, validate=True)
        certificates = list(x509.load_pem_x509_certificates(certificate_pem))
    except (ValueError, TypeError) as exc:
        raise SignatureError("Signing certificate could not be read") from exc
    if not certificates or not signature:
        raise SignatureError("Signing certificate could not be read")
    leaf = certificates[0]
    try:
        names = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(
            x509.DNSName
        )
    except x509.ExtensionNotFound as exc:
        raise SignatureError("Signing certificate is not echo-api.amazon.com") from exc
    if "echo-api.amazon.com" not in names:
        raise SignatureError("Signing certificate is not echo-api.amazon.com")
    roots = anchors if anchors is not None else current_anchors()
    store = Store(roots)
    verifier = PolicyBuilder().store(store).build_server_verifier(x509.DNSName("echo-api.amazon.com"))
    extra_chains = [certificates[1:]]
    if len(certificates) > 2:
        extra_chains.append(certificates[1:-1])
    last_error: Exception | None = None
    for extra in extra_chains:
        try:
            verifier.verify(leaf, extra)
            break
        except Exception as exc:  # noqa: BLE001
            last_error = exc
    else:
        raise SignatureError("Signing certificate is not trusted") from last_error
    public_key = leaf.public_key()
    if not isinstance(public_key, RSAPublicKey):
        raise SignatureError("Signing certificate is not an RSA key")
    try:
        public_key.verify(signature, body, padding.PKCS1v15(), hashes.SHA1())
    except InvalidSignature as exc:
        raise SignatureError("Signature does not match the body") from exc


def verify_request(body: bytes, headers: object, anchors: list[x509.Certificate] | None = None) -> None:
    getter = getattr(headers, "get", None)
    if getter is None:
        raise SignatureError("Missing Alexa signature")
    url = getter("signaturecertchainurl") or ""
    signature = getter("signature") or ""
    if not url or not signature:
        raise SignatureError("Missing Alexa signature")
    if not certificate_url_allowed(url):
        raise SignatureError("Certificate URL is not an Alexa signing URL")
    verify_signed_body(body, signature, fetch_certificate(url), anchors)


def clear_certificate_cache() -> None:
    _CACHE.clear()
