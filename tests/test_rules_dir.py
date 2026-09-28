"""The rules-directory rules: unknown keys, unparseable frontmatter and rules linked out of the project."""

import os
from pathlib import Path

import pytest

from rigcheck import engine
from rigcheck.discover import MAX_BYTES, discover
from rigcheck.model import DEFAULT_WINDOW
from rigcheck.rules import REGISTRY
from support import Workspace, git_add, symlink_or_skip, write

RULE = Path(".claude") / "rules" / "style.md"
UNC_RULES = r"\\server\share\rules" if os.name == "nt" else "//server/share/rules"


def _run(workspace: Workspace, rule_id: str) -> list[tuple[str, int | None]]:
    repo = workspace.rig()
    findings = engine.run(discover(repo, workspace.home, DEFAULT_WINDOW), REGISTRY.values())
    return [(finding.message, finding.line) for finding in findings if finding.rule_id == rule_id]


def _findings(workspace: Workspace, rule_id: str, text: str, *, in_home: bool = False) -> list[tuple[str, int | None]]:
    repo = workspace.rig()
    write(repo / "CLAUDE.md", "# Project\n")
    write((workspace.home if in_home else repo) / RULE, text)
    return _run(workspace, rule_id)


def _link(repo: Path, name: str, target: Path) -> None:
    link = repo / ".claude" / "rules" / name
    link.parent.mkdir(parents=True, exist_ok=True)
    symlink_or_skip(link, os.fspath(target))


def test_key_unknown_suggests_case_fix(workspace: Workspace) -> None:
    text = "---\nPaths:\n  - src/**\n---\n\nStyle rules.\n"
    expected = [('unknown key "Paths" (did you mean "paths"?); Claude Code ignores it', 2)]
    assert _findings(workspace, "rule-key-unknown", text) == expected


def test_key_unknown_silent_when_yaml_invalid(workspace: Workspace) -> None:
    assert _findings(workspace, "rule-key-unknown", '---\nglobs: "src/**"\n') == []


def test_frontmatter_invalid_ignores_strict_only_yaml(workspace: Workspace) -> None:
    text = "---\npaths:\n  - src/**\ndescription: a: b\n---\n\nLoads anyway.\n"
    assert _findings(workspace, "rule-frontmatter-invalid", text) == []


def test_external_scoped_silent_without_paths(workspace: Workspace) -> None:
    repo = workspace.rig()
    write(repo / "CLAUDE.md", "# Project\n")
    external = write(workspace.home / "elsewhere-rules" / "plain.md", "External rule.\n")
    _link(repo, "shared", external.parent)
    assert _run(workspace, "rule-external-scoped") == []


def test_external_scoped_silent_on_user_layer(workspace: Workspace) -> None:
    text = "---\npaths:\n  - src/**\n---\n\nMine.\n"
    assert _findings(workspace, "rule-external-scoped", text, in_home=True) == []


def test_external_scoped_skips_network_links(workspace: Workspace, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = workspace.rig()
    write(repo / "CLAUDE.md", "# Project\n")
    link = repo / ".claude" / "rules" / "shared"
    link.parent.mkdir(parents=True, exist_ok=True)
    symlink_or_skip(link, UNC_RULES)
    monkeypatch.setattr("rigcheck.rules.rules_dir.is_outside", _fail_outside)
    rules = _every_rule_id(workspace)
    assert "rule-external-scoped" not in rules
    assert "internal-error" not in rules


def _fail_outside(*args: object) -> bool:
    raise AssertionError(f"is_outside was called with {args!r}")


def _every_rule_id(workspace: Workspace) -> list[str]:
    repo = workspace.rig()
    findings = engine.run(discover(repo, workspace.home, DEFAULT_WINDOW), REGISTRY.values())
    return [finding.rule_id for finding in findings]


def _in_git(workspace: Workspace, *names: str) -> None:
    repo = workspace.rig()
    for name in names:
        write(repo / name, "content\n")
    git_add(repo, list(names))


def test_glob_invalid_over_budget_once_per_rule(workspace: Workspace) -> None:
    text = '---\npaths: ["src/{1..600}.ts", "lib/{1..600}.ts"]\n---\n\nToo many.\n'
    expected = [("the paths patterns expand past 1,000 patterns or 4 MiB, so their braces match no files", 2)]
    assert _findings(workspace, "rule-glob-invalid", text) == expected


def test_glob_unmatched_silent_outside_git(workspace: Workspace) -> None:
    assert _findings(workspace, "rule-glob-unmatched", '---\npaths: ["lib/**"]\n---\n\nNo repo.\n') == []


def test_glob_unmatched_skips_negated(workspace: Workspace) -> None:
    _in_git(workspace, "src/app.ts")
    assert _findings(workspace, "rule-glob-unmatched", '---\npaths: ["src/**", "!lib/**"]\n---\n\nNegated.\n') == []


def test_glob_rules_skip_user_layer(workspace: Workspace) -> None:
    _in_git(workspace, "src/app.ts")
    text = '---\npaths: ["photos [2024/**", "lib/**"]\n---\n\nMine.\n'
    assert _findings(workspace, "rule-glob-invalid", text, in_home=True) == []
    assert _run(workspace, "rule-glob-unmatched") == []


def test_glob_unmatched_matches_dotfiles(workspace: Workspace) -> None:
    _in_git(workspace, ".github/workflows/ci.yml")
    assert _findings(workspace, "rule-glob-unmatched", '---\npaths: ["**/*.yml"]\n---\n\nWorkflows.\n') == []


def test_glob_unmatched_silent_for_ignored_folder(workspace: Workspace) -> None:
    _in_git(workspace, ".gitignore")
    repo = workspace.rig()
    write(repo / ".gitignore", "reference/\n")
    write(repo / "reference" / "cifp" / "FAACIFP18", "data\n")
    assert _findings(workspace, "rule-glob-unmatched", '---\npaths: ["reference/cifp/**"]\n---\n\nParser.\n') == []


def test_glob_unmatched_fires_under_tracked_folder(workspace: Workspace) -> None:
    _in_git(workspace, "src/app.ts")
    expected = [('the pattern "src/*.nope" matches no file in the repository, so the rule never loads', 2)]
    assert _findings(workspace, "rule-glob-unmatched", '---\npaths: ["src/*.nope"]\n---\n\nNothing.\n') == expected


def test_glob_unmatched_silent_for_nested_repo(workspace: Workspace) -> None:
    _in_git(workspace, "src/app.ts")
    nested = workspace.rig() / "nested"
    write(nested / "src" / "a.c", "int a;\n")
    git_add(nested, ["src/a.c"])
    assert _findings(workspace, "rule-glob-unmatched", '---\npaths: ["nested/**/*.c"]\n---\n\nNested.\n') == []


def test_glob_unmatched_silent_for_deep_ignored_folder(workspace: Workspace) -> None:
    _in_git(workspace, ".gitignore", "src/app.ts")
    repo = workspace.rig()
    write(repo / ".gitignore", "src/generated/\n")
    write(repo / "src" / "generated" / "x.ts", "export {};\n")
    assert _findings(workspace, "rule-glob-unmatched", '---\npaths: ["src/**/generated/*.ts"]\n---\n\nGenerated.\n') == []


def test_glob_invalid_counts_negated_in_budget(workspace: Workspace) -> None:
    text = '---\npaths: ["src/{1..600}.ts", "!lib/{1..600}.ts"]\n---\n\nToo many.\n'
    expected = [("the paths patterns expand past 1,000 patterns or 4 MiB, so their braces match no files", 2)]
    assert _findings(workspace, "rule-glob-invalid", text) == expected


def test_glob_invalid_reports_negated_bracket(workspace: Workspace) -> None:
    expected = [('the pattern "!photos [2024/**" has a [ that starts no bracket expression, so it matches nothing', 2)]
    assert _findings(workspace, "rule-glob-invalid", '---\npaths: ["src/**", "!photos [2024/**"]\n---\n\nPhotos.\n') == expected


def test_frontmatter_invalid_silent_when_not_loaded(workspace: Workspace) -> None:
    text = "---\n- src/**\n---\n\n" + "filler line\n" * (MAX_BYTES // 12 + 1)
    assert _findings(workspace, "rule-frontmatter-invalid", text) == []
