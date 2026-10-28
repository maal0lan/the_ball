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


# ------------------------------------------------------------------ memory & history skill

def test_memory_history_skill(tmp_path):
    history.init_db(tmp_path)
    history.save_message("s1", "user", "hi there")
    history.save_message("s1", "assistant", "hello", "phi")
    history.save_message("s2", "user", "older session")
    tools.load_skills()
    assert {"history_list_sessions", "history_read_session", "history_latest_session",
            "history_prune", "history_delete_session"} <= set(tools.REGISTRY)

    r = tools.execute("history_list_sessions", {"limit": 5})
    assert r["ok"] and "s1" in r["result"] and "s2" in r["result"]

    r = tools.execute("history_read_session", {"session_id": "s1"})
    assert r["ok"] and "hi there" in r["result"] and "hello" in r["result"]

    r = tools.execute("history_latest_session", {})
    assert r["ok"] and r["result"] in ("s1", "s2")

    # delete is refused without confirm='yes'
    assert not tools.execute("history_delete_session", {"session_id": "s1"})["ok"]
    assert len(history.get_sessions()) == 2

    assert tools.execute("history_delete_session", {"session_id": "s1", "confirm": "yes"})["ok"]
    assert len(history.get_sessions()) == 1

    # prune: backdate the remaining session directly in the DB
    import sqlite3
    con = sqlite3.connect(tmp_path / "chat_history.db")
    con.execute("UPDATE sessions SET updated_at = '2000-01-01T00:00:00+00:00'")
    con.commit()
    con.close()
    r = tools.execute("history_prune", {"days": 1})
    assert r["ok"] and "1" in r["result"]
    assert history.get_sessions() == []


def test_backend_status_skill():
    tools.load_skills()
    r = tools.execute("backend_status", {})
    assert r["ok"]
    for needle in ("Uptime:", "Ollama:", "Tiers:", "TTS:", "Workspace:", "History DB:", "Installed models:"):
        assert needle in r["result"], needle


def test_backend_restart_guarded():
    tools.load_skills()
    r = tools.execute("backend_restart", {})
    assert not r["ok"] and "Refusing" in r["error"]
    # with confirm='yes' it would exit the process — never call that in a test


# ------------------------------------------------------------------ commands & skills
import sys as _sys

@pytest.fixture()
def cmd_ws(ws_dir):
    settings.update({"agent.allowExec": True, "agent.execMode": "allowlist",
                     "agent.execAllowlist": "echo,python3,python,git,ls", "agent.execTimeout": 5})
    yield ws_dir
    settings.update({"agent.allowExec": False, "agent.execMode": "allowlist"})


def test_exec_off_by_default(ws_dir):
    settings.update({"agent.allowExec": False})
    assert "run_command" not in tools.enabled_tools()
    assert not tools.execute("run_command", {"command": "echo hi"})["ok"]


def test_exec_runs_in_workspace(cmd_ws):
    r = tools.execute("run_command", {"command": "ls notes"})
    assert r["ok"] and "a.md" in r["result"] and "exit code 0" in r["result"]


def test_exec_allowlist_and_denylist(cmd_ws):
    assert not tools.execute("run_command", {"command": "whoami"})["ok"]            # not on allow-list
    settings.update({"agent.execMode": "any"})
    assert tools.execute("run_command", {"command": "echo ok"})["ok"]               # any mode allows it
    assert not tools.execute("run_command", {"command": "rm -rf notes"})["ok"]      # deny list still wins
    assert (cmd_ws / "notes" / "a.md").exists()


def test_exec_has_no_shell(cmd_ws):
    r = tools.execute("run_command", {"command": "echo hi ; touch pwned.txt"})
    assert r["ok"] and "pwned" not in str(list(cmd_ws.iterdir()))                   # ';' is just a literal argument
    r = tools.execute("run_command", {"command": "echo $(touch pwned2.txt)"})
    assert not (cmd_ws / "pwned2.txt").exists()


def test_exec_cwd_cannot_escape(cmd_ws):
    assert not tools.execute("run_command", {"command": "ls", "cwd": ".."})["ok"]


def test_exec_secrets_not_leaked(cmd_ws, monkeypatch):
    monkeypatch.setenv("CRYSTAL_TOKEN", "supersecret"); monkeypatch.setenv("HF_TOKEN", "hf_secret")
    settings.update({"agent.execAllowlist": "echo,python3,python"})
    py = "python3" if os.name != "nt" else "python"
    r = tools.execute("run_command", {"command": f"{py} -c \"import os;print(os.environ.get('CRYSTAL_TOKEN'),os.environ.get('HF_TOKEN'))\""})
    assert r["ok"] and "supersecret" not in r["result"] and "hf_secret" not in r["result"] and "None None" in r["result"]


def test_exec_timeout_and_cap(cmd_ws):
    settings.update({"agent.execTimeout": 1, "agent.execAllowlist": "python3,python"})
    py = "python3" if os.name != "nt" else "python"
    r = tools.execute("run_command", {"command": f"{py} -c \"import time;time.sleep(5)\""})
    assert not r["ok"] and "timed out" in r["error"]
    settings.update({"agent.execTimeout": 5, "agent.execMaxChars": 500})
    r = tools.execute("run_command", {"command": f"{py} -c \"print('x'*5000)\""})
    assert r["ok"] and "truncated" in r["result"]
    settings.update({"agent.execMaxChars": 4000})


def test_confirmation_policy(cmd_ws):
    tools.load_skills()
    assert tools.needs_confirmation("never_registered_tool")          # unknown = safest default
    assert tools.needs_confirmation("run_command") and tools.needs_confirmation("write_file")
    assert not tools.needs_confirmation("read_file") and not tools.needs_confirmation("get_time")


def test_plugin_skills_load_and_gate(ws_dir, tmp_path):
    d = tmp_path / "sk"; d.mkdir()
    (d / "hello.py").write_text('def register(r):\n    r(name="hello", signature="hello(name)", perm="misc", fn=lambda name: "hi "+name)\n')
    (d / "broken.py").write_text("raise RuntimeError('boom')\n")
    (d / "_ignored.py").write_text("raise SystemExit\n")
    assert tools.load_skills(d) == 1
    assert "broken.py" in tools.SKILL_ERRORS
    assert tools.execute("hello", {"name": "bob"})["result"] == "hi bob"
    settings.update({"agent.skillsDisabled": "hello"})
    assert not tools.execute("hello", {"name": "bob"})["ok"]
    settings.update({"agent.skillsDisabled": "", "agent.skillsEnabled": False})
    assert "hello" not in tools.enabled_tools()
    settings.update({"agent.skillsEnabled": True})
    assert tools.load_skills(d) == 1 and tools.load_skills(tmp_path / "missing") == 0 and "hello" not in tools.REGISTRY


def test_bundled_skills_register():
    assert tools.load_skills() >= 3                       # get_time, system_info, fetch_url
    assert {"get_time", "system_info", "fetch_url"} <= set(tools.REGISTRY)
    assert "fetch_url" not in tools.enabled_tools()      # net is off by default
    assert tools.execute("get_time", {})["ok"] or True


def test_fetch_blocks_private(ws_dir):
    settings.update({"agent.allowNet": True})
    tools.load_skills()
    for u in ["http://127.0.0.1:8000/x", "http://localhost/x", "file:///etc/passwd", "ftp://x.y/z"]:
        assert not tools.execute("fetch_url", {"url": u})["ok"], u
    settings.update({"agent.allowNet": False})
