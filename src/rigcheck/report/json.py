"""JSON report with a stable schema, for agents and scripts."""

import json
from pathlib import Path
from typing import Any

from rigcheck import __version__
from rigcheck.engine import count_by_severity
from rigcheck.model import Artifact, Finding, Rig, Suppressed
from rigcheck.parse.tokens import INSTRUCTION_CHARS_PER_TOKEN, estimate
from rigcheck.report.budget import Budget, Listing, loaded_text
from rigcheck.rules import REGISTRY

SCHEMA_VERSION = 1


def _posix(path: Path | None) -> str | None:
    return path.as_posix() if path is not None else None


def _finding(finding: Finding) -> dict[str, Any]:
    rule = REGISTRY.get(finding.rule_id)
    return {
        "rule": finding.rule_id,
        "severity": finding.severity.value,
        "layer": finding.layer.value if finding.layer is not None else None,
        "load_class": finding.load_class.value if finding.load_class is not None else None,
        "path": _posix(finding.path),
        "line": finding.line,
        "message": finding.message,
        "fix": finding.fix,
        "evidence": list(rule.evidence) if rule is not None else [],
    }


def _artifact(rig: Rig, artifact: Artifact) -> dict[str, Any]:
    return {
        "path": artifact.path.as_posix(),
        "kind": artifact.kind.value,
        "layer": artifact.layer.value,
        "load_class": artifact.load_class.value,
        "plugin": artifact.plugin,
        "tokens_est": estimate(loaded_text(rig, artifact), INSTRUCTION_CHARS_PER_TOKEN),
    }


def _listing(listing: Listing) -> dict[str, Any]:
    return {"tokens_est": listing.tokens_est, "budget": listing.budget, "entries": listing.entries, "by_layer": dict(listing.by_layer)}


def _budget(budget: Budget) -> dict[str, Any]:
    sources = [
        {"path": source.path.as_posix(), "layer": source.layer.value, "kind": source.kind.value, "tokens_est": source.tokens_est}
        for source in budget.every_turn.sources
    ]
    return {
        "window": budget.window,
        "every_turn": {"total_est": budget.every_turn.total_est, "sources": sources},
        "skill_listing": _listing(budget.skill_listing),
        "agent_descriptions": _listing(budget.agent_descriptions),
    }


def render(rig: Rig, findings: list[Finding], suppressed: list[Suppressed], budget: Budget) -> str:
    """Render ranked findings, the suppressed findings, the context budget and the rig's artifacts as JSON.

    Enum values are lower-case strings, paths are POSIX strings, findings keep their rank
    order and artifacts are sorted by layer, then path. A suppressed finding carries the
    reason its entry gives, or null.

    Args:
        rig: The rig the findings are about.
        findings: Ranked findings.
        suppressed: Ranked findings a ``.rigcheck.toml`` entry silenced.
        budget: The rig's context budget.

    Returns:
        The JSON document, ending with a newline.
    """
    counts = count_by_severity(findings)
    artifacts = sorted(rig.artifacts, key=lambda a: (a.layer.rank, a.path.as_posix(), a.kind.value))
    payload = {
        "schema": SCHEMA_VERSION,
        "rigcheck": __version__,
        "target": rig.target.as_posix(),
        "repo_root": rig.repo_root.as_posix(),
        "summary": {**{severity.value: count for severity, count in counts.items()}, "suppressed": len(suppressed)},
        "findings": [_finding(finding) for finding in findings],
        "suppressed": [{**_finding(entry.finding), "reason": entry.suppression.reason} for entry in suppressed],
        "budget": _budget(budget),
        "artifacts": [_artifact(rig, artifact) for artifact in artifacts],
    }
    return json.dumps(payload, indent=2) + "\n"
