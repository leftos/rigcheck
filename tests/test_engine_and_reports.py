import re
from collections.abc import Iterator
from pathlib import Path

import pytest

from rigcheck import engine
from rigcheck.cli import main
from rigcheck.discover import discover
from rigcheck.model import DEFAULT_WINDOW, Finding, Layer, LoadClass, Rig, Rule, Severity
from rigcheck.report import budget, terminal
from rigcheck.rules import REGISTRY
from support import Workspace, run_cli, run_json, write

ANSI = re.compile(r"\x1b\[")


def _raising(rig: Rig) -> Iterator[Finding]:
    del rig
    raise RuntimeError("boom")


def _bad_rig(workspace: Workspace) -> Path:
    repo = workspace.rig()
    write(repo / "CLAUDE.md", "# Project\n\nSee @docs/missing.md and @AGENTS.md\n")
    write(repo / "AGENTS.md", "# Agents\n")
    write(repo / "AGENTS.override.md", "Codex.\n")
    return repo


def test_raising_rule_becomes_internal_error(workspace: Workspace) -> None:
    rig = discover(workspace.rig(), workspace.home, DEFAULT_WINDOW)
    stub = Rule("stub", "core", Severity.WARN, "Stub.", "None.", ("test",), _raising)
    findings = engine.run(rig, [stub, REGISTRY["claude-never-reads"]])
    assert [finding.rule_id for finding in findings] == ["internal-error"]
    assert findings[0].severity is Severity.ERROR
    assert "stub" in findings[0].message
    assert "RuntimeError: boom" in findings[0].message


def test_rank_orders_severity_load_class_layer_path() -> None:
    def finding(severity: Severity, load: LoadClass | None, layer: Layer | None, path: str) -> Finding:
        return Finding("r", severity, Path(path), 1, "m", "f", layer, load)

    items = [
        finding(Severity.INFO, LoadClass.EVERY_TURN, Layer.REPO, "a"),
        finding(Severity.ERROR, LoadClass.CONFIG, Layer.REPO, "a"),
        finding(Severity.ERROR, LoadClass.EVERY_TURN, Layer.USER, "a"),
        finding(Severity.ERROR, LoadClass.EVERY_TURN, Layer.REPO, "b"),
        finding(Severity.ERROR, LoadClass.EVERY_TURN, Layer.REPO, "a"),
        finding(Severity.ERROR, None, None, "a"),
    ]
    ranked = engine.rank(items)
    assert ranked == [items[4], items[3], items[2], items[1], items[5], items[0]]


def test_json_report_schema_and_determinism(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _bad_rig(workspace)
    code, first = run_json(capsys, repo, workspace.home)
    _, second_text = run_cli(capsys, repo, workspace.home, "json")
    _, third_text = run_cli(capsys, repo, workspace.home, "json")
    assert second_text == third_text
    assert code == 1
    assert set(first) == {"schema", "rigcheck", "target", "repo_root", "summary", "findings", "budget", "artifacts"}
    assert first["schema"] == 1
    assert set(first["summary"]) == {"error", "warn", "info"}
    assert first["summary"]["error"] >= 1
    finding_keys = {"rule", "severity", "layer", "load_class", "path", "line", "message", "fix", "evidence"}
    assert all(set(finding) == finding_keys for finding in first["findings"])
    assert all(set(artifact) == {"path", "kind", "layer", "load_class", "plugin", "tokens_est"} for artifact in first["artifacts"])
    unresolved = next(finding for finding in first["findings"] if finding["rule"] == "import-unresolved")
    assert (unresolved["severity"], unresolved["layer"], unresolved["line"]) == ("error", "repo", 3)
    assert unresolved["evidence"] == ["official:CM2"]
    assert "\\" not in unresolved["path"]


def test_text_report_without_tty_has_no_ansi(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _bad_rig(workspace)
    code, out = run_cli(capsys, repo, workspace.home, "text")
    assert code == 1
    assert not ANSI.search(out)
    assert out.startswith("rigcheck ")
    assert "  CLAUDE.md:3  ERROR  import-unresolved  " in out
    assert "      fix: " in out
    assert out.rstrip().endswith("1 errors · 0 warnings · 1 info")


def test_text_report_colors_only_when_asked(workspace: Workspace) -> None:
    rig = discover(_bad_rig(workspace), workspace.home, DEFAULT_WINDOW)
    findings = engine.run(rig, REGISTRY.values())
    report = budget.compute(rig)
    assert ANSI.search(terminal.render(rig, findings, report, color=True))
    assert not ANSI.search(terminal.render(rig, findings, report, color=False))


def _budget_rig(workspace: Workspace) -> Path:
    repo = workspace.rig()
    write(repo / "CLAUDE.md", "# Project\n\nUse uv.\n")
    write(workspace.home / ".claude" / "skills" / "lint" / "SKILL.md", "---\nname: lint\ndescription: " + "Lints. " * 40 + "\n---\n")
    write(workspace.home / ".claude" / "agents" / "fixer.md", "---\nname: fixer\ndescription: Fixes.\n---\n")
    return repo


def test_json_budget_shape(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _budget_rig(workspace)
    _, payload = run_json(capsys, repo, workspace.home)
    report = payload["budget"]
    assert set(report) == {"window", "every_turn", "skill_listing", "agent_descriptions"}
    assert report["window"] == 200_000
    sources = report["every_turn"]["sources"]
    assert [(source["path"], source["layer"], source["kind"]) for source in sources] == [((repo / "CLAUDE.md").as_posix(), "repo", "instructions")]
    assert report["every_turn"]["total_est"] == sources[0]["tokens_est"]
    artifact = next(artifact for artifact in payload["artifacts"] if artifact["path"] == sources[0]["path"])
    assert artifact["tokens_est"] == sources[0]["tokens_est"]
    listing_keys = {"tokens_est", "budget", "entries", "by_layer"}
    assert set(report["skill_listing"]) == listing_keys
    assert set(report["agent_descriptions"]) == listing_keys
    assert (report["skill_listing"]["budget"], report["skill_listing"]["entries"]) == (2_000, 1)
    assert report["skill_listing"]["by_layer"] == {"user": report["skill_listing"]["tokens_est"]}
    assert (report["agent_descriptions"]["budget"], report["agent_descriptions"]["entries"]) == (15_000, 1)


def test_text_report_starts_with_the_budget_block(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run_cli(capsys, _budget_rig(workspace), workspace.home, "text")
    lines = out.splitlines()
    assert code == 0
    assert lines[0].startswith("rigcheck ")
    assert lines[2] == "Context budget (≈ tokens, 200k window)"
    assert re.fullmatch(r"  every turn   ≈\d+ total", lines[3])
    assert re.fullmatch(r"    ≈\d+  CLAUDE\.md", lines[4])
    assert re.fullmatch(r"  skill listing   ≈\d+ / 2,000 \(\d+%\)   user \d+", lines[5])
    assert re.fullmatch(r"  agent descriptions   ≈\d+ / 15,000 \(\d+%\)   user \d+", lines[6])
    assert out.rstrip().endswith("0 errors · 0 warnings · 0 info")


def test_text_report_marks_a_listing_over_budget(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _budget_rig(workspace)
    main(["check", str(repo), "--home", str(workspace.home), "--window", "1500"])
    lines = capsys.readouterr().out.splitlines()
    assert "Context budget (≈ tokens, 1,500 window)" in lines
    listing = next(line for line in lines if line.startswith("  skill listing"))
    assert listing.endswith("  over budget")
    agents = next(line for line in lines if line.startswith("  agent descriptions"))
    assert "over budget" not in agents
    rig = discover(repo, workspace.home, 1_500)
    colored = terminal.render(rig, [], budget.compute(rig), color=True)
    assert "\x1b[33m" in next(line for line in colored.splitlines() if line.startswith("  skill listing"))


def test_user_layer_paths_display_with_tilde(workspace: Workspace) -> None:
    rig = discover(workspace.rig(), workspace.home, DEFAULT_WINDOW)
    path = workspace.home / ".claude" / "CLAUDE.md"
    assert terminal.display_path(rig, path, Layer.USER) == "~/.claude/CLAUDE.md"


def test_clean_rig_exits_zero(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    repo = workspace.rig()
    write(repo / "CLAUDE.md", "# Project\n")
    code, out = run_cli(capsys, repo, workspace.home, "text")
    assert code == 0
    assert out.rstrip().endswith("0 errors · 0 warnings · 0 info")


def test_check_rejects_missing_directory(workspace: Workspace) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["check", str(workspace.home / "absent"), "--home", str(workspace.home)])
    assert exit_info.value.code == 2
