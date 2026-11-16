"""Deep-pack rules for every-turn instruction and rule files: vague directives and bare prohibitions."""

from collections.abc import Iterator

from rigcheck.model import Finding, Rig, Severity
from rigcheck.rules import rule
from rigcheck.rules.deep_common import findings_from


@rule(
    "vague-directive",
    "deep",
    Severity.INFO,
    "Name what to do in a form that can be checked, such as a command, path, value or file: "
    '"Use 2-space indentation" instead of "Format code properly".',
    ("official:CM6", "sota:#13 (C)"),
)
def vague_directive(rig: Rig) -> Iterator[Finding]:
    """An every-turn instruction names no concrete action that can be checked."""
    return findings_from(rig, "vague-directive", "vague-directive")


@rule(
    "bare-prohibition",
    "deep",
    Severity.INFO,
    'Add the reason the rule exists after the prohibition, as in "Never use ellipses: the text-to-speech engine cannot read them".',
    ("official:PR2", "sota:#12 (C)"),
)
def bare_prohibition(rig: Rig) -> Iterator[Finding]:
    """An every-turn instruction forbids something without giving the reason."""
    return findings_from(rig, "bare-prohibition", "bare-prohibition")
