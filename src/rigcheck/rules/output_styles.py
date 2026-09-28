"""Rules for output styles (.claude/output-styles/*.md): unknown keys, the plugin-only key and the dropped coding instructions."""

from collections.abc import Iterator

from rigcheck.model import Finding, Kind, Layer, Rig, Severity
from rigcheck.rules import emit, rule
from rigcheck.rules.components import OUTPUT_STYLE_KEYS, components, load, normalise_key, unknown_key_message

STYLE_KINDS = (Kind.OUTPUT_STYLE,)
"""The artifact kind these rules read: output styles, from every layer."""

KEEP_CODING = "keep-coding-instructions"
"""The key that keeps Claude Code's built-in coding instructions in a style."""

FORCE_FOR_PLUGIN = "force-for-plugin"
"""The key Claude Code reads only in a plugin's output style."""


@rule(
    "output-style-key-unknown",
    "core",
    Severity.WARN,
    "Rename a misspelled key to name, description, keep-coding-instructions or force-for-plugin, or remove it; "
    "force-for-plugin works only in a plugin's output style.",
    ("official:OS1",),
)
def output_style_key_unknown(rig: Rig) -> Iterator[Finding]:
    """An output style frontmatter key Claude Code does not recognize, so it is ignored."""
    for artifact in components(rig, STYLE_KINDS):
        parsed = load(rig, artifact)
        if parsed.data is None:
            continue
        known = OUTPUT_STYLE_KEYS if artifact.layer is Layer.PLUGIN else OUTPUT_STYLE_KEYS - {FORCE_FOR_PLUGIN}
        for key in (key for key in parsed.data if isinstance(key, str) and key not in OUTPUT_STYLE_KEYS):
            message = unknown_key_message(key, known)
            yield emit("output-style-key-unknown", artifact, message, parsed.key_lines.get(key, 1))
        if FORCE_FOR_PLUGIN in parsed.data and artifact.layer is not Layer.PLUGIN:
            message = '"force-for-plugin" works only in a plugin\'s output style; Claude Code ignores it'
            yield emit("output-style-key-unknown", artifact, message, parsed.key_lines.get(FORCE_FOR_PLUGIN, 1))


@rule(
    "output-style-drops-coding",
    "core",
    Severity.WARN,
    "Add keep-coding-instructions: true to keep the built-in coding instructions, or false to confirm dropping them.",
    ("official:OS2",),
)
def output_style_drops_coding(rig: Rig) -> Iterator[Finding]:
    """An output style that drops Claude Code's built-in coding instructions."""
    message = (
        "no keep-coding-instructions, so this style drops Claude Code's built-in coding instructions; "
        "set it to true to keep them, or false to confirm"
    )
    for artifact in components(rig, STYLE_KINDS):
        data = load(rig, artifact).data or {}
        if not any(isinstance(key, str) and normalise_key(key) == normalise_key(KEEP_CODING) for key in data):
            yield emit("output-style-drops-coding", artifact, message, 1)
