import argparse
import json
from pathlib import Path

import pytest

from rigcheck import __version__, engine
from rigcheck.cli import _RULE_DOCS, _rule_doc, _rules_to_run, main, parse_packs
from rigcheck.model import Finding, Rig, Severity
from rigcheck.rules import DEFAULT_PACKS, PACKS, REGISTRY, rule
from support import Workspace, write


def test_version_flag_prints_package_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"rigcheck {__version__}"


def test_unknown_flag_exits_with_usage_error() -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--no-such-flag"])
    assert exit_info.value.code == 2


@pytest.mark.parametrize(("value", "window"), [("200k", 200_000), ("200K", 200_000), ("1m", 1_000_000), ("1M", 1_000_000), ("1500", 1_500)])
def test_window_accepts_k_and_m_suffixes(workspace: Workspace, capsys: pytest.CaptureFixture[str], value: str, window: int) -> None:
    main(["check", str(workspace.rig()), "--home", str(workspace.home), "--format", "json", "--window", value])
    assert json.loads(capsys.readouterr().out)["budget"]["window"] == window


@pytest.mark.parametrize("value", ["0", "-5", "abc", "1.5m", "k", "200kb", ""])
def test_window_rejects_garbage(workspace: Workspace, capsys: pytest.CaptureFixture[str], value: str) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["check", str(workspace.rig()), "--home", str(workspace.home), "--window", value])
    assert exit_info.value.code == 2
    assert "window must be a positive number of tokens, like 200k or 1m" in capsys.readouterr().err


def _warn_rig(workspace: Workspace, claude_md: str = "Read `docs/gone.md`.\n") -> Path:
    """A rig whose one finding is reference-path-missing (warn), plus whatever ``claude_md`` adds."""
    rig = workspace.rig()
    write(rig / "docs" / "other.md", "x\n")
    write(rig / "CLAUDE.md", claude_md)
    return rig


def _check(workspace: Workspace, rig: Path, *flags: str) -> int:
    return main(["check", str(rig), "--home", str(workspace.home), *flags])


def test_only_filters_json_findings(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    rig = _warn_rig(workspace, "Read `docs/gone.md`.\n\n@missing.md\n")
    assert _check(workspace, rig, "--format", "json") == 1
    assert {finding["rule"] for finding in json.loads(capsys.readouterr().out)["findings"]} == {"reference-path-missing", "import-unresolved"}
    assert _check(workspace, rig, "--format", "json", "--only", "reference-path-missing") == 0
    assert [finding["rule"] for finding in json.loads(capsys.readouterr().out)["findings"]] == ["reference-path-missing"]


def test_only_filters_text_findings(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    rig = _warn_rig(workspace, "Read `docs/gone.md`.\n\n@missing.md\n")
    assert _check(workspace, rig, "--only", "import-unresolved, reference-script-missing") == 1
    out = capsys.readouterr().out
    assert "import-unresolved" in out
    assert "reference-path-missing" not in out


def test_only_with_an_unknown_rule_id_names_the_closest(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        _check(workspace, workspace.rig(), "--only", "reference-path-missing,reference-path-mising")
    assert exit_info.value.code == 2
    assert "unknown rule id 'reference-path-mising'; closest: reference-path-missing" in capsys.readouterr().err


def test_only_with_no_rule_id_is_a_usage_error(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        _check(workspace, workspace.rig(), "--only", " , ")
    assert exit_info.value.code == 2
    assert "give at least one rule id" in capsys.readouterr().err


@pytest.mark.parametrize(("flags", "code"), [((), 0), (("--fail-on", "error"), 0), (("--fail-on", "warn"), 1), (("--fail-on", "info"), 1)])
def test_fail_on_sets_the_lowest_failing_severity(
    workspace: Workspace, capsys: pytest.CaptureFixture[str], flags: tuple[str, ...], code: int
) -> None:
    rig = _warn_rig(workspace)
    assert _check(workspace, rig, "--format", "json", *flags) == code
    assert {finding["severity"] for finding in json.loads(capsys.readouterr().out)["findings"]} == {"warn"}


def test_fail_on_rejects_an_unknown_severity(workspace: Workspace) -> None:
    with pytest.raises(SystemExit) as exit_info:
        _check(workspace, workspace.rig(), "--fail-on", "warning")
    assert exit_info.value.code == 2


def _suppress(rig: Path, *entries: str) -> None:
    write(rig / ".rigcheck.toml", "\n".join(f"[[suppress]]\n{entry}" for entry in entries))


def test_suppressed_finding_does_not_fail(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    rig = workspace.rig()
    write(rig / "CLAUDE.md", "# Project\n\n@missing.md\n")
    assert _check(workspace, rig, "--fail-on", "error") == 1
    _suppress(rig, 'rule = "import-unresolved"\nreason = "generated at build time"\n')
    assert _check(workspace, rig, "--fail-on", "error") == 0
    capsys.readouterr()


def test_json_lists_suppressed_with_reason(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    rig = _warn_rig(workspace)
    _suppress(rig, 'rule = "reference-path-missing"\nreason = "moved"\n')
    _check(workspace, rig, "--format", "json")
    report = json.loads(capsys.readouterr().out)
    assert report["summary"]["suppressed"] == 1
    assert "reference-path-missing" not in [finding["rule"] for finding in report["findings"]]
    [entry] = report["suppressed"]
    assert (entry["rule"], entry["line"], entry["reason"]) == ("reference-path-missing", 1, "moved")
    assert entry["path"].endswith("/CLAUDE.md")


def test_json_reason_null_when_missing(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    rig = _warn_rig(workspace)
    _suppress(rig, 'rule = "reference-path-missing"\n')
    _check(workspace, rig, "--format", "json")
    [entry] = json.loads(capsys.readouterr().out)["suppressed"]
    assert entry["reason"] is None


def test_only_filters_suppressed(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    rig = _warn_rig(workspace, "Read `docs/gone.md`.\n\n@missing.md\n")
    _suppress(rig, 'rule = "reference-path-missing"\nreason = "moved"\n', 'rule = "import-unresolved"\nreason = "generated"\n')
    _check(workspace, rig, "--format", "json")
    assert {entry["rule"] for entry in json.loads(capsys.readouterr().out)["suppressed"]} == {"reference-path-missing", "import-unresolved"}
    _check(workspace, rig, "--format", "json", "--only", "reference-path-missing")
    report = json.loads(capsys.readouterr().out)
    assert [entry["rule"] for entry in report["suppressed"]] == ["reference-path-missing"]
    assert report["summary"]["suppressed"] == 1


def test_sibling_that_is_not_a_directory_is_a_usage_error(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    missing = workspace.home / "work" / "no-such-sibling"
    with pytest.raises(SystemExit) as exit_info:
        _check(workspace, workspace.rig(), "--sibling", str(workspace.rig("server")), "--sibling", str(missing))
    assert exit_info.value.code == 2
    assert f"--sibling is not a directory: {missing}" in capsys.readouterr().err


def test_packs_unknown_name_exits_2(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        _check(workspace, workspace.rig(), "--packs", "extra")
    assert exit_info.value.code == 2
    assert "unknown pack 'extra'" in capsys.readouterr().err


def test_packs_parses_list() -> None:
    assert parse_packs("core, house") == {"core", "house"}
    for value in ("", "core,", "core,,house"):
        with pytest.raises(argparse.ArgumentTypeError) as excinfo:
            parse_packs(value)
        assert str(excinfo.value) == f"empty pack name in {value!r}; give packs like core,advice"


def _register_house_rule() -> str:
    def check(rig: Rig) -> tuple[Finding, ...]:
        """A throwaway check that yields no findings."""
        return ()

    rule_id = "packs-house-throwaway"
    rule(rule_id, "house", Severity.INFO, "Fix it.", ("rigcheck:packs",))(check)
    return rule_id


def test_rules_to_run_default_excludes_house() -> None:
    rule_id = _register_house_rule()
    try:
        ids = {r.id for r in _rules_to_run(DEFAULT_PACKS, None)}
    finally:
        REGISTRY.pop(rule_id, None)
    assert rule_id not in ids
    assert "reference-path-missing" in ids


def test_rules_to_run_only_wins() -> None:
    rule_id = _register_house_rule()
    try:
        ids = {r.id for r in _rules_to_run(DEFAULT_PACKS, frozenset({rule_id}))}
    finally:
        REGISTRY.pop(rule_id, None)
    assert rule_id in ids


def test_rules_to_run_always_includes_engine_rules() -> None:
    ids = {r.id for r in _rules_to_run(frozenset({"house"}), None)}
    assert ids >= engine.UNSUPPRESSIBLE


def test_packs_house_skips_core_rules_and_their_suppressions(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    rig = _warn_rig(workspace)
    _suppress(rig, 'rule = "reference-path-missing"\nreason = "moved"\n')
    _check(workspace, rig, "--format", "json")
    assert json.loads(capsys.readouterr().out)["summary"]["suppressed"] == 1
    _check(workspace, rig, "--format", "json", "--packs", "house")
    report = json.loads(capsys.readouterr().out)
    rules = [finding["rule"] for finding in report["findings"]]
    assert "reference-path-missing" not in rules
    assert "suppression-unused" not in rules
    assert report["summary"]["suppressed"] == 0


def test_rules_lists_every_registered_rule_once(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["rules"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == len(REGISTRY)
    ids = [line.split()[0] for line in lines]
    for rule_id in REGISTRY:
        assert ids.count(rule_id) == 1


def test_rules_orders_by_pack_then_id(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["rules"]) == 0
    rows = [line.split() for line in capsys.readouterr().out.splitlines()]
    parsed = [(row[1], row[0]) for row in rows]
    assert parsed == sorted(parsed, key=lambda pair: (PACKS.index(pair[0]), pair[1]))


def test_rules_json_has_catalog_fields(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["rules", "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload) == len(REGISTRY)
    assert all(set(entry) == {"id", "pack", "severity", "summary", "fix", "evidence"} for entry in payload)
    entry = next(entry for entry in payload if entry["id"] == "suppression-no-reason")
    meta = REGISTRY["suppression-no-reason"]
    assert entry["pack"] == meta.pack == "core"
    assert entry["severity"] == meta.severity.value == "warn"
    assert entry["evidence"] == list(meta.evidence) == ["rigcheck:suppressions"]


def test_explain_prints_rule_fields_and_area_doc(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["explain", "suppression-no-reason"]) == 0
    out = capsys.readouterr().out
    assert "id        suppression-no-reason" in out
    assert "pack      core" in out
    assert "severity  warn" in out
    assert "evidence  rigcheck:suppressions" in out
    assert "docs      docs/rules/suppressions.md" in out


def test_explain_json_matches_registry(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["explain", "suppression-no-reason", "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    meta = REGISTRY["suppression-no-reason"]
    assert payload["id"] == meta.id
    assert payload["pack"] == meta.pack
    assert payload["severity"] == meta.severity.value
    assert payload["summary"] == meta.summary
    assert payload["fix"] == meta.fix
    assert payload["evidence"] == list(meta.evidence)
    assert payload["docs"] == "docs/rules/suppressions.md"


def test_explain_unknown_id_exits_2_with_closest(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["explain", "suppresion-no-reason"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "unknown rule id 'suppresion-no-reason'; closest: suppression-no-reason" in captured.err


def test_explain_lists_every_evidence_string(capsys: pytest.CaptureFixture[str]) -> None:
    def check(rig: Rig) -> tuple[Finding, ...]:
        """A throwaway check that yields no findings."""
        return ()

    rule_id = "explain-throwaway"
    rule(rule_id, "house", Severity.INFO, "Fix it.", ("rigcheck:one", "official:two"))(check)
    try:
        assert main(["explain", rule_id]) == 0
    finally:
        REGISTRY.pop(rule_id, None)
    out = capsys.readouterr().out
    assert "evidence  rigcheck:one" in out
    assert " " * 10 + "official:two" in out
    assert "docs" not in out


def test_rule_doc_none_without_docs_folder(tmp_path: Path) -> None:
    assert _rule_doc("suppression-no-reason", tmp_path / "missing") is None


def test_every_registered_rule_has_an_area_doc() -> None:
    missing = [rule_id for rule_id in REGISTRY if _rule_doc(rule_id, _RULE_DOCS) is None]
    assert missing == []
