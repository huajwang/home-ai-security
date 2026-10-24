"""Tasks and the knowledge library stay structured without a live model."""

from hub.library.store import Library, search_notes
from hub.print.job import lp_command, uri_from_avahi
from hub.tasks.store import TaskLog, normalize_task, strip_command


def test_strip_command_keeps_the_item() -> None:
    assert strip_command("remind me to buy batteries on Saturday") == "buy batteries on Saturday"
    assert strip_command("add milk to the shopping list") == "milk"
    assert "门锁电池" in strip_command("提醒我周六买门锁电池")


def test_task_uses_the_model_when_it_answers(tmp_path) -> None:
    def chat(messages, max_new_tokens=80, timeout=25.0):
        return "TEXT: 买两节金霸王电池\nDUE: 周六"

    item = TaskLog(tmp_path).add("reminder", "提醒我周六买电池", chat)
    assert item["text"] == "买两节金霸王电池"
    assert item["due"] == "周六"
    assert item["done"] is False
    assert TaskLog(tmp_path).mark_done(item["id"])["done"] is True
    assert TaskLog(tmp_path).list_open() == []


def test_task_keeps_the_spoken_text_when_the_model_is_empty(tmp_path) -> None:
    text, due = normalize_task("remind me to buy milk tomorrow", lambda *args, **kwargs: "")
    assert text == "buy milk tomorrow"
    assert due.lower() == "tomorrow"
    saved = TaskLog(tmp_path).add("shopping", "购物清单 买牛奶", lambda *args, **kwargs: "")
    assert "牛奶" in saved["text"]


def test_library_search_matches_chinese_inside_the_note(tmp_path) -> None:
    library = Library(tmp_path)
    library.add_text("周六更换门锁电池，品牌用金霸王。", "门锁", chat=None)
    library.add_text("周日检查车道摄像头。", "摄像头", chat=None)
    found = search_notes(library.list_notes(), "金霸王")
    assert len(found) == 1
    assert found[0]["title"] == "门锁"
    assert library.search("没有的内容") == []


def test_dictation_joins_chunks_and_an_empty_one_is_not_saved(tmp_path) -> None:
    library = Library(tmp_path)
    library.start_dictation()
    library.add_chunk("门锁电池用金霸王。")
    library.add_chunk("摄像头继续用现在这一台。")
    saved = library.finish_dictation(lambda *args, **kwargs: "门锁和摄像头")
    assert saved["had_note"] is True
    assert saved["title"] == "门锁和摄像头"
    assert "金霸王" in saved["body"]
    again = Library(tmp_path)
    again.start_dictation()
    empty = again.finish_dictation(lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("empty")))
    assert empty["state"] == "empty"


def test_picture_is_stored_beside_the_note(tmp_path) -> None:
    library = Library(tmp_path)
    note = library.add_text("炉子滤芯尺寸。", "滤芯", chat=None)
    updated = library.add_picture(note["id"], "filter.png", b"png-bytes")
    assert updated["pictures"] == ["1.png"]
    assert library.picture_path(note["id"], "1.png").read_bytes() == b"png-bytes"


def test_printer_uri_comes_from_the_named_service() -> None:
    sample = (
        '=;wlan0;IPv4;Other Printer;_ipp._tcp;local;other.local;10.0.0.20;631;"rp=ipp/print"\n'
        '=;wlan0;IPv4;ET788C77E2BF92;_ipp._tcp;local;epson.local;10.0.0.55;631;"rp=ipp/print"\n'
    )
    assert uri_from_avahi(sample, "ET788C77E2BF92") == "ipp://10.0.0.55:631/ipp/print"
    command = lp_command(__import__("pathlib").Path("note.png"), "ET788C77E2BF92", "ipp://10.0.0.136:631/ipp/print")
    assert command[:3] == ["lp", "-d", "ET788C77E2BF92"]
