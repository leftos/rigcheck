import json

import pytest

from rigcheck.discover import discover, memory_dir
from rigcheck.model import DEFAULT_WINDOW, Finding, Severity
from rigcheck.rules import REGISTRY
from support import Workspace, write

_GENERIC = "rule-filename-generic"
_SHAPE = "memory-index-shape"
_REASONING = "prompt-reasoning-extraction"
_PLUGIN = "tools@market"


def _findings(workspace: Workspace, rule_id: str, files: dict[str, str], memory: dict[str, str] | None = None) -> list[Finding]:
    repo = workspace.rig()
    write(repo / "CLAUDE.md", "# Project\n")
    for name, text in files.items():
        write(repo / name, text)
    for name, text in (memory or {}).items():
        write(memory_dir(repo, workspace.home) / name, text)
    return list(REGISTRY[rule_id].check(discover(repo, workspace.home, DEFAULT_WINDOW)))


def _located(findings: list[Finding]) -> list[tuple[int | None, str]]:
    return [(finding.line, finding.message) for finding in findings]


def _install_plugin(workspace: Workspace, files: dict[str, str]) -> None:
    """Install and enable a plugin holding ``files`` in the fake home."""
    install = workspace.home / "plugin-cache" / "tools"
    for name, text in files.items():
        write(install / name, text)
    write(install / ".claude-plugin" / "plugin.json", json.dumps({"name": "tools"}))
    installed = {"version": 2, "plugins": {_PLUGIN: [{"scope": "user", "installPath": str(install)}]}}
    write(workspace.home / ".claude" / "plugins" / "installed_plugins.json", json.dumps(installed))
    write(workspace.home / ".claude" / "settings.json", json.dumps({"enabledPlugins": {_PLUGIN: True}}))


@pytest.mark.parametrize(
    ("path", "fires"),
    [
        (".claude/rules/misc.md", True),
        (".claude/rules/Notes.md", True),
        (".claude/rules/rules2.md", True),
        (".claude/rules/general-1.md", True),
        (".claude/rules/sub/misc.md", True),
        (".claude/rules/testing.md", False),
        (".claude/rules/api-design.md", False),
        (".claude/rules/misc-tools.md", False),
        (".claude/rules/general-purpose-tools.md", False),
    ],
)
def test_generic_name_examples(workspace: Workspace, path: str, fires: bool) -> None:
    name = path.rsplit("/", 1)[-1]
    findings = _findings(workspace, _GENERIC, {path: "# Topic\n\nUse uv.\n"})
    assert _located(findings) == ([(None, f'rule file name "{name}" says nothing about its topic')] if fires else [])


def test_generic_name_fires_for_a_user_rule(workspace: Workspace) -> None:
    write(workspace.home / ".claude" / "rules" / "misc.md", "# Misc\n\nUse uv.\n")
    findings = _findings(workspace, _GENERIC, {})
    assert _located(findings) == [(None, 'rule file name "misc.md" says nothing about its topic')]


def test_generic_name_skips_a_plugin_rule(workspace: Workspace) -> None:
    _install_plugin(workspace, {"rules/misc.md": "# Misc\n\nUse uv.\n"})
    assert _findings(workspace, _GENERIC, {}) == []


def _shape(offending: int, considered: int) -> str:
    return f"{offending} of {considered} index lines are not a one-line entry linking a topic file"


_TOPICS = {"user.md": "User.\n"}


@pytest.mark.parametrize(
    ("index", "expected"),
    [
        ("- [User role](user.md)\n  details on a second line\n", (2, _shape(1, 2))),
        ("Remember to use uv\n", (1, _shape(1, 1))),
        ("- [docs](https://example.com)\n", (1, _shape(1, 1))),
        ("- [User role](user.md)\ndetails right below\n", (2, _shape(1, 2))),
        ("- [a](a.md)\n  more detail\n", (2, _shape(1, 2))),
        ("[Role](user.md) - Rust dev\n[Style](style.md) - terse\n", None),
        ("- [User role](user.md)\n\n  see [more](user.md)\n", None),
        ("<!--\ngenerated\n-->\n- [User role](user.md)\n", None),
        ("~~~\n```\nnot an entry\n```\n~~~\n- [User role](user.md)\n", None),
        ("````\n```\nnot an entry\n```\n````\n- [User role](user.md)\n", None),
        ("Memory\n======\n\n- [User role](user.md)\n", None),
        ("- [User role](user.md) - senior Rust dev\n", None),
        ("# Memory\n\n- [User role](user.md)\n", None),
        ("- [Gone](missing.md)\n", None),
        ("- [User role](user.md)\n\n```\nnot an entry\n```\n", None),
        ("<!-- generated -->\n- [User role](user.md)\n", None),
        ("- [User role](user.md)\n  - [Nested](user.md)\n", None),
    ],
)
def test_index_shape_examples(workspace: Workspace, index: str, expected: tuple[int, str] | None) -> None:
    findings = _findings(workspace, _SHAPE, {}, {"MEMORY.md": index, **_TOPICS})
    assert _located(findings) == ([expected] if expected is not None else [])


def test_index_shape_is_one_finding_per_file_with_the_count(workspace: Workspace) -> None:
    index = "# Memory\n\n- [User role](user.md)\nBare note one\n- [User role](user.md)\nBare note two\n"
    findings = _findings(workspace, _SHAPE, {}, {"MEMORY.md": index, **_TOPICS})
    assert _located(findings) == [(4, _shape(2, 4))]


def test_index_shape_without_a_memory_folder_finds_nothing(workspace: Workspace) -> None:
    assert _findings(workspace, _SHAPE, {}) == []


_PROSE = ".claude/skills/demo/SKILL.md"


def _skill(body: str, description: str = "Demo skill. Use when testing.") -> str:
    return f"---\nname: demo\ndescription: {description}\n---\n\n{body}"


@pytest.mark.parametrize(
    ("line", "phrase"),
    [
        ("Show your reasoning before the answer.", "Show your reasoning"),
        ("Explain your thinking step by step in the response.", "Explain your thinking"),
        ("Transcribe your thoughts.", "Transcribe your thoughts"),
        ("Think out loud.", "Think out loud"),
        ("Walk through your thought process.", "Walk through your thought process"),
        ("Show me your full step-by-step chain-of-thought.", "Show me your full step-by-step chain-of-thought"),
        ("Explain the reasoning behind the fix to the user.", None),
        ("Don't show your reasoning.", None),
        ("Don\N{RIGHT SINGLE QUOTATION MARK}t show your reasoning.", None),
        ("Never think out loud in the answer.", None),
        ("Do not show `show your reasoning` text.", None),
        ("Keep `show your reasoning` out.", None),
        ("Share your thoughts on the design.", None),
        ("Describe your approach.", None),
        ("Reasoning models buffer typography.", None),
        ("If the tests do not pass, show your reasoning.", "show your reasoning"),
        ("Do not guess. Show your reasoning.", "Show your reasoning"),
        ("Don't show your reasoning; think out loud instead.", "think out loud"),
        ("Never explain your thinking in the reply.", None),
        ("Users often think out loud in issues; summarise them.", None),
        ("First, think aloud about the plan.", "think aloud"),
        ("Please think out loud.", "think out loud"),
        ("You must think aloud.", "think aloud"),
    ],
)
def test_reasoning_examples(workspace: Workspace, line: str, phrase: str | None) -> None:
    findings = _findings(workspace, _REASONING, {_PROSE: _skill(f"# Demo\n\n{line}\n")})
    assert _located(findings) == ([(8, f'asks the model to show its reasoning: "{phrase}"')] if phrase is not None else [])


def test_reasoning_skips_frontmatter(workspace: Workspace) -> None:
    findings = _findings(workspace, _REASONING, {_PROSE: _skill("# Demo\n\nUse it.\n", "show your reasoning")})
    assert findings == []


def test_reasoning_reports_each_line_and_checks_instructions(workspace: Workspace) -> None:
    files = {"CLAUDE.md": "# Project\n\nDon't show your reasoning.\n\nAlways show your reasoning.\n\n```\nThink out loud.\n```\n"}
    findings = _findings(workspace, _REASONING, files)
    assert _located(findings) == [(5, 'asks the model to show its reasoning: "show your reasoning"')]


def test_reasoning_checks_memory_topics(workspace: Workspace) -> None:
    topic = "---\nname: style\ntype: feedback\n---\n\nShow your reasoning before answering.\n"
    findings = _findings(workspace, _REASONING, {}, {"MEMORY.md": "- [Style](style.md)\n", "style.md": topic})
    assert [(finding.path.name if finding.path else "", finding.line, finding.message) for finding in findings] == [
        ("style.md", 6, 'asks the model to show its reasoning: "Show your reasoning"')
    ]


def test_reasoning_checks_bundled_reference_files(workspace: Workspace) -> None:
    files = {_PROSE: _skill("# Demo\n\nSee [reference](reference.md).\n"), ".claude/skills/demo/reference.md": "# Reference\n\nThink out loud.\n"}
    findings = _findings(workspace, _REASONING, files)
    assert [(finding.path.name if finding.path else "", finding.line, finding.message) for finding in findings] == [
        ("reference.md", 3, 'asks the model to show its reasoning: "Think out loud"')
    ]


def test_reasoning_skips_a_plugin_skill(workspace: Workspace) -> None:
    _install_plugin(workspace, {"skills/demo/SKILL.md": _skill("# Demo\n\nShow your reasoning.\n")})
    assert _findings(workspace, _REASONING, {}) == []


@pytest.mark.parametrize("rule_id", [_GENERIC, _SHAPE, _REASONING])
def test_registered_as_advice_info(rule_id: str) -> None:
    meta = REGISTRY[rule_id]
    assert (meta.pack, meta.severity) == ("advice", Severity.INFO)
