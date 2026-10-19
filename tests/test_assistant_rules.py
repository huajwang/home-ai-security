"""Rule coverage for the questions people actually ask the assistant."""

from __future__ import annotations

import os
from unittest.mock import MagicMock

os.environ["HUB_VISION_ENABLED"] = "0"
os.environ["HUB_AUDIO_ENABLED"] = "0"
os.environ["HUB_DOORBELL_ENABLED"] = "0"
os.environ["HUB_TALKBACK_ENABLED"] = "0"
os.environ["HUB_CAMERA_URL"] = ""
os.environ["HUB_DRIVEWAY_CAMERA"] = ""
os.environ["HUB_MONITOR"] = "0"
os.environ["HUB_PC_CAMERA"] = "0"
os.environ["HUB_DATA_DIR"] = os.path.join(os.path.dirname(__file__), "_tmp_assistant_rules")
os.environ["HUB_OWNER_USERNAME"] = "owner"
os.environ["HUB_OWNER_PASSWORD"] = "changeme"

from hub.ai.assistant import AssistantEngine
from hub.ai.rules import match_rule
from hub.state import HubState
from hub.storage import Store

_SEARCH = (
    "Did anyone come by today?",
    "Does anyone come by today?",
    "Anybody stop by this afternoon?",
    "Has anyone been here?",
    "Who came to the door?",
    "Who was here today?",
    "Any visitors today?",
    "Any cars in the driveway?",
    "Seen anyone at the front door?",
    "今天有人来过吗",
    "有没有人来过",
    "昨天谁来了",
    "车道有车吗",
    "门口有人吗",
    "有没有车来过",
)

_MISS = (
    "Hello",
    "How are you?",
    "Thank you",
    "What's the weather?",
    "你好",
    "现在几点",
    "讲个笑话",
)


def test_search_questions_hit_the_search_rule() -> None:
    for phrase in _SEARCH:
        hit = match_rule(phrase)
        assert hit is not None and hit.tool == "search_events", phrase


def test_other_common_questions_hit_their_rules() -> None:
    lights_on = match_rule("Turn on the lights")
    assert lights_on is not None and lights_on.tool == "control_light" and lights_on.turn_on is True
    lights_off = match_rule("把灯关了")
    assert lights_off is not None and lights_off.turn_on is False
    assert match_rule("开灯") is not None and match_rule("开灯").turn_on is True
    assert match_rule("Is the front door locked?") is not None
    assert match_rule("Is the front door locked?").tool == "device_status"
    assert match_rule("门锁了吗").tool == "device_status"
    assert match_rule("布防了吗").tool == "device_status"
    assert match_rule("Arm the security system").armed is True
    assert match_rule("Alexa, I'm the system.") is None
    assert match_rule("I am the system") is None
    assert match_rule("Alexa, on the system.") is None
    assert match_rule("on the system") is None
    assert match_rule("this armed system").armed is True
    assert match_rule("Is the system armed?").tool == "device_status"
    assert match_rule("Is the system disarmed?").tool == "device_status"
    assert match_rule("disarmed the system").armed is False
    assert match_rule("布防").armed is True
    assert match_rule("撤防").armed is False
    assert match_rule("解除布防").armed is False
    assert match_rule("Give me a security briefing").tool == "security_briefing"
    assert match_rule("今天有什么情况").tool == "security_briefing"
    assert match_rule("what happened yesterday").timeframe == "yesterday"
    assert match_rule("Unlock the front door right now").tool == "guardrail_unlock_blocked"
    assert match_rule("帮我开锁").tool == "guardrail_unlock_blocked"
    assert match_rule("打开灯").tool == "control_light"


def test_small_talk_does_not_hit_a_rule() -> None:
    for phrase in _MISS:
        assert match_rule(phrase) is None, phrase


def test_screenshot_phrase_searches_by_rule(tmp_path) -> None:
    store = Store(tmp_path / "hub.db")
    store.add_event("person", 0.9, None, camera="driveway")
    engine = AssistantEngine({"store": store, "state": HubState()})
    result = engine.process_query("Does anyone come by today?")
    assert result["tool_used"] == "search_events"
    assert result["tool_data"]["routed_by"] == "rule"
    assert result["tool_data"]["matched_count"] >= 1


def test_chinese_today_says_nobody_came_and_names_the_latest(tmp_path) -> None:
    from datetime import datetime, timedelta, timezone

    from hub.ai.tools import search_events_tool

    store = Store(tmp_path / "hub.db")
    with store.cursor() as cur:
        cur.execute(
            "INSERT INTO events(ts, label, confidence, snapshot_path, clip_path, camera, mask_detected) "
            "VALUES(?,?,?,?,?,?,?)",
            ("2026-10-15T23:43:41+00:00", "person", 0.9, None, None, "driveway", 0),
        )
    now = datetime(2026, 10, 16, 21, 36, tzinfo=timezone(timedelta(hours=-4)))
    result = search_events_tool(store, "今天有人来过吗?", now=now)
    assert result["matched_count"] == 0
    assert result["summary"] == "今天没有人来过。最近一次是10月15日 7:43 PM，车道有一个人。"


def test_search_media_links_the_snapshots_named_in_the_answer(tmp_path) -> None:
    from datetime import datetime, timedelta, timezone

    from hub.ai.tools import search_events_tool

    store = Store(tmp_path / "hub.db")
    with store.cursor() as cur:
        for minute in (10, 20, 30, 40):
            cur.execute(
                "INSERT INTO events(ts, label, confidence, snapshot_path, clip_path, camera, mask_detected) "
                "VALUES(?,?,?,?,?,?,?)",
                (
                    f"2026-10-15T23:{minute}:00+00:00",
                    "person",
                    0.9,
                    f"/tmp/snap-{minute}.jpg",
                    None,
                    "driveway",
                    0,
                ),
            )
    now = datetime(2026, 10, 16, 21, 0, tzinfo=timezone(timedelta(hours=-4)))
    result = search_events_tool(store, "昨天车道有人吗?", now=now)
    assert result["matched_count"] == 4
    assert len(result["media"]) == 3
    assert result["media"][0]["snapshot_url"].startswith("/v1/events/")
    assert result["media"][0]["snapshot_url"].endswith("/snapshot")
    assert "snapshot_path" not in result["media"][0]


def test_search_answer_is_the_tool_summary(tmp_path, monkeypatch) -> None:
    def _fail():
        raise AssertionError("search results are not rewritten")

    monkeypatch.setattr("hub.ai.assistant.get_runner", _fail)
    store = Store(tmp_path / "hub.db")
    engine = AssistantEngine({"store": store, "state": HubState()})
    result = engine.process_query("今天有人来过吗?")
    assert result["tool_used"] == "search_events"
    assert result["response"] == "今天没有人来过。"


def test_status_says_disarmed_when_the_system_is_disarmed(monkeypatch) -> None:
    def _fail():
        raise AssertionError("status is not rewritten by the model")

    monkeypatch.setattr("hub.ai.assistant.get_runner", _fail)
    engine = AssistantEngine({"state": HubState()})
    english = engine.process_query("Is system armed?")
    chinese = engine.process_query("系统布防了吗?")
    assert english["tool_used"] == "device_status"
    assert english["response"] == "The system is disarmed."
    assert chinese["response"] == "系统未布防。"


def test_chinese_light_off_runs_the_tool() -> None:
    lights = MagicMock()
    engine = AssistantEngine({"lights": lights, "state": HubState()})
    result = engine.process_query("把灯关了")
    assert result["tool_used"] == "control_light"
    lights.set_on.assert_called_once_with(turn_on=False)
