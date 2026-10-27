"""Run:  cd backend && python -m pytest ../tests -q   (no GPU, no Ollama needed)"""
import asyncio, json, os, sys, tempfile, threading, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import pytest
from config import settings
import tools, history
from agent import ToolStreamFilter, parse_tool_call, build_system_prompt
from tts import SentenceSplitter, clean_for_speech
from llm import pick_model


@pytest.fixture()
def ws_dir(tmp_path):
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "a.md").write_text("hello world\nsecret plan")
    (tmp_path / ".git").mkdir()
    settings.update({"agent.workspace": str(tmp_path), "agent.enabled": True, "agent.allowRead": True,
                     "agent.allowWrite": True, "agent.allowDelete": True})
    return tmp_path


def test_schema_defaults_loaded():
    assert settings.get("llm.model.heavy") == "mistral"
    assert len(settings.defaults) > 100


def test_read_and_list(ws_dir):
    assert "a.md" in tools.execute("list_dir", {"path": "notes"})["result"]
    assert "secret plan" in tools.execute("read_file", {"path": "notes/a.md"})["result"]
    assert "a.md" in tools.execute("search_files", {"pattern": "*.md"})["result"]
    assert "a.md:2" in tools.execute("grep", {"text": "SECRET"})["result"]


def test_sandbox_blocks_escape(ws_dir):
    for p in ["../etc/passwd", "/etc/passwd", "notes/../../x", ".git/config"]:
        r = tools.execute("read_file", {"path": p})
        assert not r["ok"], p


def test_symlink_blocked(ws_dir):
    outside = ws_dir.parent / "outside.txt"
    outside.write_text("x")
    (ws_dir / "link.txt").symlink_to(outside)
    assert not tools.execute("read_file", {"path": "link.txt"})["ok"]


def test_write_delete_permissions(ws_dir):
    assert tools.execute("write_file", {"path": "n/b.txt", "content": "hi"})["ok"]
    assert (ws_dir / "n" / "b.txt").read_text() == "hi"
    settings.update({"agent.allowWrite": False})
    assert not tools.execute("write_file", {"path": "c.txt", "content": "x"})["ok"]
    assert tools.execute("delete_path", {"path": "n/b.txt"})["ok"]
    assert not tools.execute("delete_path", {"path": "."})["ok"]


def test_tool_filter_hides_tool_block():
    f = ToolStreamFilter()
    out = ""
    for chunk in ["Let me look. <to", "ol>{\"name\":\"read_file\",", "\"args\":{\"path\":\"a\"}}</tool> ignored"]:
        out += f.feed(chunk)
    assert out == "Let me look. " and f.done
    assert parse_tool_call(f.tool_text) == ("read_file", {"path": "a"})


def test_tool_filter_plain_text_with_angle():
    f = ToolStreamFilter()
    out = f.feed("5 < 6 and <b") + f.feed("> ok") + f.flush()
    assert out == "5 < 6 and <b> ok" and not f.done


def test_splitter_and_cleaner():
    sp = SentenceSplitter()
    got = sp.feed("Hello there. How are") + sp.feed(" you? Fine!") + sp.flush()
    assert got == ["Hello there.", "How are you?", "Fine!"]
    assert clean_for_speech("**Bold** [link](http://x.y) ```code``` 😀 ok") == "Bold link code omitted. ok"


def test_router():
    settings.update({"llm.mode": "auto"})
    assert pick_model("hi", False)[0] == "fast"
    assert pick_model("please read the file", True)[0] == "heavy"
    assert pick_model(" ".join(["w"] * 30), False)[0] == "mid"
    settings.update({"llm.mode": "mid"})
    assert pick_model("hi", False) == ("mid", "phi")
    settings.update({"llm.mode": "auto"})


def test_history_roundtrip(tmp_path):
    history.init_db(tmp_path)
    history.save_message("s1", "user", "hi there")
    history.save_message("s1", "assistant", "hello", "phi")
    assert [m["role"] for m in history.get_session_messages("s1")] == ["user", "assistant"]
    history.delete_session("s1")
    assert history.get_sessions() == []


def test_system_prompt_lists_only_allowed_tools(ws_dir):
    settings.update({"agent.allowWrite": False, "agent.allowDelete": False})
    p = build_system_prompt()
    assert "read_file" in p and "write_file" not in p and "delete_path" not in p
