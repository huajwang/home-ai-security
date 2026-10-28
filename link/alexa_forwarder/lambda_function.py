"""Forward an Alexa Smart Home directive to the hub.

Alexa invokes this function directly, so the request has no Alexa HTTPS
signature. The hub accepts it only when the shared forwarder secret matches.
"""

from __future__ import annotations

import json
import os
import urllib.request


def lambda_handler(event, context):
    body = json.dumps(event).encode("utf-8")
    request = urllib.request.Request(
        os.environ["HUB_URL"],
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Home-Ai-Forwarder": os.environ["FORWARD_SECRET"],
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=7) as response:
        return json.loads(response.read().decode("utf-8"))
