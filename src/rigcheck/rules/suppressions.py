"""Rules on the checked repo's ``.rigcheck.toml`` suppressions."""

from collections.abc import Iterator

from rigcheck.model import Finding, Layer, LoadClass, Rig, Severity
from rigcheck.rules import REGISTRY, rule

NO_REASON_FIX = "Give the suppression a reason: say why the finding does not apply here, so a later reader can tell when it stops being true."
UNUSED_FIX = "Remove the suppression, or correct its rule id or path so it matches the finding it is meant to silence."


@rule("suppression-no-reason", "core", Severity.WARN, NO_REASON_FIX, ("rigcheck:suppressions",))
def suppression_no_reason(rig: Rig) -> Iterator[Finding]:
    """A .rigcheck.toml suppression has no reason."""
    meta = REGISTRY["suppression-no-reason"]
    path = rig.repo_root / ".rigcheck.toml"
    for suppression in rig.suppressions:
        if suppression.reason is None or not suppression.reason.strip():
            message = f"suppression of `{suppression.rule}` has no reason"
            yield Finding("suppression-no-reason", meta.severity, path, suppression.line, message, meta.fix, Layer.REPO, LoadClass.NOT_LOADED)


@rule("suppression-unused", "core", Severity.INFO, UNUSED_FIX, ("rigcheck:suppressions",))
def suppression_unused(rig: Rig) -> Iterator[Finding]:
    """A .rigcheck.toml suppression matched no finding; the engine emits this finding."""
    del rig
    yield from ()
