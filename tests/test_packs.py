"""The rule packs: the constants, and the decorator's rejection of an unknown pack."""

import argparse

import pytest

from rigcheck.cli import parse_packs
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
    assert PACKS == ("core", "advice", "house", "deep")
    assert frozenset({"core", "advice"}) == DEFAULT_PACKS


def test_default_packs_exclude_deep() -> None:
    assert "deep" not in DEFAULT_PACKS


def test_unknown_pack_message_lists_every_pack() -> None:
    def check(rig: Rig) -> tuple[Finding, ...]:
        """A throwaway check that yields no findings."""
        return ()

    decorator = rule("packs-throwaway", "extra", Severity.INFO, "Fix it.", ("rigcheck:packs",))
    try:
        with pytest.raises(ValueError, match="unknown pack") as rule_error:
            decorator(check)
    finally:
        REGISTRY.pop("packs-throwaway", None)
    assert str(rule_error.value) == "rule packs-throwaway has unknown pack 'extra'; packs are core, advice, house and deep"
    with pytest.raises(argparse.ArgumentTypeError) as parse_error:
        parse_packs("core,extra")
    assert str(parse_error.value) == "unknown pack 'extra'; packs are core, advice, house and deep"


def test_parse_packs_accepts_deep() -> None:
    assert parse_packs("core, deep") == {"core", "deep"}
    assert parse_packs("deep") == {"deep"}
