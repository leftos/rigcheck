"""Rules for rule files (.claude/rules/*.md) and their path globs."""

from collections.abc import Iterator

from rigcheck.discover import is_outside
from rigcheck.model import Artifact, Finding, Kind, Layer, LoadClass, Rig, Severity, unc_link_target
from rigcheck.parse.globs import bracket_error, matches_any, matches_on_disk, over_budget, rule_patterns
from rigcheck.rules import emit, rule
from rigcheck.rules.components import KEYS, components, load, unknown_key_message, yaml_line, yaml_reason

RULE_KINDS = (Kind.RULE,)
"""The artifact kinds these rules read: repo- and user-layer rules, since plugins ship no rules folder."""


@rule(
    "rule-key-unknown",
    "core",
    Severity.WARN,
    "Rename the key to paths or remove it: paths is the only field Claude Code reads from a rule.",
    ("official:RL1",),
)
def rule_key_unknown(rig: Rig) -> Iterator[Finding]:
    """A rule frontmatter key other than paths, which Claude Code ignores."""
    for artifact in components(rig, RULE_KINDS):
        parsed = load(rig, artifact)
        if parsed.data is None:
            continue
        for key in map(str, parsed.data):
            if key not in KEYS[Kind.RULE]:
                message = unknown_key_message(key, KEYS[Kind.RULE])
                yield emit("rule-key-unknown", artifact, message, parsed.key_lines.get(key, 1))


@rule(
    "rule-frontmatter-invalid",
    "core",
    Severity.ERROR,
    'Fix the YAML: quote values that hold ": " or start with a YAML indicator, save the file with LF line endings, and close the block with ---.',
    ("official:RL2",),
)
def rule_frontmatter_invalid(rig: Rig) -> Iterator[Finding]:
    """Rule frontmatter Claude Code cannot parse, so the rule loads every turn."""
    for artifact in components(rig, RULE_KINDS):
        if artifact.load_class is LoadClass.NOT_LOADED:
            continue
        parsed = load(rig, artifact)
        if parsed.present and parsed.load_error is not None:
            error = parsed.load_error
            message = f"Claude Code rejects the frontmatter ({yaml_reason(error)}), so the rule loads every turn as if it had no paths"
            yield emit("rule-frontmatter-invalid", artifact, message, yaml_line(error))


@rule(
    "rule-external-scoped",
    "core",
    Severity.WARN,
    "Remove paths so the linked rule loads once external imports are approved, or copy the rule into the project's .claude/rules/.",
    ("official:RL7",),
)
def rule_external_scoped(rig: Rig) -> Iterator[Finding]:
    """A rule reached through a link out of the project that has paths, so it never loads."""
    for artifact in components(rig, RULE_KINDS):
        if artifact.layer is not Layer.REPO or unc_link_target(artifact.path) is not None:
            continue
        parsed = load(rig, artifact)
        if isinstance(parsed.data, dict) and "paths" in parsed.data and is_outside(artifact.path, rig.repo_root):
            message = "the rule is reached through a link out of the project and has paths, so Claude Code never loads it"
            yield emit("rule-external-scoped", artifact, message, parsed.key_lines.get("paths", 1))


def _repo_rule_patterns(rig: Rig) -> Iterator[tuple[Artifact, list[str], int]]:
    """Yield each repo-layer rule that has ``paths``, with its patterns as written (negated ones included) and the ``paths`` line."""
    for artifact in components(rig, RULE_KINDS):
        if artifact.layer is not Layer.REPO or unc_link_target(artifact.path) is not None:
            continue
        parsed = load(rig, artifact)
        if not isinstance(parsed.data, dict) or "paths" not in parsed.data:
            continue
        yield artifact, rule_patterns(parsed.data["paths"]), parsed.key_lines.get("paths", 1)


def _globs(patterns: list[str]) -> list[str]:
    """Return the patterns with a leading ``!`` stripped, so negated patterns are checked as the glob they negate."""
    return [pattern.removeprefix("!") for pattern in patterns]


@rule(
    "rule-glob-invalid",
    "core",
    Severity.ERROR,
    "Close the bracket expression or escape the [ as \\[, and keep brace expansion under 1,000 patterns across the rule's paths.",
    ("official:RL3",),
)
def rule_glob_invalid(rig: Rig) -> Iterator[Finding]:
    """A rule paths pattern Claude Code cannot use, so it matches no file."""
    for artifact, patterns, line in _repo_rule_patterns(rig):
        for pattern in patterns:
            if bracket_error(pattern.removeprefix("!")):
                message = f'the pattern "{pattern}" has a [ that starts no bracket expression, so it matches nothing'
                yield emit("rule-glob-invalid", artifact, message, line)
        if over_budget(_globs(patterns)):
            message = "the paths patterns expand past 1,000 patterns or 4 MiB, so their braces match no files"
            yield emit("rule-glob-invalid", artifact, message, line)


@rule(
    "rule-glob-unmatched",
    "core",
    Severity.WARN,
    "Correct the pattern so it names files in this repository (paths are relative to the project root), or remove it.",
    ("official:RL3",),
)
def rule_glob_unmatched(rig: Rig) -> Iterator[Finding]:
    """A rule paths pattern that matches no file in the repository."""
    files = rig.project_files
    if files is None:
        return
    for artifact, patterns, line in _repo_rule_patterns(rig):
        if artifact.load_class is LoadClass.NOT_LOADED or over_budget(_globs(patterns)):
            continue
        for pattern in (pattern for pattern in patterns if not pattern.startswith("!")):
            if bracket_error(pattern) or matches_any(pattern, files) or matches_on_disk(pattern, rig.repo_root):
                continue
            message = f'the pattern "{pattern}" matches no file in the repository, so the rule never loads'
            yield emit("rule-glob-unmatched", artifact, message, line)
