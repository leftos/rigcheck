from pathlib import Path

import pytest

from rigcheck.parse.markdown import Reference, find_references
from rigcheck.rules.references import (
    invocations,
    justfile_names,
    makefile_names,
    path_bases,
    path_candidate,
    reference_path,
)
from support import Workspace, git_add, run_json, write


@pytest.mark.parametrize(
    ("source", "raw", "expected"),
    [
        ("span", "docs/architecture.md", "docs/architecture.md"),
        ("span", "./scripts/run.ps1", "./scripts/run.ps1"),
        ("span", "src/api/", "src/api/"),
        ("span", "~/.claude/skills/x/SKILL.md", "~/.claude/skills/x/SKILL.md"),
        ("link", "docs/gone.md", "docs/gone.md"),
        ("link", "./gone.md#setup", "./gone.md"),
        ("link", "docs/a.md?raw=1", "docs/a.md"),
        ("link", "docs/my%20file.md", "docs/my file.md"),
        ("span", "tools\\setup.ps1", "tools/setup.ps1"),
        ("span", "docs/a.md#setup", "docs/a.md"),
        ("span", "../sibling.md", "../sibling.md"),
        ("span", "http://localhost:5130", None),
        ("link", "https://example.com/a/b", None),
        ("link", "#section", None),
        ("link", "gone.md", None),
        ("link", "mailto:a@b.com/x", None),
        ("span", ".env", None),
        ("span", "net10.0", None),
        ("span", "Yaat.VStrips.Web", None),
        ("span", "launchSettings.json", None),
        ("span", "src/*.py", None),
        ("span", "src/?.py", None),
        ("span", "src/[ab].py", None),
        ("span", "docs/{a,b}.md", None),
        ("span", "<name>/SKILL.md", None),
        ("span", "$HOME/x", None),
        ("span", "%APPDATA%/x", None),
        ("span", "path/.../file", None),
        ("span", "dotnet build src/Yaat.sln", None),
        ("span", "/agent/repos/yaat", None),
        ("span", "D:/dev/x", None),
        ("span", "D:\\dev\\x", None),
        ("span", "#tag/x", None),
        ("span", "", None),
        ("span", "\N{HORIZONTAL ELLIPSIS}Stars.Tracks/Track.cs", None),
        ("span", "src/\N{HORIZONTAL ELLIPSIS}/x.cs", None),
        ("span", "A=docs/present.md", "docs/present.md"),
        ("span", "CLAUDE_ROSLYN_LSP_SOLUTION=.claude/x.slnx", ".claude/x.slnx"),
        ("span", "A=net10.0", None),
        ("span", "1A=docs/x.md", "1A=docs/x.md"),
        ("span", "github.com/leftos/godot-mcp", None),
        ("span", "GitHub.COM/a/b", None),
        ("link", "docs.example.io/a", None),
        ("span", "docs.example/a", "docs.example/a"),
        ("span", "bin/", None),
        ("span", "bin/Debug/app.dll", None),
        ("span", "./node_modules/x/index.js", None),
        ("span", ".venv/lib/x.py", None),
        ("span", "src/bin/x.cs", "src/bin/x.cs"),
        ("span", "src/foo.py:42", "src/foo.py"),
        ("span", "src/foo.py:42:7", "src/foo.py"),
        ("span", "tests/test_a.py::test_b", "tests/test_a.py"),
        ("span", "tests/test_a.py::Class::test_b[x]", "tests/test_a.py"),
        ("link", "src/foo.py:42", "src/foo.py"),
    ],
)
def test_path_candidate(source: str, raw: str, expected: str | None) -> None:
    assert path_candidate(Reference(line=1, raw=raw, source=source, lang="")) == expected


def test_path_candidate_ignores_fences() -> None:
    assert path_candidate(Reference(line=1, raw="docs/a.md", source="fence", lang="")) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("deploy.sh", "deploy.sh"),
        ("notes.org", "notes.org"),
        ("example.com", "example.com"),
        ("github.com/leftos/rigcheck", None),
        ("docs.example.io/a", None),
        ("tel:5550100", None),
        ("TEL:5550100", None),
        ("sms:5550100", None),
        ("mailto:a@b.com", None),
        ("vscode://file/x", None),
        ("gone.md:12", "gone.md"),
        ("Makefile:12", "Makefile"),
        ("Dockerfile:3:1", "Dockerfile"),
        ("notes:x", None),
        ("mem0:status", None),
        ("npm:lodash", None),
        ("a.md:12:3", "a.md"),
        ("C:/x/y.md", "C:/x/y.md"),
    ],
)
def test_reference_path(raw: str, expected: str | None) -> None:
    assert reference_path(Reference(line=1, raw=raw, source="link", lang="")) == expected


def test_backslash_link_from_markdown_is_normalised() -> None:
    [reference] = find_references("[setup](tools\\\\setup.ps1)\n")
    assert path_candidate(reference) == "tools/setup.ps1"


def _path_messages(capsys: pytest.CaptureFixture[str], rig: Path, home: Path) -> list[str]:
    _, report = run_json(capsys, rig, home)
    return [finding["message"] for finding in report["findings"] if finding["rule"] == "reference-path-missing"]


def test_path_rule_flags_only_when_the_parent_folder_exists(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    rig = workspace.rig()
    write(rig / "docs" / "other.md", "x\n")
    write(workspace.home / ".claude" / "keep.md", "x\n")
    write(
        rig / "CLAUDE.md",
        "`docs/gone.md` `nowhere/deeper/x.md` `gone-dir/` `./gone.md` `~/.claude/gone.md` `~/.nowhere/x.md`\n",
    )
    assert sorted(_path_messages(capsys, rig, workspace.home)) == [
        "./gone.md does not exist (looked beside CLAUDE.md and at the repo root)",
        "docs/gone.md does not exist (looked beside CLAUDE.md and at the repo root)",
        "gone-dir/ does not exist (looked beside CLAUDE.md and at the repo root)",
        "~/.claude/gone.md does not exist in the home folder",
    ]


def test_path_rule_checks_only_home_paths_in_user_files(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    rig = workspace.rig()
    write(rig / "CLAUDE.md", "# Project\n")
    write(rig / "docs" / "other.md", "x\n")
    write(workspace.home / ".claude" / "CLAUDE.md", "`docs/gone.md` `./gone.md` `~/.claude/gone.md`\n")
    assert _path_messages(capsys, rig, workspace.home) == ["~/.claude/gone.md does not exist in the home folder"]


def test_path_rule_flags_a_parent_path_that_leaves_the_repo(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    rig = workspace.rig()
    write(rig.parent / "sib" / "docs" / "other.md", "x\n")
    write(rig / "CLAUDE.md", "`../sib/docs/x.md`\n")
    assert _path_messages(capsys, rig, workspace.home) == ["../sib/docs/x.md does not exist (looked beside CLAUDE.md, outside the repo)"]


def test_path_rule_accepts_a_parent_path_that_exists_outside_the_repo(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    rig = workspace.rig()
    write(rig.parent / "sib" / "docs" / "x.md", "x\n")
    write(rig / "CLAUDE.md", "`../sib/docs/x.md`\n")
    assert _path_messages(capsys, rig, workspace.home) == []


def test_path_rule_skips_a_parent_path_whose_folder_is_gone(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    rig = workspace.rig()
    write(rig / "CLAUDE.md", "`../sib/docs/x.md`\n")
    assert _path_messages(capsys, rig, workspace.home) == []


def test_path_rule_keeps_the_repo_message_for_a_parent_path_inside_the_repo(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    rig = workspace.rig()
    write(rig / "CLAUDE.md", "# Project\n")
    write(rig / "docs" / "other.md", "x\n")
    write(rig / "sub" / "CLAUDE.md", "`../docs/a.md`\n")
    git_add(rig, ["CLAUDE.md", "sub/CLAUDE.md"])
    assert _path_messages(capsys, rig, workspace.home) == ["../docs/a.md does not exist (looked beside CLAUDE.md and at the repo root)"]


def test_path_bases_skip_what_escapes_the_repo(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    assert path_bases("../yaat-server/x.md", root, root) == []
    assert path_bases("../docs/x.md", root / "sub", root) == [root / "docs" / "x.md"]
    assert path_bases("docs/x.md", root / "sub", root) == [root / "sub" / "docs" / "x.md", root / "docs" / "x.md"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("npm run nope", [("npm run", "nope")]),
        ("npm run-script nope", [("npm run-script", "nope")]),
        ("pnpm run nope --silent", [("pnpm run", "nope")]),
        ("yarn run nope", []),
        ("bun run nope", []),
        ("  just nope arg", [("just", "nope")]),
        ("make nope", [("make", "nope")]),
        ("make -j4 CONFIG=x all", []),
        ("make CONFIG=x all", [("make", "all")]),
        ("make -j 4 build", []),
        ("npm run --silent build", []),
        ("make -Csub all", []),
        ("make all --directory=sub", []),
        ("just build --working-directory sub", []),
        ("just build -d sub", []),
        ("make all -d", [("make", "all")]),
        ("make all -fother.mk", []),
        ("echo 'a | make b'", []),
        ('echo "x; npm run y"', []),
        ("echo 'a' | make b", [("make", "b")]),
        ("'make' b", []),
        ("git pull && npm run nope", [("npm run", "nope")]),
        ("npm run a; just b || make c | tee log", [("npm run", "a"), ("just", "b"), ("make", "c")]),
        ("npm test", []),
        ("npm start", []),
        ("npx tsc", []),
        ("pnpm dlx x", []),
        ("pnpm build", []),
        ("yarn build", []),
        ("npm run build -w pkg", []),
        ("npm run build --workspace=pkg", []),
        ("pnpm --filter web run build", []),
        ("npm --prefix web run build", []),
        ("cd web && npm run other", []),
        ("make -C sub all", []),
        ("make -f other.mk all", []),
        ("just --justfile x.just build", []),
        ("make", []),
        ("make CONFIG=x", []),
        ("just --list", []),
        ("npm run", []),
        ("sudo make install", []),
        ("# make nope", []),
    ],
)
def test_invocations(raw: str, expected: list[tuple[str, str]]) -> None:
    assert invocations(raw) == expected


@pytest.mark.parametrize("package_json", [None, "{not json", '{"scripts": ["build"]}'])
def test_script_rule_is_silent_without_a_usable_manifest(package_json: str | None, workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    rig = workspace.rig()
    write(rig / "CLAUDE.md", "Run `npm run nope`, `just nope` and `make nope`.\n")
    if package_json is not None:
        write(rig / "package.json", package_json)
    _, report = run_json(capsys, rig, workspace.home)
    rules = [finding["rule"] for finding in report["findings"]]
    assert "reference-script-missing" not in rules
    assert "internal-error" not in rules


def test_script_rule_uses_the_nearest_manifest(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    rig = workspace.rig()
    write(rig / "package.json", '{"scripts": {"root": "echo"}}')
    write(rig / "web" / "package.json", '{"scripts": {"web": "echo"}}')
    write(rig / "CLAUDE.md", "Run `npm run root`.\n")
    write(rig / "web" / "CLAUDE.md", "Run `npm run web` or `npm run root`.\n")
    git_add(rig, ["CLAUDE.md", "web/CLAUDE.md"])
    _, report = run_json(capsys, rig, workspace.home)
    messages = [finding["message"] for finding in report["findings"] if finding["rule"] == "reference-script-missing"]
    assert messages == ["npm run root: no such script in web/package.json"]


@pytest.mark.parametrize(
    "case",
    [
        ("justfile", "test:\n    echo\n", "`just nope`\n", True),
        ("justfile", "import 'more.just'\ntest:\n    echo\n", "`just nope`\n", False),
        ("justfile", "import? 'more.just'\n", "`just nope`\n", False),
        ("justfile", "mod tools\n", "`just nope`\n", False),
        ("justfile", "mod? tools 'x.just'\n", "`just nope`\n", False),
        ("Makefile", "lint:\n\techo\n", "`make nope`\n", True),
        ("Makefile", "include rules.mk\nlint:\n", "`make nope`\n", False),
        ("Makefile", "-include local.mk\n", "`make nope`\n", False),
        ("Makefile", "sinclude local.mk\n", "`make nope`\n", False),
        ("Makefile", "lint:\n", "```bash\nmake nope\n```\n", True),
        ("Makefile", "lint:\n", "```\nmake nope\n```\n", True),
        ("Makefile", "lint:\n", "```PowerShell\nmake nope\n```\n", True),
        ("Makefile", "lint:\n", "```text\nmake nope\n```\n", False),
        ("Makefile", "lint:\n", "```python\nmake nope\n```\n", False),
        ("Makefile", "lint:\n", "    make nope\n", True),
    ],
)
def test_script_rule_includes_and_fence_languages(case: tuple[str, str, str, bool], workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    manifest, content, claude, flagged = case
    rig = workspace.rig()
    write(rig / manifest, content)
    write(rig / "CLAUDE.md", claude)
    _, report = run_json(capsys, rig, workspace.home)
    rules = [finding["rule"] for finding in report["findings"]]
    assert ("reference-script-missing" in rules) is flagged


def test_justfile_names() -> None:
    text = (
        "set shell := ['bash']\nversion := '1'\nexport X := '2'\n\n"
        "build:\n    echo\n@test *args:\n    echo\nlint target: build\nalias b := build\n  indented:\n"
    )
    assert justfile_names(text) == {"build", "test", "lint", "b"}


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("build target='x':", {"build"}),
        ("test *args:", {"test"}),
        ('run +flags="a b":', {"run"}),
        ("deploy env=prod $TOKEN: build", {"deploy"}),
        ("colon arg='a:b':", {"colon"}),
        ("x := y", set()),
        ("x:=y", set()),
        ("export X := 'a'", set()),
    ],
)
def test_justfile_recipe_parameters(line: str, expected: set[str]) -> None:
    assert justfile_names(line + "\n") == expected


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("VAR ::= x", set()),
        ("VAR := x", set()),
        ("VAR ?= x", set()),
        ("VAR += x", set()),
        ("VAR != x", set()),
        ("URL ?= http://x", set()),
        ("all: CFLAGS += -O2", {"all"}),
        ("clean:: tidy", {"clean"}),
    ],
)
def test_makefile_assignments_are_not_targets(line: str, expected: set[str]) -> None:
    assert makefile_names(line + "\n") == expected


def test_makefile_names() -> None:
    text = "CC := gcc\nX = y\n.PHONY: all lint\nall lint: deps\n\techo\nclean::\n%.o: %.c\n$(OUT): x\nbuild/out.txt:\n\tx:\n"
    assert makefile_names(text) == {"all", "lint", "clean", "build/out.txt"}
