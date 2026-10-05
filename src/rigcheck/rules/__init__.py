"""The rule registry: every rule registers itself here through :func:`rule`."""

from collections.abc import Callable, Iterable

from rigcheck.model import Artifact, Finding, LoadClass, Rig, Rule, Severity

Check = Callable[[Rig], Iterable[Finding]]

REGISTRY: dict[str, Rule] = {}

PACKS = ("core", "advice", "house")
"""Every rule belongs to exactly one of these packs; the tuple is their canonical listing order."""

DEFAULT_PACKS = frozenset({"core", "advice"})
"""The packs a run selects when ``--packs`` is not given; ``house`` is off unless named."""


def rule(rule_id: str, pack: str, severity: Severity, fix: str, evidence: tuple[str, ...]) -> Callable[[Check], Check]:
    """Register the decorated check as a rule; its docstring's first line is the rule summary.

    Args:
        rule_id: The rule's slug id, such as ``import-unresolved``.
        pack: The pack the rule belongs to; one of :data:`PACKS`.
        severity: The severity of every finding the rule emits.
        fix: The suggested fix shown with each finding.
        evidence: Research ids backing the rule, such as ``official:CM2``.

    Returns:
        A decorator that registers the check and returns it unchanged.
    """

    def register(check: Check) -> Check:
        if rule_id in REGISTRY:
            raise ValueError(f"rule {rule_id} is registered twice")
        if pack not in PACKS:
            raise ValueError(f"rule {rule_id} has unknown pack {pack!r}; packs are core, advice and house")
        doc = (check.__doc__ or "").strip()
        if not doc:
            raise ValueError(f"rule {rule_id} needs a docstring: its first line is the rule summary")
        REGISTRY[rule_id] = Rule(rule_id, pack, severity, doc.splitlines()[0], fix, evidence, check)
        return check

    return register


def emit(rule_id: str, artifact: Artifact, message: str, line: int | None) -> Finding:
    """Build a finding of a registered rule located at ``artifact``.

    Args:
        rule_id: The registered rule emitting the finding.
        artifact: The file the finding is about; supplies path, layer and load class.
        message: What is wrong, specific to this location.
        line: The 1-based line, or None for a whole-file finding.

    Returns:
        The finding, with severity and fix taken from the rule.
    """
    meta = REGISTRY[rule_id]
    return Finding(rule_id, meta.severity, artifact.path, line, message, meta.fix, artifact.layer, artifact.load_class)


def emit_setup(rule_id: str, message: str) -> Finding:
    """Build a finding of a registered rule about the whole setup rather than one file.

    Args:
        rule_id: The registered rule emitting the finding.
        message: What is wrong with the setup.

    Returns:
        The finding, with no path, line or layer, loading every turn, and severity and fix taken from the rule.
    """
    meta = REGISTRY[rule_id]
    return Finding(rule_id, meta.severity, None, None, message, meta.fix, None, LoadClass.EVERY_TURN)


# Area modules register their rules on import; they need `rule`, `emit` and `emit_setup` defined above.
import rigcheck.rules.advice_components  # noqa: E402 - imported for its registrations
import rigcheck.rules.advice_instructions  # noqa: E402 - imported for its registrations
import rigcheck.rules.advice_other  # noqa: E402 - imported for its registrations
import rigcheck.rules.agent_refs  # noqa: E402 - imported for its registrations
import rigcheck.rules.agents  # noqa: E402 - imported for its registrations
import rigcheck.rules.budget  # noqa: E402 - imported for its registrations
import rigcheck.rules.commands  # noqa: E402 - imported for its registrations
import rigcheck.rules.components  # noqa: E402 - imported for its registrations
import rigcheck.rules.duplication  # noqa: E402 - imported for its registrations
import rigcheck.rules.hook_commands  # noqa: E402 - imported for its registrations
import rigcheck.rules.hooks  # noqa: E402 - imported for its registrations
import rigcheck.rules.instructions  # noqa: E402 - imported for its registrations
import rigcheck.rules.mcp  # noqa: E402 - imported for its registrations
import rigcheck.rules.memory  # noqa: E402 - imported for its registrations
import rigcheck.rules.output_styles  # noqa: E402 - imported for its registrations
import rigcheck.rules.permissions  # noqa: E402 - imported for its registrations
import rigcheck.rules.references  # noqa: E402 - imported for its registrations
import rigcheck.rules.rules_dir  # noqa: E402 - imported for its registrations
import rigcheck.rules.secrets  # noqa: E402 - imported for its registrations
import rigcheck.rules.settings  # noqa: E402 - imported for its registrations
import rigcheck.rules.skill_body  # noqa: E402 - imported for its registrations
import rigcheck.rules.skills  # noqa: E402 - imported for its registrations
import rigcheck.rules.suppressions  # noqa: E402, F401 - imported for its registrations
