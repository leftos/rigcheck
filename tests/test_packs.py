"""The rule packs: the constants, and the decorator's rejection of an unknown pack."""

import pytest

from rigcheck.model import Finding, Rig, Severity
from rigcheck.rules import DEFAULT_PACKS, PACKS, REGISTRY, rule


def test_rule_with_unknown_pack_raises() -> None:
    def check(rig: Rig) -> tuple[Finding, ...]:
        """A throwaway check that yields no findings."""
        return ()

    decorator = rule("packs-throwaway", "extra", Severity.INFO, "Fix it.", ("rigcheck:packs",))
    try:
        with pytest.raises(ValueError, match="unknown pack 'extra'"):
            decorator(check)
    finally:
        REGISTRY.pop("packs-throwaway", None)


def test_packs_constant() -> None:
    assert PACKS == ("core", "advice", "house")
    assert frozenset({"core", "advice"}) == DEFAULT_PACKS
