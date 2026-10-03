"""The remote-blanked predicate: the fixed name list and each name pattern Claude Code uses toward a remote server."""

import pytest

from rigcheck.rules.mcp_credentials import _REMOTE_BLANKED, remote_blanked

# Blanked and not-blanked examples, grouped by the pattern that decides them, per the probe in
# docs/research/mcp-credential-blanking.md.
MATCHES = [
    # Telemetry endpoints, and Claude Code's own artifact and memory endpoints.
    "OTEL_EXPORTER_OTLP_HEADERS",
    "CLAUDE_CODE_ARTIFACT_VIEWER_BASE_URL",
    # Git's exported configuration parameters, and its exported keys and values.
    "GIT_CONFIG_PARAMETERS",
    "GIT_CONFIG_VALUE_0",
    # Cargo registry tokens.
    "CARGO_REGISTRIES_MY_TOKEN",
    "CARGO_REGISTRIES_A_B_TOKEN",
    # Package-manager prefixes followed by a credential word or a USER suffix.
    "ORG_GRADLE_PROJECT_PASSWORD",
    "CONAN_LOGIN_USERNAME_REMOTE",
    "ORG_GRADLE_PROJECT_SIGNING_KEY_ID",
    "ORG_GRADLE_PROJECT_MYTOKEN",
    # Bundler per-host credentials.
    "BUNDLE_GEMS__EXAMPLE__COM",
    "BUNDLE_MIRROR__RUBYGEMS__ORG",
    # A fixed name from the 130 the probe lists, with no pattern of its own.
    "CLAUDE_CODE_ARTIFACTS_API_TOKEN",
]

NON_MATCHES = [
    "OTELX",
    "GIT_CONFIG_COUNT",
    "GIT_CONFIG_KEY_X",
    "CARGO_REGISTRIES_MY_INDEX",
    "CARGO_REGISTRIES_MY_TOKENS",
    "ORG_GRADLE_PROJECT_VERSION",
    "POETRY_REPOSITORIES_X_URL",
    "BUNDLE_PATH__VENDOR",
    "BUNDLE_JOBS",
]


@pytest.mark.parametrize("name", MATCHES)
def test_remote_blanked_matches(name: str) -> None:
    assert remote_blanked(name)


@pytest.mark.parametrize("name", NON_MATCHES)
def test_remote_blanked_non_matches(name: str) -> None:
    assert not remote_blanked(name)


def test_every_listed_name_is_blanked_in_any_case_and_with_input_prefix() -> None:
    for name in _REMOTE_BLANKED:
        assert remote_blanked(name)
        assert remote_blanked(name.lower())
        assert remote_blanked("INPUT_" + name)
