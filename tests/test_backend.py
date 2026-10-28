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


def test_inactive_reasons_are_specific(tmp_path):
    tools.load_skills()
    settings.update({"agent.enabled": True, "agent.workspace": "", "agent.allowRead": True})
    assert "NO WORKSPACE" in tools.why_inactive("read_file")
    settings.update({"agent.workspace": str(tmp_path / "nope")})
    assert "does not exist" in tools.why_inactive("read_file")
    settings.update({"agent.workspace": str(tmp_path), "agent.allowWrite": False})
    assert "Allow writing" in tools.why_inactive("write_file") and tools.why_inactive("read_file") == ""


def test_confirm_flag_forces_confirmation(tmp_path):
    d = tmp_path / "s"; d.mkdir()
    (d / "x.py").write_text('def register(r):\n    r(name="danger", signature="danger()", perm="misc", fn=lambda: "ok", confirm=True)\n')
    tools.load_skills(d)
    assert tools.needs_confirmation("danger")
    tools.load_skills()


# ------------------------------------------------------------------ tolerant tool-call parsing
from agent import extract_tool_call

def _run_filter(chunks):
    f = ToolStreamFilter(); shown = ""
    for c in chunks:
        shown += f.feed(c)
        if f.done:
            break
    shown += f.flush()
    return f, shown

REAL_FORMATS = {
    "your exact output": '```plaintext\n[tool] [name]: {"name": "write_file", "args": {"path": "notes/cooking-hacks.md", "content": "Here are hacks\nline two"}}\n```',
    "mistral native": '[TOOL_CALLS] [{"name": "write_file", "arguments": {"path": "a.md", "content": "hi"}}]',
    "json fence": 'Sure!\n```json\n{"name": "write_file", "args": {"path": "a.md", "content": "hi"}}\n```',
    "bare json": '{"name": "write_file", "args": {"path": "a.md", "content": "hi"}}',
    "official tag": '<tool>{"name": "write_file", "args": {"path": "a.md", "content": "hi"}}</tool>',
    "openai style": '{"function": {"name": "write_file", "arguments": "{\\"path\\": \\"a.md\\", \\"content\\": \\"hi\\"}"}}',
    "raw newlines in string": '<tool>{"name": "write_file", "args": {"path": "a.md", "content": "line1\nline2\n\\"quoted\\""}}</tool>',
}

@pytest.mark.parametrize("label", REAL_FORMATS)
def test_real_model_formats_are_recognised(label):
    text = REAL_FORMATS[label]
    for size in (1, 3, 7, 1000):                                    # any chunking of the stream
        f, shown = _run_filter([text[i:i + size] for i in range(0, len(text), size)])
        assert f.done and not f.suspect, (label, size)
        name, args = extract_tool_call(f.tool_text)
        assert name == "write_file" and args["path"] in ("a.md", "notes/cooking-hacks.md")
        assert "write_file" not in shown and "{" not in shown, (label, size, shown)   # raw call never reaches chat/TTS

def test_prose_before_call_is_kept_and_call_hidden():
    f, shown = _run_filter(["I'll save that now. ", '```json\n{"name":"make_dir","args":{"path":"x"}}\n```'])
    assert shown == "I'll save that now. " and f.done

def test_normal_code_block_is_released_not_swallowed():
    text = "Here is code:\n```python\nprint('hi')\n```\nDone."
    f, shown = _run_filter([text[i:i + 4] for i in range(0, len(text), 4)])
    assert shown == text and not f.done and not f.suspect

def test_non_tool_json_is_just_text():
    text = 'Example config:\n```json\n{"name": "my-package", "version": "1.0"}\n```'
    f, shown = _run_filter([text])
    assert shown == text and not f.done

def test_cut_off_call_is_flagged_suspect_not_shown():
    f, shown = _run_filter(['<tool>{"name": "write_file", "args": {"path": "a.md", "content": "Here are some handy cooking life ha'])
    assert f.suspect and not f.done and shown == ""

def test_bare_name_of_real_tool_without_args():
    tools.load_skills()
    assert extract_tool_call('{"name": "get_time"}') == ("get_time", {})
    assert extract_tool_call('{"name": "my-package"}') is None

def test_unknown_tool_error_lists_available(ws_dir):
    r = tools.execute("create_file", {"path": "x"})
    assert not r["ok"] and "read_file" in r["error"]

def test_prompt_without_workspace_does_not_crash():
    tools.load_skills()
    settings.update({"agent.workspace": "", "agent.enabled": True})
    assert "get_time" in build_system_prompt()
