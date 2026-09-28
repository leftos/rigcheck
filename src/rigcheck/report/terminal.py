"""Plain-text report for a terminal, grouped by layer."""

import os
from pathlib import Path
from typing import TextIO

from rigcheck import __version__
from rigcheck.engine import count_by_severity
from rigcheck.model import Finding, Layer, Rig, Severity
from rigcheck.report.budget import Budget, Listing, window_label

_COLORS = {Severity.ERROR: "\x1b[31m", Severity.WARN: "\x1b[33m", Severity.INFO: "\x1b[36m"}
_RESET = "\x1b[0m"
_GROUPS: tuple[Layer | None, ...] = (Layer.REPO, Layer.MEMORY, Layer.USER, Layer.PLUGIN, None)
_EVERY_TURN_ROWS = 10


def use_color(stream: TextIO) -> bool:
    """Return True when ``stream`` is a TTY and ``NO_COLOR`` is not set to a non-empty value."""
    return stream.isatty() and not os.environ.get("NO_COLOR")


def display_path(rig: Rig, path: Path | None, layer: Layer | None) -> str:
    """Show a path relative to the repo root (repo layer) or as ``~/...`` (other layers), else absolute."""
    if path is None:
        return "(rigcheck)"
    if layer is None:
        return path.as_posix()
    base, prefix = (rig.repo_root, "") if layer is Layer.REPO else (rig.home, "~/")
    try:
        return prefix + path.relative_to(base).as_posix()
    except ValueError:
        return path.as_posix()


def _finding_lines(rig: Rig, finding: Finding, color: bool) -> list[str]:
    location = display_path(rig, finding.path, finding.layer)
    if finding.line is not None:
        location += f":{finding.line}"
    severity = finding.severity.name
    if color:
        severity = f"{_COLORS[finding.severity]}{severity}{_RESET}"
    return [f"  {location}  {severity}  {finding.rule_id}  {finding.message}", f"      fix: {finding.fix}"]


def _listing_line(label: str, listing: Listing, color: bool) -> str:
    line = f"  {label}   ≈{listing.tokens_est:,} / {listing.budget:,}"
    if listing.budget > 0:
        line += f" ({round(100 * listing.tokens_est / listing.budget)}%)"
    if listing.by_layer:
        line += "   " + " · ".join(f"{layer} {tokens:,}" for layer, tokens in listing.by_layer.items())
    if listing.tokens_est > listing.budget:
        marker = "over budget"
        if color:
            marker = f"{_COLORS[Severity.WARN]}{marker}{_RESET}"
        line += f"  {marker}"
    return line


def _budget_lines(rig: Rig, budget: Budget, color: bool) -> list[str]:
    every_turn = budget.every_turn
    shown = every_turn.sources[:_EVERY_TURN_ROWS]
    counts = [f"≈{source.tokens_est:,}" for source in shown]
    width = max((len(count) for count in counts), default=0)
    lines = [f"Context budget (≈ tokens, {window_label(budget.window)} window)", f"  every turn   ≈{every_turn.total_est:,} total"]
    lines.extend(f"    {count:>{width}}  {display_path(rig, source.path, source.layer)}" for count, source in zip(counts, shown, strict=True))
    hidden = len(every_turn.sources) - len(shown)
    if hidden:
        lines.append(f"    … {hidden} more")
    lines.append(_listing_line("skill listing", budget.skill_listing, color))
    lines.append(_listing_line("agent descriptions", budget.agent_descriptions, color))
    return lines


def render(rig: Rig, findings: list[Finding], budget: Budget, *, color: bool) -> str:
    """Render the context budget and ranked findings as text, findings grouped by layer.

    Args:
        rig: The rig the findings are about.
        findings: Ranked findings.
        budget: The rig's context budget, shown at the top.
        color: Whether to color severities and over-budget markers with ANSI codes.

    Returns:
        The report, ending with a newline.
    """
    lines = [f"rigcheck {__version__} — {rig.target.as_posix()}", "", *_budget_lines(rig, budget, color)]
    for group in _GROUPS:
        members = [finding for finding in findings if finding.layer is group]
        if not members:
            continue
        lines.extend(["", group.value if group is not None else "rigcheck"])
        for finding in members:
            lines.extend(_finding_lines(rig, finding, color))
    counts = count_by_severity(findings)
    lines.extend(["", f"{counts[Severity.ERROR]} errors · {counts[Severity.WARN]} warnings · {counts[Severity.INFO]} info"])
    return "\n".join(lines) + "\n"
