import re
from pathlib import Path

import pytest

from rigcheck.discover import memory_dir
from support import Workspace, git_add, run_json, symlink_or_skip, write

FORMAT_RULES = "# Project\n\nDo NOT run bare `dotnet format`. Do NOT pass `-v q`, `--nologo`, or extra flags to `dotnet format`.\n"
FORMATTER = "Always run the formatter before you commit.\n"


def _shown(path: Path, rig: Path, home: Path) -> str:
    return path.relative_to(rig).as_posix() if path.is_relative_to(rig) else "~/" + path.relative_to(home).as_posix()


def _findings(capsys: pytest.CaptureFixture[str], rig: Path, home: Path, target: Path | None = None) -> list[tuple[str, int, str]]:
    _, report = run_json(capsys, target or rig, home)
    return [
        (_shown(Path(finding["path"]), rig, home), finding["line"], finding["message"])
        for finding in report["findings"]
        if finding["rule"] == "duplicate-line"
    ]


def _pair(workspace: Workspace, claude: str, agents: str, agents_name: str = "AGENTS.md") -> Path:
    rig = workspace.rig()
    write(rig / "CLAUDE.md", claude)
    write(rig / agents_name, agents)
    return rig


def test_exact_clause_in_shadowed_agents_md(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    agents = "# Agents\n\n- Do not run bare `dotnet format`; use the configured hooks or project-approved formatting commands from `CLAUDE.md`.\n"
    rig = _pair(workspace, FORMAT_RULES, agents)
    assert _findings(capsys, rig, workspace.home) == [("AGENTS.md", 3, "repeats CLAUDE.md:3")]


def test_near_duplicate_clause(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    agents = "# Agents\n\n- Never pass `-q`, `-v q`, `--nologo`, or extra quieting flags to `dotnet format`.\n"
    rig = _pair(workspace, FORMAT_RULES, agents)
    assert _findings(capsys, rig, workspace.home) == [("AGENTS.md", 3, "nearly repeats CLAUDE.md:3")]


def test_headings_tables_and_fences_skipped(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    shared = (
        "## Build and test the whole solution here\n\n"
        "| Build the whole solution with dotnet build | yes |\n"
        "| --- | --- |\n\n"
        "```bash\ndotnet build the whole solution --no-restore -c Release\n```\n"
    )
    rig = _pair(workspace, "# Project\n\n" + shared, "# Agents\n\n" + shared)
    assert _findings(capsys, rig, workspace.home) == []


def test_short_clause_skipped(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    rig = _pair(workspace, "# Project\n\nRun the tests.\n", "# Agents\n\nRun the tests.\n")
    assert _findings(capsys, rig, workspace.home) == []


def test_low_overlap_not_reported(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    rig = _pair(workspace, "# Project\n\nUse uv for Python projects.\n", "# Agents\n\nUse pnpm for Node projects.\n")
    assert _findings(capsys, rig, workspace.home) == []


def test_same_file_repeat_not_reported(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    rig = workspace.rig()
    write(rig / "CLAUDE.md", "# Project\n\nAlways run the formatter before committing.\n\nAlways run the formatter before committing.\n")
    assert _findings(capsys, rig, workspace.home) == []


def test_length_ratio_bound(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    claude = "# Project\n\nAlways run the formatter first.\n"
    agents = "# Agents\n\nBefore each commit always run the formatter first and then push upstream.\n"
    rig = _pair(workspace, claude, agents)
    assert _findings(capsys, rig, workspace.home) == []


def test_ignored_by_claude_not_compared(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    agents = "# Agents\n\n- Do not run bare `dotnet format`; use the configured hooks.\n"
    rig = _pair(workspace, FORMAT_RULES, agents, agents_name="AGENTS.override.md")
    assert _findings(capsys, rig, workspace.home) == []


def test_user_and_repo_claude_md_not_compared(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    write(workspace.home / ".claude" / "CLAUDE.md", "- Do not run bare `dotnet format` in any repository.\n")
    rig = workspace.rig()
    write(rig / "CLAUDE.md", "# Project\n\nDo not run bare `dotnet format` in any repository.\n")
    assert _findings(capsys, rig, workspace.home) == []


def test_unscoped_rule_compared(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    rig = workspace.rig()
    write(rig / "CLAUDE.md", FORMAT_RULES)
    rule = "---\ndescription: Do not run bare dotnet format\n---\n\n# Formatting\n\n- Do not run bare `dotnet format`.\n"
    write(rig / ".claude" / "rules" / "x.md", rule)
    assert _findings(capsys, rig, workspace.home) == [(".claude/rules/x.md", 7, "repeats CLAUDE.md:3")]


def test_message_quotes_no_text(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    agents = (
        "# Agents\n\n"
        "- Do not run bare `dotnet format`; use the configured hooks.\n"
        "- Never pass `-q`, `-v q`, `--nologo`, or extra quieting flags to `dotnet format`.\n"
    )
    rig = _pair(workspace, FORMAT_RULES, agents)
    messages = [message for _, _, message in _findings(capsys, rig, workspace.home)]
    assert len(messages) == 2
    for message in messages:
        assert re.fullmatch(r"(?:nearly )?repeats CLAUDE\.md:\d+", message)
        assert not {"dotnet", "format", "bare", "nologo"} & set(re.findall(r"[a-z]+", message.casefold()))


def test_symlinked_peer_not_compared(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    rig = workspace.rig()
    write(rig / "CLAUDE.md", FORMAT_RULES)
    symlink_or_skip(rig / "AGENTS.md", "CLAUDE.md")
    assert _findings(capsys, rig, workspace.home) == []


def test_user_rule_and_repo_rule_not_compared(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    write(workspace.home / ".claude" / "rules" / "u.md", FORMATTER)
    rig = workspace.rig()
    write(rig / ".claude" / "rules" / "a.md", FORMATTER)
    assert _findings(capsys, rig, workspace.home) == []


def test_user_rule_repeats_user_claude_md(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    write(workspace.home / ".claude" / "CLAUDE.md", FORMATTER)
    write(workspace.home / ".claude" / "rules" / "u.md", FORMATTER)
    rig = workspace.rig()
    assert _findings(capsys, rig, workspace.home) == [("~/.claude/rules/u.md", 1, "repeats ~/.claude/CLAUDE.md:1")]


def test_user_import_and_repo_claude_md_not_compared(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    write(workspace.home / ".claude" / "CLAUDE.md", "@~/.claude/shared.md\n")
    write(workspace.home / ".claude" / "shared.md", FORMATTER)
    rig = workspace.rig()
    write(rig / "CLAUDE.md", "# Project\n\n" + FORMATTER)
    assert _findings(capsys, rig, workspace.home) == []


def test_memory_repeats_repo_claude_md(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    rig = workspace.rig()
    write(rig / "CLAUDE.md", "# Project\n\n" + FORMATTER)
    index = memory_dir(rig, workspace.home) / "MEMORY.md"
    write(index, "- " + FORMATTER)
    assert _findings(capsys, rig, workspace.home) == [(_shown(index, rig, workspace.home), 1, "repeats CLAUDE.md:3")]


def test_memory_repeats_user_claude_md(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    write(workspace.home / ".claude" / "CLAUDE.md", FORMATTER)
    rig = workspace.rig()
    index = memory_dir(rig, workspace.home) / "MEMORY.md"
    write(index, "- " + FORMATTER)
    assert _findings(capsys, rig, workspace.home) == [(_shown(index, rig, workspace.home), 1, "repeats ~/.claude/CLAUDE.md:1")]


def test_ancestor_claude_md_outside_repo_not_compared_with_repo(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    rig = workspace.rig()
    write(workspace.home / "work" / "CLAUDE.md", "# Parent\n\n" + FORMATTER)
    write(rig / "CLAUDE.md", "# Project\n\n" + FORMATTER)
    assert _findings(capsys, rig, workspace.home) == []


def test_ancestor_claude_md_compared_with_user_claude_md(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    write(workspace.home / ".claude" / "CLAUDE.md", FORMATTER)
    rig = workspace.rig()
    write(workspace.home / "work" / "CLAUDE.md", "# Parent\n\n" + FORMATTER)
    assert _findings(capsys, rig, workspace.home) == [("~/work/CLAUDE.md", 3, "repeats ~/.claude/CLAUDE.md:1")]


def test_claude_local_md_compared_with_user_claude_md(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    write(workspace.home / ".claude" / "CLAUDE.md", FORMATTER)
    rig = workspace.rig()
    write(rig / ".gitignore", "CLAUDE.local.md\n")
    write(rig / "CLAUDE.md", "# Project\n\nShared instructions live here.\n")
    write(rig / "CLAUDE.local.md", "# Local\n\n" + FORMATTER)
    git_add(rig, [".gitignore", "CLAUDE.md"])
    assert _findings(capsys, rig, workspace.home) == [("CLAUDE.local.md", 3, "repeats ~/.claude/CLAUDE.md:1")]


def test_repo_importing_personal_file_not_compared(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    rig = workspace.rig()
    write(rig / "CLAUDE.md", "# Project\n\n" + FORMATTER + "\n@~/.claude/personal.md\n")
    write(workspace.home / ".claude" / "personal.md", FORMATTER)
    assert _findings(capsys, rig, workspace.home) == []


def test_home_repo_agents_md_compared_with_its_claude_md(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    rig = workspace.home / ".claude"
    write(rig / "CLAUDE.md", "# Home\n\n" + FORMATTER)
    write(rig / "AGENTS.md", "# Agents\n\n" + FORMATTER)
    git_add(rig, ["CLAUDE.md", "AGENTS.md"])
    assert _findings(capsys, rig, workspace.home) == [("AGENTS.md", 3, "repeats CLAUDE.md:3")]


def test_shadowed_agents_md_never_reported_against_memory(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    rig = workspace.rig()
    write(rig / "CLAUDE.md", "# Project\n\nUnrelated shared instructions.\n")
    write(rig / "AGENTS.md", "# Agents\n\n" + FORMATTER)
    index = memory_dir(rig, workspace.home) / "MEMORY.md"
    write(index, "- " + FORMATTER)
    assert _findings(capsys, rig, workspace.home) == [(_shown(index, rig, workspace.home), 1, "repeats AGENTS.md:3")]


def test_near_match_not_compared_across_shared_and_local(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    write(workspace.home / ".claude" / "CLAUDE.md", FORMAT_RULES)
    rig = workspace.rig()
    write(rig / "CLAUDE.md", "# Project\n\n- Never pass `-q`, `-v q`, `--nologo`, or extra quieting flags to `dotnet format`.\n")
    assert _findings(capsys, rig, workspace.home) == []


def test_shadowed_parent_agents_md_is_last(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    rig = workspace.rig()
    write(rig / "AGENTS.md", "# Agents\n\n" + FORMATTER)
    write(rig / "sub" / "CLAUDE.md", "# Sub\n\n" + FORMATTER)
    assert _findings(capsys, rig, workspace.home, target=rig / "sub") == [("AGENTS.md", 3, "repeats CLAUDE.md:3")]


def test_setext_heading_skipped(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    shared = "Always run the formatter before you commit\n===\n\nBuild the whole solution before you push\n---\n"
    rig = _pair(workspace, shared, shared)
    assert _findings(capsys, rig, workspace.home) == []


def test_repeated_words_do_not_pass_minimum(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    rig = _pair(workspace, "# Project\n\nRun it, run it, run it.\n", "# Agents\n\nRun it, then run it again.\n")
    assert _findings(capsys, rig, workspace.home) == []


def test_link_destinations_not_tokens(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    url = "https://example.com/a?x=1&y=2&z=3&w=4&v=5"
    claude = f"# Project\n\nSee [docs]({url}).\n\nDocs live at <{url}> today.\n"
    agents = f"# Agents\n\nOpen [it]({url}) now.\n\nPing <{url}> first.\n"
    rig = _pair(workspace, claude, agents)
    assert _findings(capsys, rig, workspace.home) == []
