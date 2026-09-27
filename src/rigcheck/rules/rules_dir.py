"""Rules for rule files (.claude/rules/*.md) and their path globs."""

from collections.abc import Iterator

from rigcheck.discover import is_outside
from rigcheck.model import Finding, Kind, Layer, LoadClass, Rig, Severity, unc_link_target
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
