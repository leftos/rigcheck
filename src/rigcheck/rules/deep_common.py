"""What ``--deep`` and every ``deep`` pack rule share: which files are judged, and turning verdicts into findings."""

from collections.abc import Iterator
from pathlib import Path

from rigcheck.model import Artifact, Finding, Kind, Layer, LoadClass, Rig
from rigcheck.rules import emit

DEEP_KINDS = (Kind.INSTRUCTIONS, Kind.NESTED_INSTRUCTIONS, Kind.RULE, Kind.SKILL, Kind.COMMAND, Kind.AGENT)
"""The kinds of file ``--deep`` may send; settings, hooks, MCP, memory and plugin files never qualify."""
_DEEP_LAYERS = (Layer.REPO, Layer.USER)


def deep_artifacts(rig: Rig) -> dict[Path, Artifact]:
    """Return the files ``--deep`` may judge: loaded deep-kind artifacts of the repo and user layers, the first per path.

    Args:
        rig: The discovered setup.

    Returns:
        Each eligible path mapped to its first eligible artifact, in rig order.
    """
    chosen: dict[Path, Artifact] = {}
    for artifact in rig.artifacts:
        eligible = artifact.kind in DEEP_KINDS and artifact.layer in _DEEP_LAYERS and artifact.load_class is not LoadClass.NOT_LOADED
        if eligible and artifact.path not in chosen:
            chosen[artifact.path] = artifact
    return chosen


def findings_from(rig: Rig, family_id: str, rule_id: str) -> Iterator[Finding]:
    """Yield one finding of ``rule_id`` per verdict the family ``family_id`` returned, located at the judged file.

    Each verdict is matched to the artifact :func:`deep_artifacts` chose for its path, which supplies the finding's
    layer and load class. Without ``--deep``, or when the family judged nothing, nothing is yielded.

    Args:
        rig: The discovered setup, with ``verdicts`` filled under ``--deep``.
        family_id: The id of the family whose verdicts the rule reports.
        rule_id: The registered deep rule emitting the findings.

    Yields:
        The findings, in verdict order.

    Raises:
        ValueError: When a verdict's path is not a file ``--deep`` would send.
    """
    artifacts = deep_artifacts(rig)
    for verdict in rig.verdicts.get(family_id, ()):
        artifact = artifacts.get(verdict.path)
        if artifact is None:
            raise ValueError(f"verdict for {verdict.path} matches no artifact")
        yield emit(rule_id, artifact, verdict.message, verdict.line)
