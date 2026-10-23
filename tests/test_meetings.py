"""Meeting notes stay short, and the final minutes come only from those notes."""

from __future__ import annotations

from hub.meetings.session import EMPTY_MINUTES, MeetingLog, parse_minutes


def test_parse_minutes_reads_the_labeled_sections() -> None:
    parsed = parse_minutes(
        "TITLE: Front door plan\n"
        "SUMMARY: We will replace the battery.\n"
        "The lock stays as it is.\n"
        "DECISIONS:\n"
        "- Keep the current lock\n"
        "ACTIONS:\n"
        "- Buy a battery\n"
    )
    assert parsed["title"] == "Front door plan"
    assert "replace the battery" in parsed["summary"]
    assert parsed["decisions"] == ["Keep the current lock"]
    assert parsed["action_items"] == ["Buy a battery"]


def test_parse_minutes_accepts_a_single_markdown_line() -> None:
    parsed = parse_minutes(
        "**TITLE:** Review and Approval of Meeting Minutes "
        "**SUMMARY:** The group agreed to show the minutes on the phone. "
        "**DECISIONS:** - Review the minutes. - Show them on the phone. "
        "**ACTIONS:** - Confirm the phone shows the summary."
    )
    assert parsed["title"] == "Review and Approval of Meeting Minutes"
    assert parsed["summary"] == "The group agreed to show the minutes on the phone."
    assert parsed["decisions"] == ["Review the minutes.", "Show them on the phone."]
    assert parsed["action_items"] == ["Confirm the phone shows the summary."]


def test_chunk_notes_and_final_minutes_use_the_runner(tmp_path) -> None:
    calls: list[str] = []

    def chat(messages, max_new_tokens=120, timeout=30.0):
        system = messages[0]["content"]
        calls.append(system)
        if "fragment" in system:
            return "They agreed to check the driveway camera."
        return (
            "TITLE: Driveway camera\n"
            "SUMMARY: The camera needs a check.\n"
            "DECISIONS:\n"
            "- Check the camera\n"
            "ACTIONS:\n"
            "- Look at yesterday's clips\n"
        )

    log = MeetingLog(tmp_path)
    started = log.start()
    assert started["already"] is False
    added = log.add_chunk("Let's look at the driveway camera tomorrow.", chat)
    assert added["ok"] is True
    assert log.active()["chunks"] == 1
    done = log.finish(chat)
    assert done["title"] == "Driveway camera"
    assert done["action_items"] == ["Look at yesterday's clips"]
    assert log.active() is None
    assert any("fragment" in item for item in calls)
    assert any("TITLE" in item for item in calls)
    saved = (tmp_path / f"{started['id']}.json").read_text(encoding="utf-8")
    assert "driveway camera" in saved


def test_empty_meeting_skips_the_model(tmp_path) -> None:
    def chat(messages, max_new_tokens=120, timeout=30.0):
        raise AssertionError("an empty meeting does not call the model")

    log = MeetingLog(tmp_path)
    log.start()
    done = log.finish(chat)
    assert done["title"] == EMPTY_MINUTES["title"]
    assert done["summary"] == "No speech was captured."
    assert done["decisions"] == []
    assert done["action_items"] == []


def test_finish_tells_the_phone_to_reload(tmp_path) -> None:
    class Bus:
        def __init__(self) -> None:
            self.events = []

        def publish_threadsafe(self, payload) -> None:
            self.events.append(payload)

    bus = Bus()
    log = MeetingLog(tmp_path, bus)
    log.start()
    log.finish(lambda *args, **kwargs: "")
    assert [event["state"] for event in bus.events] == ["recording", "ended"]


def test_spoken_start_and_stop_stay_one_sentence(tmp_path) -> None:
    from hub.ai.assistant import AssistantEngine

    log = MeetingLog(tmp_path)
    engine = AssistantEngine({"meetings": log})
    started = engine.process_query("开始开会")
    assert started["tool_used"] == "start_meeting"
    assert started["response"] == "会议开始了。"
    stopped = engine.process_query("结束开会")
    assert stopped["tool_used"] == "end_meeting"
    assert stopped["response"] == "纪要好了。"
    assert stopped["tool_data"]["title"] == "Empty meeting"
