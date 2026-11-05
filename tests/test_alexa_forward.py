"""Alexa Lambda picks the Home Assistant bearer token off the directive."""

from link.alexa_forwarder.lambda_function import directive_token


def test_uses_the_endpoint_scope_token(monkeypatch) -> None:
    monkeypatch.delenv("HA_TOKEN", raising=False)
    event = {"directive": {"endpoint": {"scope": {"token": "from-alexa"}}}}
    assert directive_token(event) == "from-alexa"


def test_falls_back_to_the_long_lived_token(monkeypatch) -> None:
    monkeypatch.setenv("HA_TOKEN", "long-lived")
    assert directive_token({"directive": {}}) == "long-lived"
