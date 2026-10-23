import json
from datetime import datetime

from conftest import drained_steps
from zamp_sdk.capture import capture_step, drain_log_capture, start_log_capture
from zamp_sdk.version import __version__


def test_drained_items_are_json_strings_with_sdk_version_first():
    start_log_capture()
    capture_step({"event": "action", "name": "act"})
    (line,) = drain_log_capture()
    assert isinstance(line, str)
    assert list(json.loads(line)) == ["sdk_version", "event", "name"]
    assert json.loads(line)["sdk_version"] == __version__


def test_a_nested_datetime_is_stringified():
    start_log_capture()
    at = datetime(2026, 1, 2, 3, 4, 5)
    capture_step({"event": "action", "output": {"rows": [{"at": at}]}})
    (step,) = drained_steps()
    assert step["output"] == {"rows": [{"at": str(at)}]}


def test_drain_clears_the_buffer():
    start_log_capture()
    capture_step({"event": "action"})
    assert len(drain_log_capture()) == 1
    assert drain_log_capture() == []


def test_nothing_is_appended_when_capture_is_inactive():
    capture_step({"event": "action"})
    assert drain_log_capture() == []


def test_an_unserializable_step_becomes_a_stand_in_line_without_its_payload():
    start_log_capture()
    cyc: dict = {}
    cyc["self"] = cyc
    capture_step({"event": "action", "name": "act", "input": {"secret": "payload"}, "output": cyc})
    (step,) = drained_steps()
    assert step == {
        "sdk_version": __version__,
        "event": "action",
        "name": "act",
        "capture_error": "ValueError: Circular reference detected",
    }


def test_a_stand_in_log_line_keeps_its_level():
    start_log_capture()
    cyc: list = []
    cyc.append(cyc)
    capture_step({"event": "log", "level": "error", "content": cyc})
    (step,) = drained_steps()
    assert step["event"] == "log"
    assert step["level"] == "error"
    assert "content" not in step


def test_a_stand_in_line_keeps_only_string_fields():
    start_log_capture()
    cyc: dict = {}
    cyc["self"] = cyc
    capture_step({"event": "action", "name": cyc})
    (step,) = drained_steps()
    assert "name" not in step
    assert step["event"] == "action"
