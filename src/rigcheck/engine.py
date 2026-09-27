"""Runs rules over a rig and ranks what they find."""

from collections.abc import Iterable

from rigcheck.model import Finding, Layer, LoadClass, Rig, Rule, Severity
from rigcheck.rules import REGISTRY


def _internal_error(rule: Rule, exc: Exception) -> Finding:
    meta = REGISTRY["internal-error"]
    message = f"rule {rule.id} raised {type(exc).__name__}: {exc}"
    return Finding("internal-error", meta.severity, None, None, message, meta.fix, None, None)


def run(rig: Rig, rules: Iterable[Rule]) -> list[Finding]:
    """Run every rule over ``rig`` and return the ranked findings.

    A rule that raises contributes one ``internal-error`` finding in place of its results;
    the other rules still run.

    Args:
        rig: The discovered setup.
        rules: The rules to run.

    Returns:
        The findings, ranked by :func:`rank`.
    """
    findings: list[Finding] = []
    for rule in rules:
        try:
            results = list(rule.check(rig))
        except Exception as exc:  # noqa: BLE001 - a failing rule becomes an internal-error finding instead of ending the run
            results = [_internal_error(rule, exc)]
        findings.extend(results)
    return rank(findings)


def _rank_key(finding: Finding) -> tuple[int, int, int, str, int, str, str]:
    return (
        finding.severity.rank,
        finding.load_class.rank if finding.load_class is not None else len(LoadClass),
        finding.layer.rank if finding.layer is not None else len(Layer),
        finding.path.as_posix() if finding.path is not None else "",
        finding.line or 0,
        finding.rule_id,
        finding.message,
    )


def rank(findings: Iterable[Finding]) -> list[Finding]:
    """Sort findings by severity, load class, layer, path and line (then rule id and message, for stability)."""
    return sorted(findings, key=_rank_key)


def count_by_severity(findings: Iterable[Finding]) -> dict[Severity, int]:
    """Count findings per severity, including severities with no findings."""
    counts = dict.fromkeys(Severity, 0)
    for finding in findings:
        counts[finding.severity] += 1
    return counts
