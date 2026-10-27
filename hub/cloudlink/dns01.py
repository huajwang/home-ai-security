"""Aliyun DNS-01 helper for a hub certificate.

Let's Encrypt is contacted only when this module is run as a certbot hook
and Aliyun credentials are present. Tests check the signature, not the CA.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import sys
import urllib.parse
import uuid
from datetime import datetime, timezone

from hub import config

_ENDPOINT = "https://alidns.aliyuncs.com/"


def percent_encode(value: str) -> str:
    return urllib.parse.quote(str(value), safe="~")


def sign(params: dict[str, str], secret: str) -> str:
    """Aliyun RPC signature. `secret` is the access key secret."""
    canonical = "&".join(
        f"{percent_encode(key)}={percent_encode(params[key])}" for key in sorted(params)
    )
    string_to_sign = "GET&" + percent_encode("/") + "&" + percent_encode(canonical)
    digest = hmac.new((secret + "&").encode(), string_to_sign.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def request_params(action: str, extra: dict[str, str], now: datetime | None = None, nonce: str | None = None) -> dict[str, str]:
    if not config.ALIYUN_ACCESS_KEY_ID or not config.ALIYUN_ACCESS_KEY_SECRET:
        raise RuntimeError("Set ALIYUN_ACCESS_KEY_ID and ALIYUN_ACCESS_KEY_SECRET")
    moment = now or datetime.now(timezone.utc)
    params = {
        "AccessKeyId": config.ALIYUN_ACCESS_KEY_ID,
        "Action": action,
        "Format": "JSON",
        "SignatureMethod": "HMAC-SHA1",
        "SignatureNonce": nonce or str(uuid.uuid4()),
        "SignatureVersion": "1.0",
        "Timestamp": moment.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "Version": "2015-01-09",
    }
    params.update(extra)
    params["Signature"] = sign(params, config.ALIYUN_ACCESS_KEY_SECRET)
    return params


def split_hostname(hostname: str) -> tuple[str, str]:
    """Return (rr, domain) for a name under yaojiabuy.com."""
    name = hostname.strip(".").lower()
    parts = name.split(".")
    if len(parts) < 3:
        raise ValueError(f"{hostname} is not under a registrable domain this hook understands")
    return ".".join(parts[:-2]), ".".join(parts[-2:])


def txt_params(hostname: str, value: str) -> dict[str, str]:
    rr, domain = split_hostname(hostname)
    return {"DomainName": domain, "RR": "_acme-challenge." + rr, "Type": "TXT", "Value": value}


def certbot_args(hostname: str) -> list[str]:
    email = config.ACME_EMAIL or "admin@yaojiabuy.com"
    return [
        "certbot",
        "certonly",
        "--manual",
        "--preferred-challenges",
        "dns",
        "--manual-auth-hook",
        f"{sys.executable} -m hub.cloudlink.dns01 auth",
        "--manual-cleanup-hook",
        f"{sys.executable} -m hub.cloudlink.dns01 cleanup",
        "--agree-tos",
        "--non-interactive",
        "--email",
        email,
        "-d",
        hostname,
    ]


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] not in {"auth", "cleanup", "print-sign"}:
        print("usage: python -m hub.cloudlink.dns01 auth|cleanup")
        return 2
    domain = os.environ.get("CERTBOT_DOMAIN", "")
    value = os.environ.get("CERTBOT_VALIDATION", "")
    if args[0] == "print-sign":
        print(sign({"Action": "DescribeDomains"}, config.ALIYUN_ACCESS_KEY_SECRET or "secret"))
        return 0
    if not domain:
        print("CERTBOT_DOMAIN is empty")
        return 2
    action = "AddDomainRecord" if args[0] == "auth" else "DeleteDomainRecord"
    if args[0] == "cleanup":
        print(f"Remove the _acme-challenge TXT record for {domain} in Aliyun DNS after issuance.")
        return 0
    print(f"DNS-01 {action} for {domain}")
    if not config.ALIYUN_ACCESS_KEY_ID:
        print("Aliyun credentials are not set, so the TXT record was not changed.")
        return 1
    import json
    import urllib.request

    params = request_params(action, txt_params(domain, value))
    url = _ENDPOINT + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=30) as response:
        print(json.loads(response.read().decode()).keys())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
