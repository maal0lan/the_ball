"""
Tools & diagnostics: list installed skills (active/error), reload skills,
and refresh the Ollama model list.

Knowledge doc: ../knowledge/skills/tools_diagnostics.md
"""
import asyncio

import tools
from llm import ollama


def tools_list_skills() -> str:
    skills = tools.list_skills()
    if not skills:
        return "No tools registered."
    lines = [f"{len(skills)} tool(s):"]
    for s in skills:
        if "error" in s:
            lines.append(f"✗ {s['name']}: {s['error']}")
        else:
            mark = "●" if s["active"] else "○"
            lines.append(f"{mark} {s['name']}  [{s['perm']}, {s['source']}]  {s['signature']}")
    return "\n".join(lines)


def tools_reload_skills() -> str:
    n = tools.load_skills()
    return f"Reloaded skills: {n} tool(s) from {tools.skills_dir()}"


def models_refresh() -> str:
    models = asyncio.run(ollama.list_models())
    if not models:
        return "No Ollama models found — is `ollama serve` running and at least one model pulled?"
    return f"{len(models)} model(s):\n" + "\n".join(models)


def register(register_tool):
    register_tool(name="tools_list_skills",
                  signature="tools_list_skills()   # list every registered tool and its state",
                  perm="misc", fn=tools_list_skills,
                  describe=lambda a: "Listing registered skills and tools")
    register_tool(name="tools_reload_skills",
                  signature="tools_reload_skills()   # reload all backend/skills/*.py files",
                  perm="misc", fn=tools_reload_skills,
                  describe=lambda a: "Reloading skill files")
    register_tool(name="models_refresh",
                  signature="models_refresh()   # refresh the Ollama model list",
                  perm="misc", fn=models_refresh,
                  describe=lambda a: "Refreshing the Ollama model list")
