"""The suppression rules: an entry of ``.rigcheck.toml`` that gives no reason."""

from rigcheck.discover import discover
from rigcheck.model import DEFAULT_WINDOW, Layer, LoadClass, Severity
from rigcheck.rules import REGISTRY
from support import Workspace, write

RULE = "suppression-no-reason"


def test_whitespace_reason_is_one_finding_at_the_entry_line(workspace: Workspace) -> None:
    repo = workspace.rig()
    write(repo / "CLAUDE.md", "# Project\n")
    config = write(repo / ".rigcheck.toml", '[[suppress]]\nrule = "a"\nreason = "r"\n\n[[suppress]]\nrule = "b"\nreason = "  "\n')
    rig = discover(repo, workspace.home, DEFAULT_WINDOW)
    findings = list(REGISTRY[RULE].check(rig))
    assert len(findings) == 1
    finding = findings[0]
    assert (finding.rule_id, finding.severity, finding.path, finding.line) == (RULE, Severity.WARN, config, 5)
    assert (finding.layer, finding.load_class) == (Layer.REPO, LoadClass.NOT_LOADED)
    assert finding.message == "suppression of `b` has no reason"


def test_entry_with_a_reason_is_no_finding(workspace: Workspace) -> None:
    repo = workspace.rig()
    write(repo / "CLAUDE.md", "# Project\n")
    write(repo / ".rigcheck.toml", '[[suppress]]\nrule = "a"\nreason = "vendored"\n')
    rig = discover(repo, workspace.home, DEFAULT_WINDOW)
    assert list(REGISTRY[RULE].check(rig)) == []
