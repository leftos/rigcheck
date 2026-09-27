"""JSON report with a stable schema, for agents and scripts."""

import json
from pathlib import Path
from typing import Any

from rigcheck import __version__
from rigcheck.engine import count_by_severity
from rigcheck.model import Artifact, Finding, Kind, Rig
from rigcheck.parse.markdown import strip_html_comments
from rigcheck.parse.tokens import estimate
from rigcheck.rules import REGISTRY

SCHEMA_VERSION = 1

_STRIPPED_KINDS = (Kind.INSTRUCTIONS, Kind.NESTED_INSTRUCTIONS)


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
    text = rig.text(artifact.path)
    if artifact.kind in _STRIPPED_KINDS:
        text = strip_html_comments(text)
    return {
        "path": artifact.path.as_posix(),
        "kind": artifact.kind.value,
        "layer": artifact.layer.value,
        "load_class": artifact.load_class.value,
        "plugin": artifact.plugin,
        "tokens_est": estimate(text),
    }


def render(rig: Rig, findings: list[Finding]) -> str:
    """Render ranked findings and the rig's artifacts as JSON.

    Enum values are lower-case strings, paths are POSIX strings, findings keep their rank
    order and artifacts are sorted by layer, then path.

    Args:
        rig: The rig the findings are about.
        findings: Ranked findings.

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
        "summary": {severity.value: count for severity, count in counts.items()},
        "findings": [_finding(finding) for finding in findings],
        "artifacts": [_artifact(rig, artifact) for artifact in artifacts],
    }
    return json.dumps(payload, indent=2) + "\n"
