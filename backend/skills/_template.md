---
name: my-skill
description: One line telling the model WHEN to use this skill (shown in its prompt, max 160 characters)
---
# Instruction skill template

Copy this file, rename it (no leading underscore), edit, then use
Settings → Tools & diagnostics → "List / reload skills" and click **Trust this skill**.
Files starting with "_" are never loaded. A skill can also be a folder: `my-skill/SKILL.md`.

An instruction skill is plain text the model reads (through `use_skill`) before doing a task. It adds no new
abilities: the model can only use tools you already allow, and every write / delete / command / network call
still needs its normal switch and Allow/Deny click.

Write it as short numbered steps. Small models follow 5–10 clear steps far better than long prose.

1. Say what to look at first (for example: `list_dir` the notes folder).
2. Say what to produce.
3. Say when to stop and ask the user.
