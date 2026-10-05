import os
from collections.abc import Iterator

import pytest

from rigcheck.discover import discover
from rigcheck.model import DEFAULT_WINDOW, Finding, Kind
from rigcheck.rules import REGISTRY
from rigcheck.rules.skills import bundled_files
from support import Workspace, write

_SKILL = ".claude/skills/demo/SKILL.md"
_REFERENCE = ".claude/skills/demo/reference.md"


def _findings(workspace: Workspace, rule_id: str, files: dict[str, str]) -> list[Finding]:
    repo = workspace.rig()
    for name, text in files.items():
        write(repo / name, text)
    return list(REGISTRY[rule_id].check(discover(repo, workspace.home, DEFAULT_WINDOW)))


def _located(findings: list[Finding]) -> list[tuple[int | None, str]]:
    return [(finding.line, finding.message) for finding in findings]


def _lines(text: str, count: int) -> str:
    return "".join(f"{text} {number}.\n" for number in range(count))


def _skill(body: str, description: str = "Demo skill. Use when testing.") -> str:
    return f"---\nname: demo\ndescription: {description}\n---\n\n{body}"


_THIRD_PERSON = "skill description starts in the first or second person"


@pytest.mark.parametrize(
    ("description", "fires"),
    [
        ("I can help you review code", True),
        ("You can use this to deploy", True),
        ("We generate changelogs", True),
        ("I'm the release helper", True),
        ("I'll draft the notes", True),
        ("Your guide to the build", True),
        ("we'll lint the tree", True),
        ("My notes on deploys", True),
        ("Our release steps", True),
        ("Reviews code for bugs", False),
        ("Use when you need X", False),
        ("Iterates over files", False),
        ("Youtube uploader", False),
        ("Webhook helper", False),
        ("I/O helpers for streams", False),
        ("I.e. a helper", False),
        ("You-tube uploader", False),
    ],
)
def test_third_person_examples(workspace: Workspace, description: str, fires: bool) -> None:
    findings = _findings(workspace, "skill-description-not-third-person", {_SKILL: _skill("# Demo\n", description)})
    assert _located(findings) == ([(3, _THIRD_PERSON)] if fires else [])


def test_third_person_reads_a_folded_quoted_description(workspace: Workspace) -> None:
    text = "---\nname: demo\ndescription: >-\n  'You can use this\n  to deploy'\n---\n\n# Demo\n"
    assert _located(_findings(workspace, "skill-description-not-third-person", {_SKILL: text})) == [(3, _THIRD_PERSON)]


def test_third_person_skips_a_missing_description(workspace: Workspace) -> None:
    assert _findings(workspace, "skill-description-not-third-person", {_SKILL: "---\nname: demo\n---\n\nI can help.\n"}) == []


def test_third_person_checks_commands(workspace: Workspace) -> None:
    command = "---\ndescription: You can deploy with this\n---\n\nDeploy.\n"
    assert _located(_findings(workspace, "skill-description-not-third-person", {".claude/commands/deploy.md": command})) == [(2, _THIRD_PERSON)]


@pytest.mark.parametrize(("count", "fires"), [(500, False), (501, True)])
def test_body_long_threshold(workspace: Workspace, count: int, fires: bool) -> None:
    findings = _findings(workspace, "skill-body-long", {_SKILL: _skill(_lines("Line", count - 1))})
    assert _located(findings) == ([(None, f"SKILL.md body is {count} lines (over 500)")] if fires else [])


def test_body_long_skips_lines_of_a_block_comment(workspace: Workspace) -> None:
    comment = "<!--\n" + "hidden\n" * 8 + "-->\n"
    assert _findings(workspace, "skill-body-long", {_SKILL: _skill(_lines("Line", 499) + comment)}) == []


def test_body_long_skips_reference_files(workspace: Workspace) -> None:
    assert _findings(workspace, "skill-body-long", {_SKILL: _skill("# Demo\n"), _REFERENCE: _lines("Line", 600)}) == []


def _no_toc(count: int) -> str:
    return f"reference file is {count} lines with no table of contents at the top"


def _reference(workspace: Workspace, text: str) -> list[Finding]:
    return _findings(workspace, "skill-reference-no-toc", {_SKILL: _skill("# Demo\n\nSee [reference](reference.md).\n"), _REFERENCE: text})


@pytest.mark.parametrize(("count", "fires"), [(100, False), (101, True)])
def test_no_toc_threshold(workspace: Workspace, count: int, fires: bool) -> None:
    findings = _reference(workspace, _lines("Detail", count))
    assert _located(findings) == ([(1, _no_toc(count))] if fires else [])
    assert all(finding.path is not None and finding.path.name == "reference.md" for finding in findings)


@pytest.mark.parametrize("heading", ["## Contents", "# Table of Contents", "### TOC"])
def test_no_toc_accepts_a_contents_heading(workspace: Workspace, heading: str) -> None:
    assert _reference(workspace, f"# Reference\n\n{heading}\n\n" + _lines("Detail", 101)) == []


def test_no_toc_needs_the_heading_in_the_first_twenty_nonblank_lines(workspace: Workspace) -> None:
    within = "\n".join(f"Intro {number}." for number in range(19)) + "\n\n## Contents\n" + _lines("Detail", 101)
    assert _reference(workspace, within) == []
    late = "\n".join(f"Intro {number}." for number in range(20)) + "\n\n## Contents\n" + _lines("Detail", 101)
    assert _located(_reference(workspace, late)) == [(1, _no_toc(123))]


def test_no_toc_accepts_a_list_of_anchor_links(workspace: Workspace) -> None:
    links = "- [Setup](#setup)\n- [Usage](#usage)\n  1. [Flags](#flags)\n"
    assert _reference(workspace, "# Reference\n\n" + links + _lines("Detail", 101)) == []
    short = "- [Setup](#setup)\n- [Usage](#usage)\n- See [docs](docs.md)\n"
    assert len(_reference(workspace, "# Reference\n\n" + short + _lines("Detail", 101))) == 1


def test_no_toc_skips_lines_of_a_block_comment(workspace: Workspace) -> None:
    comment = "<!--\n" + "hidden\n" * 18 + "-->\n"
    assert _reference(workspace, "# Reference\n" + _lines("Detail", 89) + comment) == []


def test_bundled_files_walks_each_skill_once(workspace: Workspace, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = workspace.rig()
    write(repo / _SKILL, _skill("# Demo\n"))
    write(repo / _REFERENCE, "# Reference\n")
    rig = discover(repo, workspace.home, DEFAULT_WINDOW)
    walked: list[object] = []
    real_walk = os.walk

    def counting_walk(top: str) -> Iterator[tuple[str, list[str], list[str]]]:
        walked.append(top)
        return real_walk(top)

    monkeypatch.setattr(os, "walk", counting_walk)
    skill = next(artifact for artifact in rig.artifacts if artifact.kind is Kind.SKILL)
    first, second = bundled_files(rig, skill), bundled_files(rig, skill)
    assert [path.name for path in first] == ["reference.md"]
    assert second == first
    assert len(walked) == 1


def test_no_toc_skips_non_markdown_files(workspace: Workspace) -> None:
    files = {_SKILL: _skill("# Demo\n\nRun `scripts/run.py`.\n"), ".claude/skills/demo/scripts/run.py": _lines("# line", 200)}
    assert _findings(workspace, "skill-reference-no-toc", files) == []


@pytest.mark.parametrize(
    ("markdown", "shown"),
    [
        ("Run `scripts\\run.py` to start.", "scripts\\run.py"),
        ("Read [the guide](docs\\guide.md).", "docs\\guide.md"),
        ("Edit `.claude\\settings.json` first.", ".claude\\settings.json"),
        ("Open `src\\pkg\\mod.py` first.", "src\\pkg\\mod.py"),
        ("Run `.\\build.ps1`.", ".\\build.ps1"),
        ("Run `.\\dtd.ps1`.", ".\\dtd.ps1"),
        ("Bash is `System32\\bash.exe` here.", None),
        ("Bash is `WindowsApps\\bash.EXE` here.", None),
        ("Run `tools\\setup.cmd` once.", None),
        ("Match `settings\\.json` exactly.", None),
        ("Match `README\\.md` exactly.", None),
        ("Open `HKCU\\Software\\Microsoft` in the registry.", None),
        ("Escape with `\\n`.", None),
        ("Match `\\d+\\.\\d+` versions.", None),
        ("Open `src\\pkg` first.", None),
        ("Install to `C:\\Users\\me\\x.txt`.", None),
        ("Share `\\\\server\\share\\notes.md`.", None),
        ("The `a\\b` pair.", None),
        ("Use `my dir\\file.md` here.", None),
        ("Free prose docs\\guide.md is left alone.", None),
    ],
)
def test_backslash_examples(workspace: Workspace, markdown: str, shown: str | None) -> None:
    findings = _findings(workspace, "skill-backslash-path", {_SKILL: _skill(f"# Demo\n\n{markdown}\n")})
    assert _located(findings) == ([(8, f"path uses backslashes: {shown}")] if shown is not None else [])


def test_backslash_skips_fenced_code(workspace: Workspace) -> None:
    body = "# Demo\n\n```powershell\n.\\build.ps1\nscripts\\run.py\n```\n"
    assert _findings(workspace, "skill-backslash-path", {_SKILL: _skill(body)}) == []


def test_backslash_skips_frontmatter(workspace: Workspace) -> None:
    text = "---\nname: demo\ndescription: Demo.\nargument-hint: '`scripts\\run.py`'\n---\n\n# Demo\n"
    assert _findings(workspace, "skill-backslash-path", {_SKILL: text}) == []


def test_backslash_checks_bundled_markdown_and_commands(workspace: Workspace) -> None:
    files = {
        _SKILL: _skill("# Demo\n\nSee [reference](reference.md).\n"),
        _REFERENCE: "# Reference\n\nRun `tools\\gate.ps1`.\n",
        ".claude/commands/deploy.md": "---\ndescription: Deploys.\n---\n\nRun `bin\\deploy.sh`.\n",
    }
    findings = _findings(workspace, "skill-backslash-path", files)
    located = sorted((finding.path.name if finding.path else "", finding.line, finding.message) for finding in findings)
    assert located == [
        ("deploy.md", 5, "path uses backslashes: bin\\deploy.sh"),
        ("reference.md", 3, "path uses backslashes: tools\\gate.ps1"),
    ]


@pytest.mark.parametrize(
    ("line", "phrase"),
    [
        ("If you're doing this before August 2025, use the old API.", "before August 2025"),
        ("As of Q3 2026 the endpoint moved.", "As of Q3 2026"),
        ("The flag works until 2027.", "until 2027"),
        ("Use this currently.", None),
        ("Works since version 2.1.233.", None),
        ("Run before the 2025 tests.", None),
        ("Deploy after May.", None),
        ("Run `until 2027` in code.", None),
        ("Retry after 2000 ms.", None),
        ("Wait until 1920 pixels render.", None),
        ("It ran well since 2048 jobs ran.", None),
        ("As of Q3 2026, the endpoint moved.", "As of Q3 2026"),
    ],
)
def test_time_sensitive_examples(workspace: Workspace, line: str, phrase: str | None) -> None:
    findings = _findings(workspace, "skill-time-sensitive-text", {_SKILL: _skill(f"# Demo\n\n{line}\n")})
    assert _located(findings) == ([(8, f'time-sensitive text: "{phrase}"')] if phrase is not None else [])


def test_time_sensitive_skips_fences_and_reports_each_line(workspace: Workspace) -> None:
    body = "# Demo\n\n```\nuntil 2027\n```\n\nBefore March 2024 use v1.\nAfter 2026, use v3.\n"
    findings = _findings(workspace, "skill-time-sensitive-text", {_SKILL: _skill(body)})
    assert _located(findings) == [(12, 'time-sensitive text: "Before March 2024"'), (13, 'time-sensitive text: "After 2026"')]


def _agent(name: str, description: str, extra: str = "") -> dict[str, str]:
    return {f".claude/agents/{name}.md": f"---\nname: {name}\ndescription: {description}\n{extra}---\n\nDo the work.\n"}


@pytest.mark.parametrize(
    ("name", "description", "extra", "expected"),
    [
        ("code-reviewer", "Reviews diffs.", "tools: Read, Grep, Edit\n", (4, "agent sounds read-only but can use Edit")),
        ("helper", "Audits configs.", "", (3, "agent sounds read-only but inherits every tool")),
        ("helper", "Explores the codebase.", "tools: [Read, Write, Edit(docs/**)]\n", (4, "agent sounds read-only but can use Write, Edit")),
        ("helper", "Inspects logs.", "disallowedTools: Write\n", (3, "agent sounds read-only but can use Edit, NotebookEdit")),
        ("code-reviewer", "Reviews diffs.", "tools: Read, Grep, Glob\n", None),
        ("code-reviewer", "Reviews diffs.", "tools: Read, Bash\n", None),
        ("linter", "Reviews and fixes lint errors.", "tools: Edit\n", None),
        ("helper", "Implements features.", "", None),
        ("helper", "Audits configs.", "disallowedTools: Write, Edit, NotebookEdit\n", None),
        ("code-reviewer", "Reviews diffs.", "tools: Read, MultiEdit\n", None),
        ("lint-fixer", "Analyzes lint output and patches the files.", "tools: Edit\n", None),
    ],
)
def test_read_only_examples(workspace: Workspace, name: str, description: str, extra: str, expected: tuple[int, str] | None) -> None:
    findings = _findings(workspace, "agent-read-only-has-write-tools", _agent(name, description, extra))
    assert _located(findings) == ([expected] if expected is not None else [])
