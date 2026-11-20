import asyncio
import json
import os
from pathlib import Path

import pytest

from zamp_sdk import Checkpoint


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(work)
    monkeypatch.delenv("ZAMP_RERUN_CHAIN_ID", raising=False)
    monkeypatch.delenv("ZAMP_TOOL_CALL_ID", raising=False)
    monkeypatch.setenv("ZAMP_RERUN_CHAIN_ID", "chain-1")


def _files(tmp_path: Path) -> list[Path]:
    directory = tmp_path / "home" / ".agent" / "checkpoints"
    return sorted(directory.iterdir()) if directory.exists() else []


async def test_once_runs_then_skips_on_rerun():
    calls = []

    async def step():
        calls.append(1)
        return {"ids": [1, 2]}

    assert await Checkpoint().once("fetch", step) == {"ids": [1, 2]}
    assert await Checkpoint().once("fetch", step) == {"ids": [1, 2]}  # a re-run builds a new instance
    assert calls == [1]


async def test_once_supports_sync_callables():
    assert await Checkpoint().once("a", lambda: 5) == 5
    assert await Checkpoint().once("a", lambda: 6) == 5


async def test_progress_is_saved_after_each_step(tmp_path):
    cp = Checkpoint()
    await cp.once("one", lambda: 1)

    async def boom():
        raise RuntimeError("stopped")

    with pytest.raises(RuntimeError):
        await cp.once("two", boom)
    assert await Checkpoint().once("one", lambda: 99) == 1
    assert await Checkpoint().once("two", lambda: 2) == 2


async def test_failed_step_is_not_recorded():
    def bad():
        raise RuntimeError("x")

    with pytest.raises(RuntimeError):
        await Checkpoint().once("s", bad)
    assert await Checkpoint().once("s", lambda: "ok") == "ok"


def test_value_is_frozen():
    values = iter([100, 200])
    assert Checkpoint().value("now", lambda: next(values)) == 100
    assert Checkpoint().value("now", lambda: next(values)) == 100


async def test_first_run_returns_the_same_shape_as_a_rerun():
    assert await Checkpoint().once("t", lambda: (1, 2)) == [1, 2]
    assert await Checkpoint().once("t", lambda: (1, 2)) == [1, 2]


async def test_chain_id_wins_over_tool_call_id(monkeypatch):
    monkeypatch.setenv("ZAMP_TOOL_CALL_ID", "call-1")
    await Checkpoint().once("s", lambda: "chain")
    monkeypatch.setenv("ZAMP_RERUN_CHAIN_ID", "chain-2")  # a different run: nothing saved
    assert await Checkpoint().once("s", lambda: "fresh") == "fresh"
    monkeypatch.setenv("ZAMP_RERUN_CHAIN_ID", "chain-1")
    assert await Checkpoint().once("s", lambda: "x") == "chain"


async def test_tool_call_id_is_the_fallback_key(monkeypatch):
    monkeypatch.delenv("ZAMP_RERUN_CHAIN_ID")
    monkeypatch.setenv("ZAMP_TOOL_CALL_ID", "call-1")
    await Checkpoint().once("s", lambda: 1)
    assert await Checkpoint().once("s", lambda: 2) == 1
    monkeypatch.setenv("ZAMP_TOOL_CALL_ID", "call-2")
    assert await Checkpoint().once("s", lambda: 3) == 3


async def test_explicit_key_works_without_env(monkeypatch):
    monkeypatch.delenv("ZAMP_RERUN_CHAIN_ID")
    await Checkpoint(key="mine").once("s", lambda: 1)
    assert await Checkpoint(key="mine").once("s", lambda: 2) == 1


async def test_no_key_runs_without_resuming(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("ZAMP_RERUN_CHAIN_ID")
    calls = []

    def step():
        calls.append(1)
        return len(calls)

    first = Checkpoint()
    assert await first.once("s", step) == 1
    assert await first.once("s", step) == 1
    assert first.value("v", lambda: "x") == "x"
    assert await Checkpoint().once("s", step) == 2
    assert len(calls) == 2
    assert _files(tmp_path) == []
    assert "progress will not be resumed" in capsys.readouterr().out


async def test_write_is_atomic_and_leaves_one_file(tmp_path):
    await Checkpoint().once("a", lambda: 1)
    await Checkpoint().once("b", lambda: 2)
    (path,) = _files(tmp_path)
    assert path.name.startswith(".zamp_checkpoint_") and path.suffix == ".json"
    assert json.loads(path.read_text()) == {"a": 1, "b": 2}


async def test_failed_write_keeps_old_state_and_no_temp_file(tmp_path, monkeypatch):
    await Checkpoint().once("a", lambda: 1)
    (path,) = _files(tmp_path)

    def broken_replace(src, dst):
        raise OSError("disk")

    monkeypatch.setattr(os, "replace", broken_replace)
    with pytest.raises(OSError):
        await Checkpoint().once("b", lambda: 2)
    assert _files(tmp_path) == [path]
    assert json.loads(path.read_text()) == {"a": 1}


async def test_clear_deletes_state(tmp_path):
    cp = Checkpoint()
    await cp.once("a", lambda: 1)
    cp.clear()
    cp.clear()  # idempotent
    assert _files(tmp_path) == []
    assert await Checkpoint().once("a", lambda: 2) == 2


async def test_non_serialisable_result_is_a_clear_error(tmp_path):
    with pytest.raises(TypeError, match="'bad'.*not JSON-serialisable"):
        await Checkpoint().once("bad", lambda: object())
    with pytest.raises(TypeError, match="'bad2'.*not JSON-serialisable"):
        Checkpoint().value("bad2", lambda: {1, 2})
    assert _files(tmp_path) == []


async def test_overlapping_calls_for_one_step_run_it_once():
    calls = []
    release = asyncio.Event()

    async def step():
        calls.append(1)
        await release.wait()
        return len(calls)

    cp = Checkpoint()
    first = asyncio.create_task(cp.once("notify", step))
    second = asyncio.create_task(cp.once("notify", step))
    await asyncio.sleep(0)
    release.set()
    assert await asyncio.gather(first, second) == [1, 1]
    assert calls == [1]


async def test_overlapping_call_retries_after_the_first_fails():
    async def boom():
        await asyncio.sleep(0)
        raise RuntimeError("x")

    cp = Checkpoint()
    first = asyncio.create_task(cp.once("s", boom))
    second = asyncio.create_task(cp.once("s", lambda: "ok"))
    with pytest.raises(RuntimeError):
        await first
    assert await second == "ok"


async def test_file_lands_under_home_agent_checkpoints_not_cwd(tmp_path):
    await Checkpoint().once("a", lambda: 1)
    (path,) = _files(tmp_path)
    assert path.parent == tmp_path / "home" / ".agent" / "checkpoints"
    assert list((tmp_path / "work").iterdir()) == []


async def test_same_key_from_another_cwd_finds_progress(tmp_path, monkeypatch):
    await Checkpoint().once("a", lambda: 1)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert await Checkpoint().once("a", lambda: 2) == 1


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_unwritable_directory_raises_before_any_step_runs(tmp_path):
    directory = tmp_path / "home" / ".agent" / "checkpoints"
    directory.mkdir(parents=True)
    directory.chmod(0o500)
    try:
        with pytest.raises(OSError, match=r"checkpoints is not writable.*No step has run"):
            Checkpoint()
    finally:
        directory.chmod(0o700)


async def test_no_key_mode_writes_nothing(monkeypatch, tmp_path):
    monkeypatch.delenv("ZAMP_RERUN_CHAIN_ID")
    await Checkpoint().once("a", lambda: 1)
    assert not (tmp_path / "home" / ".agent").exists()
    assert list((tmp_path / "work").iterdir()) == []
