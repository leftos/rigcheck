"""Rules for the listings Claude Code keeps in context: skills and commands, and subagents."""

from collections.abc import Iterator

from rigcheck.model import Finding, Rig, Severity
from rigcheck.report.budget import Listing, compute, window_label
from rigcheck.rules import emit_setup, rule


def _layers(listing: Listing) -> str:
    return ", ".join(f"{layer} ≈{tokens:,}" for layer, tokens in listing.by_layer.items())


def _count(entries: int, one: str, many: str) -> str:
    return f"1 {one}" if entries == 1 else f"{entries} {many}"


@rule(
    "skill-listing-over-budget",
    "core",
    Severity.WARN,
    fix=(
        "Set disable-model-invocation: true on skills Claude need not pick on its own, or disable plugins you do not use; "
        "pass --window if your model's window is larger."
    ),
    evidence=("official:SK27",),
)
def skill_listing_over_budget(rig: Rig) -> Iterator[Finding]:
    """The skill listing is estimated past 1% of the context window, where Claude Code drops skill descriptions."""
    listing = compute(rig).skill_listing
    if listing.tokens_est <= listing.budget:
        return
    yield emit_setup(
        "skill-listing-over-budget",
        f"skill listing ≈{listing.tokens_est:,} tokens is over its ≈{listing.budget:,}-token budget (1% of a {window_label(rig.window)} window) "
        f"across {_count(listing.entries, 'skill or command', 'skills and commands')}; by layer: {_layers(listing)}",
    )


@rule(
    "agent-descriptions-over-budget",
    "core",
    Severity.WARN,
    fix="Shorten agent descriptions, or remove or disable agents you do not use.",
    evidence=("official:AG6",),
)
def agent_descriptions_over_budget(rig: Rig) -> Iterator[Finding]:
    """Subagent names and descriptions are estimated past the 15,000 tokens where Claude Code shows a startup warning."""
    listing = compute(rig).agent_descriptions
    if listing.tokens_est <= listing.budget:
        return
    yield emit_setup(
        "agent-descriptions-over-budget",
        f"agent names and descriptions ≈{listing.tokens_est:,} tokens are over the {listing.budget:,}-token limit "
        f"across {_count(listing.entries, 'agent', 'agents')}; by layer: {_layers(listing)}",
    )
