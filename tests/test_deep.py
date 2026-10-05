"""The --deep runner: file selection, the consent listing, the cache, the envelope unwrap and the production argv."""

import dataclasses
import io
import json
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from rigcheck import deep
from rigcheck.discover import discover, memory_dir
from rigcheck.model import DEFAULT_WINDOW, Rig, Verdict
from rigcheck.rules import REGISTRY
from support import Workspace, write

TOKEN = "gh" + "p_" + "a1B2c3D4" * 5
SCHEMA = '{"type": "object"}'
STRUCTURED = {"verdicts": [{"line": 3, "message": "vague"}]}


def _parse(path: Path, data: dict) -> tuple[Verdict, ...]:
    return tuple(Verdict("fake", path, item.get("line"), item["message"]) for item in data["verdicts"])


FAKE = deep.Family("fake", "1", SCHEMA, lambda text: "Judge this:\n" + text, _parse)


def _envelope(structured: object, **overrides: object) -> str:
    body: dict[str, Any] = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "structured_output": structured,
        "result": json.dumps(structured),
        "total_cost_usd": 0.001,
        "num_turns": 1,
        "stop_reason": "end_turn",
        "terminal_reason": "completed",
        "usage": {},
        "modelUsage": {},
        "session_id": "session",
    }
    body.update(overrides)
    return json.dumps(body)


class CountingRunner:
    """A fake runner that counts its calls and returns a fixed stdout."""

    def __init__(self, stdout: str) -> None:
        self.stdout = stdout
        self.calls: list[tuple[str, str]] = []

    def __call__(self, prompt: str, schema: str) -> str:
        self.calls.append((prompt, schema))
        return self.stdout


class Tty(io.StringIO):
    """A stdin that claims to be a terminal."""

    def isatty(self) -> bool:
        return True


def _rig(workspace: Workspace) -> Rig:
    return discover(workspace.rig(), workspace.home, DEFAULT_WINDOW)


def _one_file_rig(workspace: Workspace, text: str = "# Project\n\nBe brief.\n") -> Rig:
    write(workspace.rig() / "CLAUDE.md", text)
    return _rig(workspace)


def _sent_names(listing: deep.Listing) -> set[str]:
    return {path.name for path, _ in listing.sent}


def test_selects_instruction_rule_skill_command_agent_on_repo_and_user_layers(workspace: Workspace) -> None:
    repo = workspace.rig()
    claude = workspace.home / ".claude"
    expected = [
        write(repo / "CLAUDE.md", "# Project\n"),
        write(repo / "sub" / "CLAUDE.md", "# Sub\n"),
        write(repo / ".claude" / "rules" / "style.md", "Style.\n"),
        write(repo / ".claude" / "skills" / "demo" / "SKILL.md", "---\nname: demo\ndescription: Demo.\n---\n\nBody.\n"),
        write(repo / ".claude" / "commands" / "go.md", "Go.\n"),
        write(repo / ".claude" / "agents" / "helper.md", "---\nname: helper\ndescription: Helps.\n---\n\nHelp.\n"),
        write(claude / "CLAUDE.md", "# Mine\n"),
        write(claude / "skills" / "mine" / "SKILL.md", "---\nname: mine\ndescription: Mine.\n---\n\nBody.\n"),
        write(claude / "agents" / "aide.md", "---\nname: aide\ndescription: Aids.\n---\n\nAid.\n"),
        write(claude / "commands" / "run.md", "Run.\n"),
    ]
    listing = deep.plan(_rig(workspace), (FAKE,))
    assert {path for path, _ in listing.sent} == set(expected)
    assert listing.not_sent == ()


def test_never_selects_settings_hooks_mcp_memory_or_plugin_files(workspace: Workspace) -> None:
    repo = workspace.rig()
    home = workspace.home
    hooks = '{"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "true"}]}]}}\n'
    write(repo / ".claude" / "settings.json", hooks)
    write(repo / ".claude" / "settings.local.json", "{}\n")
    write(repo / ".mcp.json", '{"mcpServers": {}}\n')
    write(home / ".claude" / "settings.json", '{"enabledPlugins": {"demo@local": true}}\n')
    write(home / ".claude.json", '{"mcpServers": {}}\n')
    memory = memory_dir(repo, home)
    write(memory / "MEMORY.md", "- [Topic](topic.md)\n")
    write(memory / "topic.md", "---\nname: topic\n---\nTopic.\n")
    plugin = home / ".claude" / "plugins" / "cache" / "demo"
    installed = {"version": 2, "plugins": {"demo@local": [{"scope": "user", "installPath": plugin.as_posix()}]}}
    write(home / ".claude" / "plugins" / "installed_plugins.json", json.dumps(installed))
    write(plugin / "skills" / "x" / "SKILL.md", "---\nname: x\ndescription: X.\n---\n")
    write(plugin / "hooks" / "hooks.json", "{}\n")
    write(plugin / ".claude-plugin" / "plugin.json", '{"name": "demo"}\n')
    rig = _rig(workspace)
    assert any(artifact.path == plugin / "skills" / "x" / "SKILL.md" for artifact in rig.artifacts)
    listing = deep.plan(rig, (FAKE,))
    assert listing.sent == ()
    assert listing.not_sent == ()


def test_skips_a_shadowed_agents_md(workspace: Workspace) -> None:
    repo = workspace.rig()
    write(repo / "CLAUDE.md", "# Project\n")
    write(repo / "AGENTS.md", "# Agents\n")
    assert _sent_names(deep.plan(_rig(workspace), (FAKE,))) == {"CLAUDE.md"}


def test_file_with_a_secret_is_not_sent(workspace: Workspace) -> None:
    rig = _one_file_rig(workspace, "# Project\n\nexport GITHUB_TOKEN=" + TOKEN + "\n")
    listing = deep.plan(rig, (FAKE,))
    assert listing.sent == ()
    assert listing.not_sent == ((rig.repo_root / "CLAUDE.md", "holds a secret"),)
    assert listing.calls == 0


def test_suppressed_secret_is_still_not_sent(workspace: Workspace) -> None:
    repo = workspace.rig()
    write(repo / ".rigcheck.toml", '[[suppress]]\nrule = "secret-literal"\nreason = "test token"\n')
    rig = _one_file_rig(workspace, "# Project\n\nexport GITHUB_TOKEN=" + TOKEN + "\n")
    assert rig.suppressions
    assert deep.plan(rig, (FAKE,)).not_sent == ((repo / "CLAUDE.md", "holds a secret"),)


def test_file_over_the_byte_cap_is_not_sent(workspace: Workspace) -> None:
    repo = workspace.rig()
    write(repo / "CLAUDE.md", "# Project\n")
    write(repo / ".claude" / "rules" / "big.md", "x" * deep.MAX_BYTES + "\n")
    write(repo / ".claude" / "rules" / "edge.md", "x" * (deep.MAX_BYTES - 1) + "\n")
    listing = deep.plan(_rig(workspace), (FAKE,))
    assert _sent_names(listing) == {"CLAUDE.md", "edge.md"}
    assert listing.not_sent == ((repo / ".claude" / "rules" / "big.md", "over 100,000 bytes"),)


def test_call_count_is_files_times_families(workspace: Workspace) -> None:
    repo = workspace.rig()
    write(repo / "CLAUDE.md", "# Project\n")
    write(repo / ".claude" / "commands" / "go.md", "Go.\n")
    rig = _rig(workspace)
    other = deep.Family("other", "1", SCHEMA, str, _parse)
    assert deep.plan(rig, (FAKE, other)).calls == 4
    assert deep.plan(rig, (FAKE,)).calls == 2
    assert deep.plan(rig, ()).calls == 0


def test_listing_shows_paths_bytes_model_and_calls_without_contents(workspace: Workspace) -> None:
    sentinel = "SENTINEL-BODY-TEXT"
    repo = workspace.rig()
    write(repo / ".claude" / "commands" / "go.md", "Go " + sentinel + ".\n")
    write(workspace.home / ".claude" / "CLAUDE.md", "# Mine\n")
    write(repo / "CLAUDE.md", "# Project\n\nexport GITHUB_TOKEN=" + TOKEN + "\n")
    rig = _rig(workspace)
    text = deep.format_listing(deep.plan(rig, (FAKE,)), rig)
    assert sentinel not in text
    assert TOKEN not in text
    lines = text.splitlines()
    assert "  .claude/commands/go.md  23 bytes" in lines
    assert "  ~/.claude/CLAUDE.md  7 bytes" in lines
    assert lines[-3:] == ["Not sent:", "  CLAUDE.md  (holds a secret)", "Model haiku, 2 call(s)."]


def test_cache_dir_honours_xdg_cache_home(tmp_path: Path) -> None:
    assert deep.cache_dir({"XDG_CACHE_HOME": str(tmp_path / "xdg")}, tmp_path / "home") == tmp_path / "xdg" / "rigcheck"


def test_cache_dir_defaults_under_home(tmp_path: Path) -> None:
    home = tmp_path / "home"
    assert deep.cache_dir({}, home) == home / ".cache" / "rigcheck"
    assert deep.cache_dir({"XDG_CACHE_HOME": ""}, home) == home / ".cache" / "rigcheck"


def test_cache_key_changes_with_family_version_model_schema_and_text() -> None:
    base = deep.cache_key(FAKE, "haiku", "text")
    assert base == deep.cache_key(FAKE, "haiku", "text")
    variants = [
        deep.cache_key(deep.Family("other", "1", SCHEMA, FAKE.build_prompt, _parse), "haiku", "text"),
        deep.cache_key(deep.Family("fake", "2", SCHEMA, FAKE.build_prompt, _parse), "haiku", "text"),
        deep.cache_key(deep.Family("fake", "1", '{"type": "array"}', FAKE.build_prompt, _parse), "haiku", "text"),
        deep.cache_key(FAKE, "sonnet", "text"),
        deep.cache_key(FAKE, "haiku", "text!"),
    ]
    assert len({base, *variants}) == 6


def test_cache_key_changes_with_the_system_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    base = deep.cache_key(FAKE, "haiku", "text")
    monkeypatch.setattr(deep, "SYSTEM_PROMPT", deep.SYSTEM_PROMPT + " Be terse.")
    assert deep.cache_key(FAKE, "haiku", "text") != base


def test_unwritable_cache_keeps_the_verdict(workspace: Workspace, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    blocker = write(tmp_path / "blocker", "a file, not a folder\n")
    rig = _one_file_rig(workspace)
    verdicts, errors = _run(rig, CountingRunner(_envelope(STRUCTURED)), blocker / "cache")
    assert errors == []
    assert verdicts == {"fake": (Verdict("fake", rig.repo_root / "CLAUDE.md", 3, "vague"),)}
    assert "rigcheck: could not cache a --deep answer: " in capsys.readouterr().err


def test_failing_secret_scan_holds_every_file_back(workspace: Workspace, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(rig: Rig) -> list:
        raise RuntimeError("scan broke")

    repo = workspace.rig()
    write(repo / "CLAUDE.md", "# Project\n")
    write(repo / ".claude" / "commands" / "go.md", "Go.\n")
    rig = _rig(workspace)
    monkeypatch.setitem(REGISTRY, "secret-literal", dataclasses.replace(REGISTRY["secret-literal"], check=broken))
    listing = deep.plan(rig, (FAKE,))
    assert listing.sent == ()
    assert listing.calls == 0
    assert set(listing.not_sent) == {(repo / "CLAUDE.md", "secret scan failed"), (repo / ".claude" / "commands" / "go.md", "secret scan failed")}


def test_empty_file_is_not_sent(workspace: Workspace) -> None:
    repo = workspace.rig()
    write(repo / "CLAUDE.md", "# Project\n")
    write(repo / ".claude" / "commands" / "empty.md", "")
    write(repo / ".claude" / "rules" / "big.md", "x" * deep.MAX_BYTES + "\nexport GITHUB_TOKEN=" + TOKEN + "\n")
    listing = deep.plan(_rig(workspace), (FAKE,))
    assert _sent_names(listing) == {"CLAUDE.md"}
    assert listing.calls == 1
    assert set(listing.not_sent) == {(repo / ".claude" / "commands" / "empty.md", "empty"), (repo / ".claude" / "rules" / "big.md", "holds a secret")}


def _run(rig: Rig, runner: Callable[[str, str], str], cache: Path) -> tuple[dict[str, tuple[Verdict, ...]], list]:
    return deep.run(rig, deep.plan(rig, (FAKE,)), runner, cache, (FAKE,))


def test_second_run_uses_the_cache(workspace: Workspace, tmp_path: Path) -> None:
    rig = _one_file_rig(workspace)
    cache = tmp_path / "cache"
    runner = CountingRunner(_envelope(STRUCTURED))
    first, _ = _run(rig, runner, cache)
    assert len(runner.calls) == 1
    second, errors = _run(_rig(workspace), runner, cache)
    assert len(runner.calls) == 1
    assert second == first
    assert errors == []


def test_changed_text_misses_the_cache(workspace: Workspace, tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    runner = CountingRunner(_envelope(STRUCTURED))
    _run(_one_file_rig(workspace), runner, cache)
    _run(_one_file_rig(workspace, "# Project\n\nBe briefer.\n"), runner, cache)
    assert len(runner.calls) == 2


def test_valid_envelope_becomes_verdicts(workspace: Workspace, tmp_path: Path) -> None:
    rig = _one_file_rig(workspace)
    runner = CountingRunner(_envelope(STRUCTURED))
    verdicts, errors = _run(rig, runner, tmp_path / "cache")
    assert errors == []
    assert verdicts == {"fake": (Verdict("fake", rig.repo_root / "CLAUDE.md", 3, "vague"),)}
    prompt, schema = runner.calls[0]
    assert prompt == "Judge this:\n# Project\n\nBe brief.\n"
    assert schema == SCHEMA
    assert len(list((tmp_path / "cache").glob("*.json"))) == 1


def _assert_one_deep_error(workspace: Workspace, tmp_path: Path, runner: Callable[[str, str], str]) -> None:
    rig = _one_file_rig(workspace)
    cache = tmp_path / "cache"
    verdicts, errors = _run(rig, runner, cache)
    assert [(finding.rule_id, finding.path) for finding in errors] == [("deep-error", rig.repo_root / "CLAUDE.md")]
    assert errors[0].message.startswith("deep check fake failed on this file: ")
    assert verdicts.get("fake", ()) == ()
    assert not cache.exists() or not any(cache.iterdir())


def test_is_error_envelope_becomes_deep_error(workspace: Workspace, tmp_path: Path) -> None:
    _assert_one_deep_error(workspace, tmp_path, CountingRunner(_envelope(STRUCTURED, is_error=True, subtype="error_max_budget_usd")))


def test_non_json_output_becomes_deep_error(workspace: Workspace, tmp_path: Path) -> None:
    _assert_one_deep_error(workspace, tmp_path, CountingRunner("Credit balance is too low"))


def test_missing_structured_output_becomes_deep_error(workspace: Workspace, tmp_path: Path) -> None:
    body = json.loads(_envelope(STRUCTURED))
    del body["structured_output"]
    _assert_one_deep_error(workspace, tmp_path, CountingRunner(json.dumps(body)))


def test_runner_exception_becomes_deep_error(workspace: Workspace, tmp_path: Path) -> None:
    def runner(prompt: str, schema: str) -> str:
        raise subprocess.TimeoutExpired(["claude"], deep.TIMEOUT_S)

    _assert_one_deep_error(workspace, tmp_path, runner)


@settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st.text())
def test_arbitrary_runner_output_never_raises(workspace: Workspace, stdout: str) -> None:
    rig = _one_file_rig(workspace)
    with tempfile.TemporaryDirectory(dir=workspace.home) as cache:
        _, errors = _run(rig, CountingRunner(stdout), Path(cache))
    assert all(finding.rule_id == "deep-error" for finding in errors)


def test_production_runner_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        seen["argv"] = argv
        seen["kwargs"] = kwargs
        return subprocess.CompletedProcess(argv, 0, stdout="out", stderr="")

    monkeypatch.setattr(deep.shutil, "which", lambda name: "/bin/claude" if name == "claude" else None)
    monkeypatch.setattr(deep.subprocess, "run", fake_run)
    assert deep.make_runner()("the prompt", SCHEMA) == "out"
    assert seen["argv"] == [
        "/bin/claude",
        "-p",
        "--output-format",
        "json",
        "--json-schema",
        SCHEMA,
        "--tools",
        "",
        "--no-session-persistence",
        "--safe-mode",
        "--model",
        "haiku",
        "--max-budget-usd",
        "0.50",
        "--system-prompt",
        deep.SYSTEM_PROMPT,
    ]
    kwargs = seen["kwargs"]
    assert kwargs["input"] == "the prompt"
    assert kwargs["timeout"] == deep.TIMEOUT_S
    assert kwargs["check"] is True
    assert "shell" not in kwargs


def test_make_runner_refuses_a_cmd_shim(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(deep.shutil, "which", lambda name: "C:/Users/me/AppData/Roaming/npm/claude.CMD")
    with pytest.raises(deep.DeepUnavailable) as unavailable:
        deep.make_runner()
    assert str(unavailable.value) == "--deep needs the native claude executable; claude.CMD is a cmd shim, which cannot pass the schema safely"


def test_make_runner_without_claude_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(deep.shutil, "which", lambda name: None)
    with pytest.raises(deep.DeepUnavailable, match="--deep needs the claude CLI on PATH"):
        deep.make_runner()


def _listing(calls: int) -> deep.Listing:
    sent = ((Path("CLAUDE.md"), 10),) if calls else ()
    return deep.Listing(sent=sent, not_sent=(), model=deep.MODEL, calls=calls)


def test_confirm_without_tty_and_without_yes_stops_with_2() -> None:
    stderr = io.StringIO()
    with pytest.raises(deep.DeepStop) as stop:
        deep.confirm(_listing(1), yes=False, stdin=io.StringIO("y\n"), stderr=stderr)
    assert stop.value.exit_code == 2
    assert "--deep needs --yes when stdin is not a terminal" in stderr.getvalue()


def test_confirm_yes_skips_the_prompt() -> None:
    stderr = io.StringIO()
    deep.confirm(_listing(1), yes=True, stdin=io.StringIO(""), stderr=stderr)
    assert stderr.getvalue() == ""


@pytest.mark.parametrize("answer", ["y\n", "YES\n", " Yes \n"])
def test_confirm_accepts_y_and_yes(answer: str) -> None:
    stderr = io.StringIO()
    deep.confirm(_listing(1), yes=False, stdin=Tty(answer), stderr=stderr)
    assert stderr.getvalue() == "Send 1 file(s) to claude (model haiku, 1 call(s))? [y/N] "


@pytest.mark.parametrize("answer", ["n\n", "\n", "", "yep\n"])
def test_confirm_declined_stops_with_2(answer: str) -> None:
    stderr = io.StringIO()
    with pytest.raises(deep.DeepStop) as stop:
        deep.confirm(_listing(1), yes=False, stdin=Tty(answer), stderr=stderr)
    assert stop.value.exit_code == 2
    assert stderr.getvalue().endswith("[y/N] --deep cancelled; nothing was sent\n")


def test_confirm_with_no_calls_does_not_prompt() -> None:
    stderr = io.StringIO()
    deep.confirm(_listing(0), yes=False, stdin=io.StringIO(""), stderr=stderr)
    assert stderr.getvalue() == ""
