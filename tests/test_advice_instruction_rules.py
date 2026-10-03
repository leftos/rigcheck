import pytest

from rigcheck.discover import discover, memory_dir
from rigcheck.model import DEFAULT_WINDOW, Finding
from rigcheck.rules import REGISTRY
from support import Workspace, write


def _findings(workspace: Workspace, rule_id: str, files: dict[str, str]) -> list[Finding]:
    repo = workspace.rig()
    for name, text in files.items():
        write(repo / name, text)
    return list(REGISTRY[rule_id].check(discover(repo, workspace.home, DEFAULT_WINDOW)))


def _located(findings: list[Finding]) -> list[tuple[int | None, str]]:
    return [(finding.line, finding.message) for finding in findings]


def _lines(text: str, count: int) -> str:
    return "".join(f"{text} {number}.\n" for number in range(count))


def test_instructions_long_reports_the_count(workspace: Workspace) -> None:
    findings = _findings(workspace, "instructions-long", {"CLAUDE.md": _lines("Plain line", 201)})
    assert _located(findings) == [(None, "201 lines; Anthropic's guidance is under 200 per instruction file")]


def test_instructions_long_skips_lines_of_a_block_comment(workspace: Workspace) -> None:
    comment = "<!--\n" + "hidden\n" * 8 + "-->\n"
    assert _findings(workspace, "instructions-long", {"CLAUDE.md": _lines("Plain line", 195) + comment}) == []
    findings = _findings(workspace, "instructions-long", {"CLAUDE.md": _lines("Plain line", 195) + comment + _lines("More", 6)})
    assert [finding.message for finding in findings] == ["201 lines; Anthropic's guidance is under 200 per instruction file"]


def test_instructions_long_skips_rule_frontmatter(workspace: Workspace) -> None:
    rule = "---\npaths:\n  - src/**\n  - docs/**\n---\n" + _lines("Rule line", 198)
    assert _findings(workspace, "instructions-long", {"CLAUDE.md": "# Project\n", ".claude/rules/long.md": rule}) == []


def test_emphasis_dense_fires_at_the_first_emphasized_line(workspace: Workspace) -> None:
    lines = ["# Rules", "", "Plain line.", "**IMPORTANT:** run the tests", "You MUST rebase", "If in doubt, ask", "NEVER push", "ALWAYS lint"]
    findings = _findings(workspace, "emphasis-dense", {"CLAUDE.md": "\n".join(lines) + "\n"})
    assert _located(findings) == [(4, "5 of 7 prose lines use all-caps emphasis such as IMPORTANT, MUST or NEVER")]


def test_emphasis_dense_ignores_sentence_case_and_longer_words(workspace: Workspace) -> None:
    text = _lines("Never commit secrets", 5) + _lines("MUSTARD and NEVERLAND", 5)
    assert _findings(workspace, "emphasis-dense", {"CLAUDE.md": text}) == []


def test_emphasis_dense_ignores_code_spans_and_fences(workspace: Workspace) -> None:
    text = _lines("run `NEVER`", 5) + "\n```\n" + _lines("NEVER do this", 5) + "```\n"
    assert _findings(workspace, "emphasis-dense", {"CLAUDE.md": text}) == []


def test_emphasis_dense_needs_five_lines(workspace: Workspace) -> None:
    assert _findings(workspace, "emphasis-dense", {"CLAUDE.md": _lines("You MUST", 4) + _lines("Plain", 6)}) == []


def test_emphasis_dense_needs_five_percent(workspace: Workspace) -> None:
    assert _findings(workspace, "emphasis-dense", {"CLAUDE.md": _lines("You MUST", 5) + _lines("Plain", 115)}) == []
    findings = _findings(workspace, "emphasis-dense", {"CLAUDE.md": _lines("You MUST", 5) + _lines("Plain", 35)})
    assert [finding.message for finding in findings] == ["5 of 40 prose lines use all-caps emphasis such as IMPORTANT, MUST or NEVER"]


def test_emphasis_dense_skips_memory_files(workspace: Workspace) -> None:
    repo = workspace.rig()
    write(memory_dir(repo, workspace.home) / "MEMORY.md", _lines("You MUST", 10))
    assert _findings(workspace, "emphasis-dense", {"CLAUDE.md": "# Project\n"}) == []


def _paragraph(words: int, per_line: int) -> str:
    tokens = [f"word{number}" for number in range(words)]
    return "\n".join(" ".join(tokens[start : start + per_line]) for start in range(0, words, per_line)) + "\n"


def test_instructions_unstructured_reports_a_long_paragraph(workspace: Workspace) -> None:
    text = "# Rules\n\n" + _paragraph(150, 19) + "\n" + "# Next\n\n" + _paragraph(149, 19)
    findings = _findings(workspace, "instructions-unstructured", {"CLAUDE.md": text})
    assert _located(findings) == [(3, "a paragraph of 150 words; split it into bullets under a heading")]


def test_instructions_unstructured_skips_list_items_and_fences(workspace: Workspace) -> None:
    text = "# Rules\n\n- " + _paragraph(300, 300) + "\n```\n" + _paragraph(150, 15) + "```\n"
    assert _findings(workspace, "instructions-unstructured", {"CLAUDE.md": text}) == []


def test_instructions_unstructured_reports_a_file_without_structure(workspace: Workspace) -> None:
    text = "".join(f"Short paragraph {number}.\n\n" for number in range(30))
    findings = _findings(workspace, "instructions-unstructured", {"CLAUDE.md": text})
    assert _located(findings) == [(None, "30 lines with no heading or list")]
    assert _findings(workspace, "instructions-unstructured", {"CLAUDE.md": "## Notes\n\n" + text}) == []


def test_instructions_unstructured_reports_both_problems(workspace: Workspace) -> None:
    findings = _findings(workspace, "instructions-unstructured", {"CLAUDE.md": _paragraph(150, 5)})
    assert _located(findings) == [(1, "a paragraph of 150 words; split it into bullets under a heading"), (None, "30 lines with no heading or list")]


def test_unstructured_skips_pipe_table(workspace: Workspace) -> None:
    rows = "".join(f"| cmd{number} --flag | Runs step number {number} of the build |\n" for number in range(30))
    table = "| Command | Purpose |\n|---|:---:|\n" + rows
    assert _findings(workspace, "instructions-unstructured", {"CLAUDE.md": table}) == []


def test_unstructured_table_after_text_line(workspace: Workspace) -> None:
    rows = "".join(f"| cmd{number} --flag | Runs step number {number} of the build |\n" for number in range(30))
    text = "# Project\n\nCommands:\n| Command | Purpose |\n|---|---|\n" + rows
    assert _findings(workspace, "instructions-unstructured", {"CLAUDE.md": text}) == []


def test_unstructured_reads_short_delimiter_rows(workspace: Workspace) -> None:
    rows = "".join(f"| cmd{number} --flag | Runs step number {number} of the build |\n" for number in range(30))
    assert _findings(workspace, "instructions-unstructured", {"CLAUDE.md": "| Command | Purpose |\n|--|--|\n" + rows}) == []


def test_unstructured_dash_without_pipe_is_not_a_delimiter_row(workspace: Workspace) -> None:
    text = "# Notes\n\nfirst | line\n    -\n" + _paragraph(150, 15)
    findings = _findings(workspace, "instructions-unstructured", {"CLAUDE.md": text})
    assert _located(findings) == [(3, "a paragraph of 154 words; split it into bullets under a heading")]


def test_unstructured_ignores_code_only_file(workspace: Workspace) -> None:
    text = "```\n" + _lines("echo line", 40) + "```\n"
    assert _findings(workspace, "instructions-unstructured", {"CLAUDE.md": text}) == []


def test_unstructured_counts_prose_lines(workspace: Workspace) -> None:
    findings = _findings(workspace, "instructions-unstructured", {"CLAUDE.md": _lines("Short prose", 30)})
    assert _located(findings) == [(None, "30 lines with no heading or list")]
    html = "\n<div>\n" + _lines("markup", 5) + "</div>\n"
    assert _findings(workspace, "instructions-unstructured", {"CLAUDE.md": _lines("Short prose", 29) + html}) == []


def _numbered(count: int, indent: str = "") -> str:
    return "".join(f"{indent}{number}. Step {number}\n" for number in range(1, count + 1))


def test_instructions_long_procedure_reports_the_list(workspace: Workspace) -> None:
    findings = _findings(workspace, "instructions-long-procedure", {"CLAUDE.md": "# Deploy\n\n" + _numbered(8)})
    assert _located(findings) == [(3, "a numbered list of 8 steps loads on every turn")]


def test_instructions_long_procedure_skips_nested_lists(workspace: Workspace) -> None:
    nested_in_step = _numbered(3) + _numbered(5, "   ") + "".join(f"{number}. Step {number}\n" for number in range(4, 8))
    assert _findings(workspace, "instructions-long-procedure", {"CLAUDE.md": "# Deploy\n\n" + nested_in_step}) == []
    nested_in_bullet = "- Deploy\n" + _numbered(9, "  ")
    assert _findings(workspace, "instructions-long-procedure", {"CLAUDE.md": "# Deploy\n\n" + nested_in_bullet}) == []


def test_instructions_long_procedure_skips_path_scoped_rules(workspace: Workspace) -> None:
    rule = "---\npaths:\n  - src/**\n---\n\n" + _numbered(12)
    assert _findings(workspace, "instructions-long-procedure", {"CLAUDE.md": "# Project\n", ".claude/rules/deploy.md": rule}) == []


_POINTER = "points to AGENTS.md in prose; Claude Code reads it only through an @AGENTS.md import"
_AGENTS = {"AGENTS.md": "# Agents\n\nBuild with make.\n"}


@pytest.mark.parametrize(("line", "fires"), [("See `AGENTS.md` for the build commands.", True), ("AGENTS.md is for Codex.", False)])
def test_agents_md_prose_pointer_needs_a_verb(workspace: Workspace, line: str, fires: bool) -> None:
    findings = _findings(workspace, "agents-md-prose-pointer", {"CLAUDE.md": f"# Project\n\n{line}\n", **_AGENTS})
    assert _located(findings) == ([(3, _POINTER)] if fires else [])


def test_agents_md_prose_pointer_skips_fences(workspace: Workspace) -> None:
    text = "# Project\n\n```\nRead AGENTS.md first.\n```\n"
    assert _findings(workspace, "agents-md-prose-pointer", {"CLAUDE.md": text, **_AGENTS}) == []


def test_agents_md_prose_pointer_needs_an_agents_md_beside_the_file(workspace: Workspace) -> None:
    write(workspace.home / ".claude" / "CLAUDE.md", "# Me\n\nRead AGENTS.md first.\n")
    assert _findings(workspace, "agents-md-prose-pointer", {"CLAUDE.md": "# Project\n", **_AGENTS}) == []


def test_agents_md_prose_pointer_looks_above_a_claude_folder(workspace: Workspace) -> None:
    findings = _findings(workspace, "agents-md-prose-pointer", {".claude/CLAUDE.md": "# Project\n\nRead AGENTS.md first.\n", **_AGENTS})
    assert _located(findings) == [(3, _POINTER)]


def test_prose_pointer_silent_when_claude_local_imports_agents_md(workspace: Workspace) -> None:
    files = {"CLAUDE.md": "# Project\n\nRead AGENTS.md first.\n", "CLAUDE.local.md": "# Local\n\n@AGENTS.md\n", **_AGENTS}
    assert _findings(workspace, "agents-md-prose-pointer", files) == []


def test_prose_pointer_silent_when_agents_md_imported_transitively(workspace: Workspace) -> None:
    files = {"CLAUDE.md": "# Project\n\n@docs/setup.md\n\nRead AGENTS.md first.\n", "docs/setup.md": "# Setup\n\n@../AGENTS.md\n", **_AGENTS}
    assert _findings(workspace, "agents-md-prose-pointer", files) == []


def test_prose_pointer_fires_when_other_agents_md_imported(workspace: Workspace) -> None:
    files = {"CLAUDE.md": "# Project\n\n@sub/AGENTS.md\n\nRead AGENTS.md first.\n", "sub/AGENTS.md": "# Sub\n", **_AGENTS}
    assert _located(_findings(workspace, "agents-md-prose-pointer", files)) == [(5, _POINTER)]


def _block(lines: list[str]) -> str:
    return "# Notes\n\n```\n" + "".join(f"{line}\n" for line in lines) + "```\n"


def _tree(count: int) -> list[str]:
    return ["project/"] + [f"├── folder{number}/" for number in range(count - 2)] + ["└── last/"]


def test_dump_ignores_box_diagram(workspace: Workspace) -> None:
    box = ["┌─────┐    ┌────────┐", "│ CLI │──►│ Engine │", "└─────┘    └────────┘"]
    assert _findings(workspace, "instructions-derivable-dump", {"CLAUDE.md": _block(box * 3)}) == []


def test_dump_reports_a_nested_tree(workspace: Workspace) -> None:
    tree = ["project/", "├── src", "│   ├── main.py", "│   └── util.py", "├── docs", "|-- lib", "+-- bin", "`-- a.txt", "└── README.md"]
    findings = _findings(workspace, "instructions-derivable-dump", {"CLAUDE.md": _block(tree)})
    assert _located(findings) == [(4, "a directory tree of 9 lines Claude can list itself")]


def test_instructions_derivable_dump_skips_shell_commands(workspace: Workspace) -> None:
    commands = [f"uv run step{number} --verbose" for number in range(10)]
    assert _findings(workspace, "instructions-derivable-dump", {"CLAUDE.md": _block(commands)}) == []


def test_instructions_derivable_dump_reports_package_json_dependencies(workspace: Workspace) -> None:
    lines = [f'"package-{number}": "^18.2.0",' for number in range(15)]
    findings = _findings(workspace, "instructions-derivable-dump", {"CLAUDE.md": _block(lines)})
    assert _located(findings) == [(4, "a dependency list of 15 lines Claude can read from the manifest")]


@pytest.mark.parametrize(("count", "fires"), [(15, True), (14, False)])
def test_instructions_derivable_dump_needs_fifteen_requirements(workspace: Workspace, count: int, fires: bool) -> None:
    lines = [f"package{number}==2.31.0" for number in range(count)]
    findings = _findings(workspace, "instructions-derivable-dump", {"CLAUDE.md": _block(lines)})
    assert len(findings) == (1 if fires else 0)


def test_instructions_derivable_dump_skips_settings_without_versions(workspace: Workspace) -> None:
    lines = [f"setting-{number} = 150" for number in range(20)]
    assert _findings(workspace, "instructions-derivable-dump", {"CLAUDE.md": _block(lines)}) == []


def test_instructions_derivable_dump_skips_path_scoped_rules(workspace: Workspace) -> None:
    rule = "---\npaths:\n  - src/**\n---\n\n" + _block(_tree(10))
    assert _findings(workspace, "instructions-derivable-dump", {"CLAUDE.md": "# Project\n", ".claude/rules/layout.md": rule}) == []


_HOOK = "a must-happen rule in prose; a hook would enforce it"


@pytest.mark.parametrize(
    ("line", "fires"),
    [
        ("Always run `ruff format` before every commit.", True),
        ("Always run tests before you commit.", True),
        ("After a commit lands, tell the user.", False),
        ("Before committing, think.", False),
        ("Never edit `.env` files.", True),
        ("Do not commit secrets.", True),
        ("Never read process.env directly; use the config module.", False),
        ("Do not edit the secretary module.", False),
        ("Never edit `.env.local`.", True),
        ("Do not commit credentials.", True),
    ],
)
def test_instruction_better_as_hook_examples(workspace: Workspace, line: str, fires: bool) -> None:
    findings = _findings(workspace, "instruction-better-as-hook", {"CLAUDE.md": f"# Rules\n\n{line}\n"})
    assert _located(findings) == ([(3, _HOOK)] if fires else [])


def test_instruction_better_as_hook_skips_fences(workspace: Workspace) -> None:
    text = "# Rules\n\n```\nRun the tests after each edit.\nDo not commit secrets.\n```\n"
    assert _findings(workspace, "instruction-better-as-hook", {"CLAUDE.md": text}) == []


def test_instruction_better_as_hook_skips_path_scoped_rules(workspace: Workspace) -> None:
    rule = "---\npaths:\n  - src/**\n---\n\nRun the tests after each edit.\n"
    assert _findings(workspace, "instruction-better-as-hook", {"CLAUDE.md": "# Project\n", ".claude/rules/tests.md": rule}) == []
