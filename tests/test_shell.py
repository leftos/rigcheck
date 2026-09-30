"""The shell text helpers: segments, words, comments, command and script words, and unquoted placeholders."""

import pytest

from rigcheck.parse.shell import (
    anchored,
    command_word,
    cwd_relative,
    program_name,
    script_word,
    segments,
    uncommented,
    unquoted_placeholders,
    words,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("a && b", ["a ", " b"]),
        ("a || b; c | d", ["a ", " b", " c ", " d"]),
        ("echo 'a && b'; c", ["echo 'a && b'", " c"]),
        ('echo "x|y"', ['echo "x|y"']),
        ("a;;b", ["a", "", "b"]),
        ("", [""]),
    ],
)
def test_segments(raw: str, expected: list[str]) -> None:
    assert segments(raw) == expected


@pytest.mark.parametrize(
    ("segment", "expected"),
    [
        ('bash "$CLAUDE_PROJECT_DIR/x.sh" -v', ["bash", "$CLAUDE_PROJECT_DIR/x.sh", "-v"]),
        (r"pwsh -File C:\hooks\gate.ps1", ["pwsh", "-File", r"C:\hooks\gate.ps1"]),
        (r'"C:\Program Files\tool.exe" run', [r"C:\Program Files\tool.exe", "run"]),
        ("echo 'unbalanced", ["echo", "unbalanced"]),
        ("", []),
    ],
)
def test_words_strip_quotes_and_keep_backslashes(segment: str, expected: list[str]) -> None:
    assert words(segment) == expected


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("run.sh # note", "run.sh "),
        ("# all comment", ""),
        ("echo a#b", "echo a#b"),
        ("echo '# not a comment' x", "echo '# not a comment' x"),
        ('echo "#x" # cut', 'echo "#x" '),
    ],
)
def test_uncommented(line: str, expected: str) -> None:
    assert uncommented(line) == expected


@pytest.mark.parametrize(
    ("word", "expected"),
    [
        ("$CLAUDE_PROJECT_DIR/x.sh", True),
        ("~/bin/x", True),
        ("/usr/bin/env", True),
        ("%APPDATA%\\x", True),
        ("\\\\server\\share\\x", True),
        (r"C:\hooks\gate.ps1", True),
        ("https://example.com/x", True),
        ("./x.sh", False),
        ("scripts/x.sh", False),
        ("node", False),
    ],
)
def test_anchored(word: str, expected: bool) -> None:
    assert anchored(word) is expected


@pytest.mark.parametrize(
    ("word", "first", "expected"),
    [
        ("./x.sh", False, True),
        ("..\\x.ps1", False, True),
        ("scripts/x.sh", True, True),
        ("scripts\\x.ps1", True, True),
        ("scripts/x.sh", False, False),
        ("x.sh", True, False),
        ("$CLAUDE_PROJECT_DIR/x.sh", True, False),
        (r"C:\hooks\gate.ps1", True, False),
    ],
)
def test_cwd_relative(word: str, first: bool, expected: bool) -> None:
    assert cwd_relative(word, first) is expected


@pytest.mark.parametrize(
    ("segment", "expected"),
    [
        ("FOO=1 BAR=2 ./run.sh arg", "./run.sh"),
        ("  git status", "git"),
        ("FOO=1", None),
        ("", None),
    ],
)
def test_command_word(segment: str, expected: str | None) -> None:
    assert command_word(segment) == expected


@pytest.mark.parametrize(
    ("word", "expected"),
    [("/usr/bin/python3", "python3"), (r"C:\Tools\PWSH.EXE", "pwsh"), ("node", "node")],
)
def test_program_name(word: str, expected: str) -> None:
    assert program_name(word) == expected


@pytest.mark.parametrize(
    ("segment", "expected"),
    [
        ("./gate.sh --strict", ("./gate.sh", True)),
        ("FOO=1 $CLAUDE_PROJECT_DIR/gate.sh", ("$CLAUDE_PROJECT_DIR/gate.sh", True)),
        ("bash -e scripts/gate.sh", ("scripts/gate.sh", False)),
        ("/usr/bin/python3 -u hooks/check.py", ("hooks/check.py", False)),
        (r"pwsh -NoProfile -ExecutionPolicy Bypass -File C:\hooks\gate.ps1", (r"C:\hooks\gate.ps1", False)),
        ("powershell.exe -f ./gate.ps1", ("./gate.ps1", False)),
        ("bun run ./x.ts", ("./x.ts", False)),
        ("uv run --quiet tools/check.py", ("tools/check.py", False)),
        ("uv run python tools/check.py", ("tools/check.py", False)),
        ("uvx ruff", ("ruff", False)),
        ("bash -c 'echo hi'", None),
        ("node -e 'console.log(1)'", None),
        ("pwsh -Command Get-Date", None),
        ("bash", None),
        ("uv sync", ("uv", True)),
        ("", None),
    ],
)
def test_script_word(segment: str, expected: tuple[str, bool] | None) -> None:
    assert script_word(segment) == expected


@pytest.mark.parametrize(
    ("segment", "expected"),
    [
        ('node -r ts-node/register "$CLAUDE_PROJECT_DIR/h.ts"', ("$CLAUDE_PROJECT_DIR/h.ts", False)),
        ("node --import tsx/esm hook.ts", ("hook.ts", False)),
        ("node --import=tsx/esm hook.ts", ("hook.ts", False)),
        ("bun --env-file .env run ./x.ts", ("./x.ts", False)),
        ("python -m pkg.hook", None),
        ("python3 -W ignore -X utf8 hooks/check.py", ("hooks/check.py", False)),
        ("ruby -I lib -r json hooks/check.rb", ("hooks/check.rb", False)),
        ("perl -Ilib hooks/check.pl", ("hooks/check.pl", False)),
        ("perl -M strict hooks/check.pl", ("hooks/check.pl", False)),
        ("bash -euc 'echo hi'", None),
        ("sh -x hooks/run.sh", ("hooks/run.sh", False)),
    ],
)
def test_interpreter_flag_value_is_not_the_script(segment: str, expected: tuple[str, bool] | None) -> None:
    assert script_word(segment) == expected


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("bash $CLAUDE_PROJECT_DIR/x.sh", ["$CLAUDE_PROJECT_DIR"]),
        ("${CLAUDE_PLUGIN_ROOT}/a.sh ${CLAUDE_PROJECT_DIR}", ["${CLAUDE_PLUGIN_ROOT}", "${CLAUDE_PROJECT_DIR}"]),
        ('"$CLAUDE_PROJECT_DIR"/x.sh', []),
        ('"${CLAUDE_PLUGIN_ROOT}/x.sh"', []),
        ("'$CLAUDE_PROJECT_DIR/x.sh'", []),
        ("\\$CLAUDE_PROJECT_DIR/x.sh", []),
        ("$CLAUDE_PROJECT_DIRX/x.sh", []),
        ('echo "a \\" $CLAUDE_PROJECT_DIR"', []),
        ("echo 'it' $CLAUDE_PLUGIN_ROOT", ["$CLAUDE_PLUGIN_ROOT"]),
        ("echo 'open $CLAUDE_PROJECT_DIR", []),
    ],
)
def test_unquoted_placeholders(command: str, expected: list[str]) -> None:
    assert unquoted_placeholders(command) == expected


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ('"$(dirname "$CLAUDE_PROJECT_DIR")/x.sh"', []),
        ('bash "$(cd "${CLAUDE_PLUGIN_ROOT}" && pwd)/x.sh"', []),
        ('"$(dirname $CLAUDE_PROJECT_DIR)/x.sh"', ["$CLAUDE_PROJECT_DIR"]),
        ('echo $(cat "$CLAUDE_PLUGIN_ROOT/v") $CLAUDE_PLUGIN_ROOT', ["$CLAUDE_PLUGIN_ROOT"]),
        ("echo $((1 + (2))) $CLAUDE_PROJECT_DIR", ["$CLAUDE_PROJECT_DIR"]),
    ],
)
def test_placeholder_inside_command_substitution_is_quoted(command: str, expected: list[str]) -> None:
    assert unquoted_placeholders(command) == expected


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ('D=$CLAUDE_PROJECT_DIR bash "$D/x.sh"', []),
        ("export D=${CLAUDE_PLUGIN_ROOT}/x", []),
        ("D=$CLAUDE_PROJECT_DIR; bash $CLAUDE_PROJECT_DIR/x.sh", ["$CLAUDE_PROJECT_DIR"]),
        ("D=$(ls $CLAUDE_PROJECT_DIR)", ["$CLAUDE_PROJECT_DIR"]),
    ],
)
def test_placeholder_in_assignment_is_silent(command: str, expected: list[str]) -> None:
    assert unquoted_placeholders(command) == expected
