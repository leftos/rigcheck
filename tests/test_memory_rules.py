from rigcheck import engine
from rigcheck.discover import MEMORY_INDEX_BYTES, discover, memory_dir
from rigcheck.model import DEFAULT_WINDOW, Finding
from rigcheck.rules import REGISTRY
from support import Workspace, write


def _findings(workspace: Workspace, files: dict[str, str]) -> list[Finding]:
    repo = workspace.rig()
    write(repo / "CLAUDE.md", "# Project\n")
    memory = memory_dir(repo, workspace.home)
    for name, text in files.items():
        write(memory / name, text)
    findings = engine.run(discover(repo, workspace.home, DEFAULT_WINDOW), REGISTRY.values())
    return [finding for finding in findings if finding.rule_id.startswith("memory-")]


def _topic(frontmatter: str) -> dict[str, str]:
    return {"MEMORY.md": "- [Topic](topic.md)\n", "topic.md": f"---\n{frontmatter}---\nBody.\n"}


def test_metadata_type_is_accepted(workspace: Workspace) -> None:
    assert _findings(workspace, _topic("name: t\nmetadata:\n  type: feedback\n")) == []


def test_top_level_type_is_accepted(workspace: Workspace) -> None:
    assert _findings(workspace, _topic("name: t\ntype: project\n")) == []


def test_missing_type_is_not_a_finding(workspace: Workspace) -> None:
    files = {"MEMORY.md": "- [A](a.md)\n- [B](b.md)\n", "a.md": "---\nname: a\n---\nBody.\n", "b.md": "No frontmatter.\n"}
    assert _findings(workspace, files) == []


def test_conflicting_types_are_one_finding(workspace: Workspace) -> None:
    findings = _findings(workspace, _topic("type: user\nmetadata:\n  type: project\n"))
    assert [(finding.rule_id, finding.message) for finding in findings] == [("memory-type-unknown", "type: user and metadata.type: project disagree")]


def test_lenient_frontmatter_still_reads_metadata_type(workspace: Workspace) -> None:
    assert _findings(workspace, _topic("description: Use when: x breaks\nmetadata:\n  type: user\n")) == []
    findings = _findings(workspace, _topic("description: Use when: x breaks\nmetadata:\n  type: bogus\n"))
    assert [finding.message for finding in findings] == ["metadata.type: bogus is not a documented memory type"]


def test_no_index_means_no_orphans(workspace: Workspace) -> None:
    assert _findings(workspace, {"topic.md": "Details.\n"}) == []


def test_link_with_fragment_resolves(workspace: Workspace) -> None:
    files = {"MEMORY.md": "- [Topic](topic.md#section)\n- [Spaced](my%20notes.md?x=1)\n", "topic.md": "A.\n", "my notes.md": "B.\n"}
    assert _findings(workspace, files) == []


def test_flat_name_is_a_file_link(workspace: Workspace) -> None:
    findings = _findings(workspace, {"MEMORY.md": "- [deploy](deploy.sh)\n"})
    assert [(finding.rule_id, finding.message, finding.line) for finding in findings] == [("memory-link-broken", "deploy.sh does not exist", 1)]


def test_non_path_hrefs_are_not_reported(workspace: Workspace) -> None:
    index = "".join(
        [
            "- [Dashboard](grafana.example.com/d/abc)\n",
            "- [notes](a.md:12)\n",
            "- [call](tel:+15550100)\n",
            "- [call](tel:5550100)\n",
            "- [template](%3Cplaceholder%3E)\n",
            "- [a](a.md#x)\n",
        ]
    )
    assert _findings(workspace, {"MEMORY.md": index, "a.md": "A.\n"}) == []


def test_line_separators_inside_a_line_do_not_count(workspace: Workspace) -> None:
    text = "- entry\N{LINE SEPARATOR}still the entry\fand this\n" * 150
    assert len(text.splitlines()) > 200
    assert _findings(workspace, {"MEMORY.md": text}) == []


def test_index_over_byte_limit_with_few_lines(workspace: Workspace) -> None:
    line = "\N{GREEK SMALL LETTER ALPHA}" * 1_000 + "\n"
    text = line * (MEMORY_INDEX_BYTES // len(line.encode("utf-8")) + 1)
    findings = _findings(workspace, {"MEMORY.md": text})
    assert len(text.splitlines()) < 20
    assert len(text) <= MEMORY_INDEX_BYTES < len(text.encode("utf-8"))
    assert [finding.rule_id for finding in findings] == ["memory-index-too-large"]
    assert findings[0].line is None
