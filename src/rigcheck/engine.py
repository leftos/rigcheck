"""Runs rules over a rig and ranks what they find."""

from collections.abc import Iterable

from rigcheck.model import Finding, Layer, LoadClass, Outcome, Rig, Rule, Severity, Suppressed, Suppression
from rigcheck.parse.globs import matches_path
from rigcheck.rules import REGISTRY

UNSUPPRESSIBLE = frozenset({"internal-error", "discovery-error", "deep-error", "suppression-no-reason", "suppression-unused"})
"""Rule ids whose findings no ``.rigcheck.toml`` entry can silence."""


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


def _matches(rig: Rig, suppression: Suppression, finding: Finding) -> bool:
    """Return True when the entry covers the finding; only repo-layer files under the repo root and setup findings are covered."""
    if finding.rule_id != suppression.rule or finding.rule_id in UNSUPPRESSIBLE:
        return False
    if finding.path is None:
        return suppression.path is None
    if finding.layer is not Layer.REPO:
        return False
    try:
        relative = finding.path.relative_to(rig.repo_root).as_posix()
    except ValueError:
        return False
    return suppression.path is None or matches_path(suppression.path, relative)


def _unused(rig: Rig, suppression: Suppression) -> Finding:
    meta = REGISTRY["suppression-unused"]
    if suppression.rule not in REGISTRY:
        message = f"suppression names `{suppression.rule}`, which is not a rigcheck rule id"
    elif suppression.path is not None:
        message = f"suppression of `{suppression.rule}` for `{suppression.path}` matched no finding"
    else:
        message = f"suppression of `{suppression.rule}` matched no finding"
    path = rig.repo_root / ".rigcheck.toml"
    return Finding("suppression-unused", meta.severity, path, suppression.line, message, meta.fix, Layer.REPO, LoadClass.NOT_LOADED)


def _skipped(ran: frozenset[str], suppression: Suppression) -> bool:
    """Return True when the entry names a registered rule that did not run, so it counts as neither used nor unused."""
    return suppression.rule in REGISTRY and suppression.rule not in ran


def apply_suppressions(rig: Rig, findings: list[Finding], ran: frozenset[str]) -> Outcome:
    """Split findings into the kept and the suppressed by the repo's ``.rigcheck.toml`` entries.

    An entry matches a repo-layer or setup finding of its rule, limited to files its ``path`` glob matches when it
    has one. The first matching entry in file order takes a finding; every entry that matches at least one finding
    counts as used, and each unused entry becomes a ``suppression-unused`` finding. An entry naming a registered
    rule that did not run is neither used nor unused, since a rule that never ran could not match it; an entry
    naming no registered rule at all is still unused. Findings of the user, memory and plugin layers, and of the
    engine and suppression rules, are never suppressed.

    Args:
        rig: The discovered setup, holding the suppressions.
        findings: The findings of a run.
        ran: The ids of the rules that ran.

    Returns:
        The kept findings plus the ``suppression-unused`` ones, ranked, and the suppressed findings, ranked.
    """
    used: set[int] = set()
    kept: list[Finding] = []
    suppressed: list[Suppressed] = []
    for finding in findings:
        matching = [index for index, suppression in enumerate(rig.suppressions) if _matches(rig, suppression, finding)]
        used.update(matching)
        if matching:
            suppressed.append(Suppressed(finding, rig.suppressions[matching[0]]))
        else:
            kept.append(finding)
    unused = [_unused(rig, suppression) for index, suppression in enumerate(rig.suppressions) if index not in used and not _skipped(ran, suppression)]
    return Outcome(findings=rank([*kept, *unused]), suppressed=sorted(suppressed, key=lambda entry: _rank_key(entry.finding)))


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
