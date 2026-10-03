"""Applying ``.rigcheck.toml`` suppressions to findings, and reporting the entries that match nothing."""

from pathlib import Path

from rigcheck import engine
from rigcheck.discover import discover
from rigcheck.model import DEFAULT_WINDOW, Finding, Layer, LoadClass, Rig, Severity
from rigcheck.rules import REGISTRY
from support import Workspace, write

MISSING = "reference-path-missing"
UNUSED = "suppression-unused"
RAN_ALL = frozenset(REGISTRY)


def _rig(workspace: Workspace, toml: str, claude_md: str = "# Project\n") -> Rig:
    repo = workspace.rig()
    write(repo / "CLAUDE.md", claude_md)
    write(repo / ".rigcheck.toml", toml)
    return discover(repo, workspace.home, DEFAULT_WINDOW)


def _finding(rule_id: str, path: Path | None, layer: Layer | None, severity: Severity = Severity.WARN) -> Finding:
    line = 1 if path is not None else None
    return Finding(rule_id, severity, path, line, f"{rule_id} message", "Fix it.", layer, LoadClass.EVERY_TURN)


def _unused(findings: list[Finding]) -> list[Finding]:
    return [finding for finding in findings if finding.rule_id == UNUSED]


def test_whole_repo_entry_suppresses_repo_finding(workspace: Workspace) -> None:
    write(workspace.rig() / "docs" / "other.md", "x\n")
    rig = _rig(workspace, f'[[suppress]]\nrule = "{MISSING}"\nreason = "moved"\n', "Read `docs/gone.md`.\n")
    findings = engine.run(rig, REGISTRY.values())
    assert MISSING in [finding.rule_id for finding in findings]
    outcome = engine.apply_suppressions(rig, findings, RAN_ALL)
    assert MISSING not in [finding.rule_id for finding in outcome.findings]
    assert [entry.finding.rule_id for entry in outcome.suppressed] == [MISSING]
    assert outcome.suppressed[0].suppression == rig.suppressions[0]
    assert _unused(outcome.findings) == []


def test_whole_repo_entry_skips_repo_layer_file_outside_root(workspace: Workspace) -> None:
    rig = _rig(workspace, f'[[suppress]]\nrule = "{MISSING}"\nreason = "moved"\n')
    outside = _finding(MISSING, rig.repo_root.parent / "CLAUDE.md", Layer.REPO)
    outcome = engine.apply_suppressions(rig, [outside], RAN_ALL)
    assert outcome.suppressed == []
    assert outside in outcome.findings
    assert [finding.line for finding in _unused(outcome.findings)] == [1]


def test_path_entry_suppresses_only_matching_path(workspace: Workspace) -> None:
    rig = _rig(workspace, f'[[suppress]]\nrule = "{MISSING}"\npath = "docs/**"\nreason = "drafts"\n')
    in_docs = _finding(MISSING, rig.repo_root / "docs" / "deep" / "a.md", Layer.REPO)
    at_root = _finding(MISSING, rig.repo_root / "CLAUDE.md", Layer.REPO)
    outcome = engine.apply_suppressions(rig, [in_docs, at_root], RAN_ALL)
    assert outcome.findings == [at_root]
    assert [entry.finding for entry in outcome.suppressed] == [in_docs]


def test_entry_never_matches_user_or_plugin_layer(workspace: Workspace) -> None:
    rig = _rig(workspace, f'[[suppress]]\nrule = "{MISSING}"\nreason = "r"\n\n[[suppress]]\nrule = "{MISSING}"\npath = "**"\nreason = "r"\n')
    user = _finding(MISSING, rig.home / ".claude" / "CLAUDE.md", Layer.USER)
    memory = _finding(MISSING, rig.home / ".claude" / "projects" / "x" / "memory" / "MEMORY.md", Layer.MEMORY)
    plugin = _finding(MISSING, rig.repo_root / "plugin" / "SKILL.md", Layer.PLUGIN)
    outcome = engine.apply_suppressions(rig, [user, memory, plugin], RAN_ALL)
    assert outcome.suppressed == []
    assert {user, memory, plugin} <= set(outcome.findings)
    assert [finding.line for finding in _unused(outcome.findings)] == [1, 5]


def test_entry_without_path_matches_setup_finding(workspace: Workspace) -> None:
    rig = _rig(workspace, '[[suppress]]\nrule = "skill-listing-over-budget"\nreason = "many skills by design"\n')
    setup = _finding("skill-listing-over-budget", None, None)
    outcome = engine.apply_suppressions(rig, [setup], RAN_ALL)
    assert outcome.findings == []
    assert [entry.finding for entry in outcome.suppressed] == [setup]


def test_unsuppressible_rules_stay(workspace: Workspace) -> None:
    toml = '[[suppress]]\nrule = "discovery-error"\nreason = "r"\n\n[[suppress]]\nrule = "suppression-no-reason"\nreason = "r"\n'
    rig = _rig(workspace, toml)
    discovery = _finding("discovery-error", None, None)
    no_reason = _finding("suppression-no-reason", rig.repo_root / ".rigcheck.toml", Layer.REPO)
    outcome = engine.apply_suppressions(rig, [discovery, no_reason], RAN_ALL)
    assert outcome.suppressed == []
    assert {discovery, no_reason} <= set(outcome.findings)
    messages = sorted(finding.message for finding in _unused(outcome.findings))
    assert messages == ["suppression of `discovery-error` matched no finding", "suppression of `suppression-no-reason` matched no finding"]


def test_unused_entry_reported_at_its_line(workspace: Workspace) -> None:
    toml = f'[[suppress]]\nrule = "{MISSING}"\nreason = "r"\n\n[[suppress]]\nrule = "import-unresolved"\npath = "docs/**"\nreason = "r"\n'
    rig = _rig(workspace, toml)
    outcome = engine.apply_suppressions(rig, [_finding(MISSING, rig.repo_root / "CLAUDE.md", Layer.REPO)], RAN_ALL)
    unused = _unused(outcome.findings)
    assert len(unused) == 1
    finding = unused[0]
    assert (finding.path, finding.line, finding.layer, finding.load_class) == (rig.repo_root / ".rigcheck.toml", 5, Layer.REPO, LoadClass.NOT_LOADED)
    assert (finding.severity, finding.fix) == (Severity.INFO, REGISTRY[UNUSED].fix)
    assert finding.message == "suppression of `import-unresolved` for `docs/**` matched no finding"


def test_unknown_rule_id_reported(workspace: Workspace) -> None:
    rig = _rig(workspace, '[[suppress]]\nrule = "no-such-rule"\nreason = "r"\n')
    outcome = engine.apply_suppressions(rig, [], RAN_ALL)
    assert [finding.message for finding in outcome.findings] == ["suppression names `no-such-rule`, which is not a rigcheck rule id"]


def test_two_entries_one_finding_both_used(workspace: Workspace) -> None:
    rig = _rig(workspace, f'[[suppress]]\nrule = "{MISSING}"\nreason = "a"\n\n[[suppress]]\nrule = "{MISSING}"\npath = "CLAUDE.md"\nreason = "b"\n')
    finding = _finding(MISSING, rig.repo_root / "CLAUDE.md", Layer.REPO)
    outcome = engine.apply_suppressions(rig, [finding], RAN_ALL)
    assert outcome.findings == []
    assert [(entry.finding, entry.suppression) for entry in outcome.suppressed] == [(finding, rig.suppressions[0])]


def test_reasonless_entry_still_suppresses(workspace: Workspace) -> None:
    rig = _rig(workspace, f'[[suppress]]\nrule = "{MISSING}"\n')
    finding = _finding(MISSING, rig.repo_root / "CLAUDE.md", Layer.REPO)
    outcome = engine.apply_suppressions(rig, [finding], RAN_ALL)
    assert outcome.findings == []
    assert [entry.finding for entry in outcome.suppressed] == [finding]
    assert outcome.suppressed[0].suppression.reason is None


def test_outcome_lists_are_ranked(workspace: Workspace) -> None:
    rig = _rig(workspace, f'[[suppress]]\nrule = "{MISSING}"\npath = "docs/**"\nreason = "r"\n\n[[suppress]]\nrule = "no-such-rule"\nreason = "r"\n')
    root = rig.repo_root
    findings = [
        _finding(MISSING, root / "docs" / "b.md", Layer.REPO),
        _finding("import-unresolved", root / "CLAUDE.md", Layer.REPO, Severity.INFO),
        _finding(MISSING, root / "docs" / "a.md", Layer.REPO),
        _finding("import-unresolved", root / "AGENTS.md", Layer.REPO, Severity.ERROR),
    ]
    outcome = engine.apply_suppressions(rig, findings, RAN_ALL)
    assert len(outcome.findings) == 3
    assert outcome.findings == engine.rank(outcome.findings)
    assert outcome.findings[0].severity is Severity.ERROR
    assert [entry.finding.path.name for entry in outcome.suppressed if entry.finding.path is not None] == ["a.md", "b.md"]


def test_entry_for_rule_not_run_is_not_unused(workspace: Workspace) -> None:
    rig = _rig(workspace, f'[[suppress]]\nrule = "{MISSING}"\nreason = "r"\n')
    outcome = engine.apply_suppressions(rig, [], ran=frozenset({"import-unresolved"}))
    assert _unused(outcome.findings) == []


def test_entry_for_unknown_rule_still_unused(workspace: Workspace) -> None:
    rig = _rig(workspace, '[[suppress]]\nrule = "no-such-rule"\nreason = "r"\n')
    outcome = engine.apply_suppressions(rig, [], ran=frozenset())
    assert [finding.message for finding in outcome.findings] == ["suppression names `no-such-rule`, which is not a rigcheck rule id"]
