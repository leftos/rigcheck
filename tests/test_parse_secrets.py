"""Credential literal detection: every token format, the placeholders it skips, and hits that never hold the value.

Every pattern-valid token is built at runtime from pieces, so no committed file holds one.
"""

import dataclasses
import string

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from rigcheck.parse.secrets import SecretHit, classify, find_secrets

MIXED = "a1B2c3D4"
AWS_BODY = "Q3ZJ7K2M" + "P4W6N8R2"

EXAMPLES = [
    ("Anthropic API key", "sk-" + "ant-" + "api03-" + MIXED * 3),
    ("OpenAI API key", "sk-" + MIXED * 5),
    ("OpenAI API key", "sk-" + "proj-" + MIXED * 5),
    ("GitHub token", "gh" + "p_" + MIXED * 5),
    ("GitHub token", "gh" + "s_" + MIXED * 5),
    ("GitHub token", "github" + "_pat_" + MIXED * 7),
    ("Slack token", "xox" + "b-" + "1234567890-" + MIXED),
    ("AWS access key", "AK" + "IA" + AWS_BODY),
    ("Google API key", "AI" + "za" + "Sy" + MIXED * 4 + "_"),
    ("JWT", "ey" + "J" + "hbGciOiJIUzI1" + ".ey" + "J" + "zdWIiOiIxMjM0" + "." + "SflKxwRJSMeK"),
]

KEY_BODY = "MIIE" + "a1B2c3D4/+" * 6 + "=="


def _header(label: str) -> str:
    return "-----" + "BEGIN " + label + "-----"


@pytest.mark.parametrize("label", ["PRIVATE KEY", "RSA PRIVATE KEY", "EC PRIVATE KEY", "OPENSSH PRIVATE KEY", "PGP PRIVATE KEY BLOCK"])
@pytest.mark.parametrize("between", ["\n", "\n\n", "\nVersion: GnuPG v2\n", "\n  "])
def test_private_key_with_body_is_found(label: str, between: str) -> None:
    header = _header(label)
    assert find_secrets("# Keys\n" + header + between + KEY_BODY + "\n") == [SecretHit(line=2, kind="private key", length=len(header))]
    assert classify(header + between + KEY_BODY) == "private key"


@pytest.mark.parametrize(
    "after",
    [
        "",
        "\n",
        "\nnot a key body\n",
        "\n" + KEY_BODY[:39] + "\n",
        "\n\n\n" + KEY_BODY + "\n",
        "\n" + KEY_BODY + " trailing words\n",
    ],
)
def test_private_key_header_alone_is_silent(after: str) -> None:
    assert find_secrets("Never commit a file starting with " + _header("RSA PRIVATE KEY") + after) == []


@pytest.mark.parametrize(("kind", "token"), EXAMPLES)
def test_token_formats_are_found(kind: str, token: str) -> None:
    assert find_secrets(f"key = {token}\n") == [SecretHit(line=1, kind=kind, length=len(token))]


@pytest.mark.parametrize(("kind", "token"), EXAMPLES)
def test_classify_names_the_kind(kind: str, token: str) -> None:
    assert classify(token) == kind
    assert classify("Bearer " + token) == kind


def test_hit_line_counts_from_one() -> None:
    token = "gh" + "p_" + MIXED * 5
    assert find_secrets("# Title\n\nuse " + token + " here\n") == [SecretHit(line=3, kind="GitHub token", length=44)]


def test_hits_are_in_text_order() -> None:
    text = "gh" + "p_" + MIXED * 5 + "\n" + "AK" + "IA" + AWS_BODY + " " + "sk-" + MIXED * 5
    assert [hit.kind for hit in find_secrets(text)] == ["GitHub token", "AWS access key", "OpenAI API key"]


def test_anthropic_key_is_not_also_an_openai_key() -> None:
    token = "sk-" + "ant-" + MIXED * 5
    assert [hit.kind for hit in find_secrets(token)] == ["Anthropic API key"]


NON_EXAMPLES = [
    "${ANTHROPIC_API_KEY}",
    "$OPENAI_API_KEY",
    "<your-key>",
    "sk-ant-...",
    "sk-" + "ant-..." + MIXED * 4,
    "sk-" + "ant-…" + MIXED * 4,
    "AK" + "IA" + "IOSFODNN7" + "EXAMPLE",
    "sk-" + "ant-" + "x" * 30,
    "gh" + "p_" + "0" * 36,
    "gh" + "p_" + "a1" + "XXXXXX" + MIXED * 5,
    "sk-" + "proj-" + "xxxxxx" + MIXED * 5,
    "gh" + "p_" + "abc",
    "AK" + "IA" + AWS_BODY + "Z",
    "AI" + "za" + "Sy" + MIXED * 4,
    "task-" + MIXED * 5,
    "x" + "gh" + "p_" + MIXED * 5,
    "xox" + "b-" + "short",
    "ey" + "J" + "hbGciOiJIUzI1" + ".not-a-jwt",
    "-----BEGIN " + "PUBLIC KEY-----",
]


@pytest.mark.parametrize("text", NON_EXAMPLES)
def test_non_examples_are_silent(text: str) -> None:
    assert find_secrets(f"value: {text}\n") == []
    assert classify(text) is None


@pytest.mark.parametrize("word", ["your", "YOUR", "example", "changeme", "placeholder", "dummy", "Fake", "redacted"])
def test_placeholder_words_are_silent(word: str) -> None:
    assert find_secrets("sk-" + "ant-" + MIXED + word + MIXED * 3) == []
    assert find_secrets("gh" + "p_" + MIXED * 2 + word + MIXED * 3) == []


def test_lowercase_x_run_of_five_still_counts() -> None:
    token = "gh" + "p_" + "a1" + "xxxxx" + MIXED * 5
    assert [hit.kind for hit in find_secrets(token)] == ["GitHub token"]


TOKEN_CHARS = string.ascii_letters + string.digits
URLSAFE = TOKEN_CHARS + "_-"
UPPER = string.ascii_uppercase + string.digits


def _body(alphabet: str, size: int, most: int | None = None) -> st.SearchStrategy[str]:
    return st.text(alphabet=alphabet, min_size=size, max_size=most if most is not None else size + 30)


TOKENS = st.one_of(
    _body(URLSAFE, 20).map(lambda body: "sk-" + "ant-" + body),
    _body(URLSAFE, 32).map(lambda body: "sk-" + "proj-" + body),
    st.tuples(st.sampled_from("pousr"), _body(TOKEN_CHARS, 36)).map(lambda pair: "gh" + pair[0] + "_" + pair[1]),
    _body(TOKEN_CHARS + "_", 50).map(lambda body: "github" + "_pat_" + body),
    st.tuples(st.sampled_from("baprs"), _body(TOKEN_CHARS + "-", 10)).map(lambda pair: "xox" + pair[0] + "-" + pair[1]),
    _body(UPPER, 16, 16).map(lambda body: "AK" + "IA" + body),
    _body(URLSAFE, 35, 35).map(lambda body: "AI" + "za" + body),
    st.tuples(_body(URLSAFE, 10), _body(URLSAFE, 10), _body(URLSAFE, 10)).map(
        lambda parts: "ey" + "J" + parts[0] + ".eyJ" + parts[1] + "." + parts[2]
    ),
)
AROUND = st.text(alphabet=TOKEN_CHARS + " \n.,:=\"'#`", max_size=40)


@settings(deadline=None)
@given(AROUND, TOKENS, AROUND)
def test_hits_never_hold_the_value(before: str, token: str, after: str) -> None:
    hits = find_secrets(before + " " + token + " " + after)
    shown = [repr(getattr(hit, field.name)) for hit in hits for field in dataclasses.fields(hit)]
    for start in range(len(token) - 5):
        chunk = token[start : start + 6]
        assert not any(chunk in text for text in shown)
