"""Markdown fix brief: a checklist of the findings for a person to work through."""

from rigcheck.model import Finding, Rig
from rigcheck.report.terminal import display_path
from rigcheck.rules import REGISTRY

_PREAMBLE = (
    "rigcheck never edits the files it checks. Work through the findings below and tick each box once it is fixed; "
    "`rigcheck explain <rule-id>` shows a rule's evidence."
)


def _evidence(rule_id: str) -> str:
    """Return a rule's evidence joined with commas, or ``none`` when the id is not registered."""
    rule = REGISTRY.get(rule_id)
    if rule is None:
        return "none"
    return ", ".join(rule.evidence)


def _setup_lines(finding: Finding) -> list[str]:
    """Render one setup finding as a checkbox, its fix and its evidence, with no file prefix."""
    return [
        f"- [ ] {finding.rule_id} ({finding.severity.value}): {finding.message}",
        f"  Fix: {finding.fix}",
        f"  Evidence: {_evidence(finding.rule_id)}",
    ]


def _file_lines(rig: Rig, finding: Finding) -> list[str]:
    """Render one file finding as a checkbox naming where it is, then its fix and evidence."""
    location = display_path(rig, finding.path, finding.layer)
    if finding.line is not None:
        location += f":{finding.line}"
    return [
        f"- [ ] {location} {finding.rule_id} ({finding.severity.value}): {finding.message}",
        f"  Fix: {finding.fix}",
        f"  Evidence: {_evidence(finding.rule_id)}",
    ]


def _file_groups(rig: Rig, findings: list[Finding]) -> dict[str, list[Finding]]:
    """Group file findings by display path, in the order each path first appears in the ranked list."""
    groups: dict[str, list[Finding]] = {}
    for finding in findings:
        if finding.path is None:
            continue
        groups.setdefault(display_path(rig, finding.path, finding.layer), []).append(finding)
    return groups


def render(rig: Rig, findings: list[Finding]) -> str:
    """Render the ranked findings as a Markdown checklist: a Setup section first, then one section per file.

    Each finding shows its display path, message, fix and rule evidence; the checked files'
    contents never appear.

    Args:
        rig: The rig the findings are about.
        findings: Ranked findings; a finding whose path is None is a setup finding.

    Returns:
        The brief, ending with a newline. With no findings the header is followed by ``No findings.``.
    """
    lines = [f"# rigcheck fix brief: {rig.target.as_posix()}", "", _PREAMBLE]
    if not findings:
        lines.extend(["", "No findings."])
        return "\n".join(lines) + "\n"
    setup = [finding for finding in findings if finding.path is None]
    if setup:
        lines.extend(["", "## Setup", ""])
        for finding in setup:
            lines.extend(_setup_lines(finding))
    for path, members in _file_groups(rig, findings).items():
        lines.extend(["", f"## {path}", ""])
        for finding in members:
            lines.extend(_file_lines(rig, finding))
    return "\n".join(lines) + "\n"
