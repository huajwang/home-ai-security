"""Forward an Alexa Smart Home directive to Home Assistant.

Alexa invokes this function directly. Home Assistant accepts the same JSON
when the Authorization bearer is the token from account linking, or the
long-lived token in HA_TOKEN for a one-house skill.
"""

from __future__ import annotations

import json
import os
import urllib.request


def directive_token(event: dict) -> str:
    directive = event.get("directive") or {}
    endpoint = directive.get("endpoint") or {}
    payload = directive.get("payload") or {}
    scope = endpoint.get("scope") or payload.get("grantee") or payload.get("scope") or {}
    token = scope.get("token") if isinstance(scope, dict) else ""
    return token or os.environ.get("HA_TOKEN", "")


def lambda_handler(event, context):
    token = directive_token(event)
    if not token:
        raise RuntimeError("Alexa request has no token and HA_TOKEN is empty")
    body = json.dumps(event).encode("utf-8")
    request = urllib.request.Request(
        os.environ["HUB_URL"],
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=7) as response:
        return json.loads(response.read().decode("utf-8"))
