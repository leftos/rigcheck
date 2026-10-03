"""The variables Claude Code 2.1.288 expands to the empty string in an MCP server's fields.

Claude Code blanks one set of names in every server, stdio included, and a wider set toward a
remote server's ``url`` and ``headers``. See ``docs/research/mcp-credential-blanking.md`` for the
probe this encodes.
"""

import re

_PLAIN_BARE: frozenset[str] = frozenset(
    {
        "AGENT_PROXY_AUTH_TOKEN",
        "CLAUDE_BG_AUTH_SNAPSHOT_PATH",
        "CLAUDE_BG_AUTO_MEMORY_OFF",
        "CLAUDE_BG_BACKEND",
        "CLAUDE_BG_CLAIM_AUTH",
        "CLAUDE_BG_DISPATCHER_RATE_LIMIT_TIER",
        "CLAUDE_BG_DISPATCHER_SUBSCRIPTION_TYPE",
        "CLAUDE_BG_ISOLATION",
        "CLAUDE_BG_MEMORY_TOGGLED_OFF",
        "CLAUDE_BG_POST_CLEAR_RESPAWN",
        "CLAUDE_BG_PTY_AUTH",
        "CLAUDE_BG_RV_AUTH",
        "CLAUDE_BG_SESSION_PERMISSION_RULES",
        "CLAUDE_BG_SOCKET_TOKENS_PATH",
        "CLAUDE_BG_SOURCE",
        "CLAUDE_BG_WORKSPACE_TRUSTED",
        "CLAUDE_BRIDGE_OAUTH_TOKEN",
        "CLAUDE_CODE_API_KEY_FILE_DESCRIPTOR",
        "CLAUDE_CODE_ARTIFACTS_API_TOKEN",
        "CLAUDE_CODE_BRIDGE_CHILD_ARTIFACT",
        "CLAUDE_CODE_BRIDGE_CHILD_AUTO_DEFAULT",
        "CLAUDE_CODE_BRIDGE_CHILD_MACHINE_SETTINGS",
        "CLAUDE_CODE_CONFIG_PROBE",
        "CLAUDE_CODE_GATEWAY_TOKEN_FILE_DESCRIPTOR",
        "CLAUDE_CODE_HFI_BEARER_TOKEN",
        "CLAUDE_CODE_HOST_PROMPT_SUPERSEDES_RECORD",
        "CLAUDE_CODE_MCP_SERVE_AUTH_TOKEN",
        "CLAUDE_CODE_MCP_SERVE_SETTINGS",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR",
        "CLAUDE_CODE_PLUGIN_ATTRIBUTION",
        "CLAUDE_CODE_RATE_LIMIT_TIER",
        "CLAUDE_CODE_RELAUNCH_HOME_TRUST",
        "CLAUDE_CODE_RESUME_INTERRUPTED_TURN",
        "CLAUDE_CODE_RESUME_INTERRUPTED_TURN_MAX_AGE_MS",
        "CLAUDE_CODE_RESUME_PROMPT",
        "CLAUDE_CODE_RESUME_REASON",
        "CLAUDE_CODE_RESUME_SOURCE_ALIVE",
        "CLAUDE_CODE_SESSION_KIND",
        "CLAUDE_CODE_SESSION_NAME",
        "CLAUDE_CODE_SKILL_ATTRIBUTION",
        "CLAUDE_CODE_SLACK_TAG_TOKEN",
        "CLAUDE_CODE_SUBSCRIPTION_TYPE",
        "CLAUDE_CODE_WEBSOCKET_AUTH_FILE_DESCRIPTOR",
        "CLAUDE_TRUSTED_DEVICE_TOKEN",
    }
)

_PLAIN_INPUT: frozenset[str] = frozenset(
    {
        "CLAUDE_CODE_HOST_CREDS_FILE",
        "CLAUDE_CODE_MESSAGING_TOKEN",
        "CLAUDE_CODE_OAUTH_REFRESH_TOKEN",
        "CLAUDE_SESSION_INGRESS_TOKEN_FILE",
        "ENVIRONMENT_SERVICE_KEY",
        "MCP_CLIENT_SECRET",
        "MCP_XAA_IDP_CLIENT_SECRET",
        "SELF_HOSTED_RUNNER_ENVIRONMENT_SECRET",
        "SELF_HOSTED_RUNNER_POOL_SECRET",
    }
)

_REMOTE_INPUT: frozenset[str] = frozenset(
    {
        "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
        "ACTIONS_ID_TOKEN_REQUEST_URL",
        "ACTIONS_RUNTIME_TOKEN",
        "ACTIONS_RUNTIME_URL",
        "ALL_INPUTS",
        "ALL_PROXY",
        "ANACONDA_API_TOKEN",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_AWS_API_KEY",
        "ANTHROPIC_CUSTOM_HEADERS",
        "ANTHROPIC_FOUNDRY_API_KEY",
        "ANTHROPIC_FOUNDRY_AUTH_TOKEN",
        "ANTHROPIC_IDENTITY_TOKEN",
        "ANTHROPIC_IDENTITY_TOKEN_FILE",
        "ARTIFACTS_CREDENTIALPROVIDER_ACCESSTOKEN",
        "ARTIFACTS_CREDENTIALPROVIDER_EXTERNAL_FEED_ENDPOINTS",
        "AWS_BEARER_TOKEN_BEDROCK",
        "AWS_CONTAINER_AUTHORIZATION_TOKEN",
        "AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE",
        "AWS_CONTAINER_CREDENTIALS_FULL_URI",
        "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_WEB_IDENTITY_TOKEN_FILE",
        "AZURE_AUTH_LOCATION",
        "AZURE_CLIENT_CERTIFICATE_PASSWORD",
        "AZURE_CLIENT_CERTIFICATE_PATH",
        "AZURE_CLIENT_SECRET",
        "AZURE_FEDERATED_TOKEN_FILE",
        "AZURE_PASSWORD",
        "BINSTAR_API_TOKEN",
        "CARGO_REGISTRY_TOKEN",
        "CI_DEPLOY_USER",
        "CI_REGISTRY_USER",
        "CLAUDE_CODE_ARTIFACTS_API_TOKEN",
        "CLAUDE_CODE_CLIENT_CERT",
        "CLAUDE_CODE_CLIENT_KEY",
        "CLAUDE_CODE_CLIENT_KEY_PASSPHRASE",
        "CLAUDE_CODE_MEMORY_API_TOKEN",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "CLAUDE_CODE_SLACK_TAG_TOKEN",
        "CLOUDSDK_AUTH_ACCESS_TOKEN",
        "CLOUDSDK_AUTH_ACCESS_TOKEN_FILE",
        "CLOUDSDK_AUTH_AUTHORIZATION_TOKEN_FILE",
        "CODEARTIFACT_AUTH_TOKEN",
        "COMPOSER_AUTH",
        "CONAN_LOGIN_USERNAME",
        "CONAN_PASSWORD",
        "CONSUL_HTTP_AUTH",
        "CONSUL_HTTP_TOKEN",
        "DEFAULT_WORKFLOW_TOKEN",
        "DISCORD_WEBHOOK",
        "DISCORD_WEBHOOK_URL",
        "FASTLANE_SESSION",
        "FLIT_PASSWORD",
        "FLIT_USERNAME",
        "GEM_HOST_API_KEY",
        "GOAUTH",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "GOOGLE_GHA_CREDS_PATH",
        "GOOGLE_OAUTH_ACCESS_TOKEN",
        "GOPROXY",
        "HATCH_INDEX_AUTH",
        "HATCH_INDEX_USER",
        "HTTPS_PROXY",
        "HTTP_PROXY",
        "IDENTITY_HEADER",
        "JF_USER",
        "MATCH_GIT_BASIC_AUTHORIZATION",
        "MATURIN_PASSWORD",
        "MATURIN_PYPI_TOKEN",
        "MATURIN_USERNAME",
        "MSI_SECRET",
        "MS_TEAMS_WEBHOOK_URI",
        "NODE_AUTH_TOKEN",
        "NOMAD_HTTP_AUTH",
        "NOMAD_TOKEN",
        "NPM_TOKEN",
        "NUGET_AUTH_TOKEN",
        "OVERRIDE_GITHUB_TOKEN",
        "PIP_EXTRA_INDEX_URL",
        "PIP_INDEX_URL",
        "PYPI_API_TOKEN",
        "PYPI_TOKEN",
        "SLACK_WEBHOOK",
        "SLACK_WEBHOOK_URL",
        "SONARQUBE_SCANNER_PARAMS",
        "SONAR_SCANNER_JSON_PARAMS",
        "SONAR_TOKEN",
        "SSH_SIGNING_KEY",
        "TEAMS_WEBHOOK_URL",
        "TWINE_PASSWORD",
        "TWINE_USERNAME",
        "UV_DEFAULT_INDEX",
        "UV_EXTRA_INDEX_URL",
        "UV_INDEX",
        "UV_INDEX_URL",
        "UV_PUBLISH_PASSWORD",
        "UV_PUBLISH_TOKEN",
        "UV_PUBLISH_USERNAME",
        "VAULT_AUTH_TOKEN",
        "VAULT_ROLE_ID",
        "VAULT_SECRET_ID",
        "VAULT_TOKEN",
        "VSS_NUGET_ACCESSTOKEN",
        "VSS_NUGET_EXTERNAL_FEED_ENDPOINTS",
    }
)

_TN = (
    r"(?:(?:^|_|(?<=[0-9]))(?:TOKEN|SECRET|PASSWORD|PASSWD|PASSPHRASE|KEY|AUTH|COOKIE|PAT|DSN|WEBHOOK|CREDENTIALS?|CREDS|APIKEY|"
    r"ACCESSKEY|SECRETKEY|ACCOUNTKEY|PRIVATEKEY|AUTHKEY|SSHKEY|SIGNINGKEY|MASTERKEY|DEPLOYKEY|ENCRYPTIONKEY|PGPASSWORD|SSHPASS|"
    r"(?:KEY|SECRET|PASSWORD|CREDENTIAL)S)"
    r"|(?:_|(?<=[0-9]))(?:PWD|PASS|JWT)"
    r"|(?:TOKEN|SECRET|PASSWORD|PASSWD|PASSPHRASE))(?=\Z|[_0-9])"
)

_CONN = r"CONN(?:ECT(?:ION)?)?_?STR(?:ING)?S?(?=\Z|[_0-9])"

_PLAIN_PATTERN = re.compile(
    r"OTEL_.*|CLAUDE_CODE_OTEL_DIAG_STDERR|CLAUDE_CODE_ARTIFACT.*_BASE_URL|CLAUDE_CODE_MEMORY_API_(?:BASE_URL|TOKEN)", re.ASCII
)

_GIT_CONFIG = re.compile(r"GIT_CONFIG_(?:PARAMETERS|(?:KEY|VALUE)_[0-9]+)", re.ASCII)

_CARGO_REGISTRY = re.compile(r"CARGO_REGISTRIES_[A-Z0-9_]+_TOKEN", re.ASCII)

_PACKAGE_CREDENTIAL = re.compile(
    r"(?=(?:INPUT_|ORG_GRADLE_PROJECT_|POETRY_PYPI_TOKEN_|POETRY_HTTP_BASIC_|CARGO_REGISTRIES_|CONAN_LOGIN_USERNAME_|CONAN_PASSWORD_))"
    r"(?:(?:INPUT_)?(?:POETRY_HTTP_BASIC_|CONAN_LOGIN_USERNAME_)|.*USER(?:_?NAME)?_?[0-9]*\Z|.*?" + _TN + r"|.*?" + _CONN + r")",
    re.ASCII,
)

_BUNDLER_HOST = re.compile(
    r"(?:INPUT_)?BUNDLE_(?!(?:BUILD|LOCAL|MIRROR|PATH|WITH|WITHOUT|CACHE|DISABLE|IGNORE|ONLY)__"
    r"(?!(?:[A-Za-z0-9]+(?:___[A-Za-z0-9]+)*__)+[A-Za-z]{2,}\Z))\w*__",
    re.ASCII,
)


def plain_blanked(name: str) -> bool:
    """Return whether Claude Code expands a reference to ``name`` to the empty string in every MCP server.

    Args:
        name: The variable name as written, in any case, with or without a leading ``INPUT_``.

    Returns:
        True when Claude Code reads the variable as empty in a stdio server's ``command``, ``args``
        or ``env``, and toward a remote server's ``url`` and ``headers`` as well.
    """
    upper = name.upper()
    bare = upper.removeprefix("INPUT_")
    return upper in _PLAIN_BARE or bare in _PLAIN_INPUT or bool(_PLAIN_PATTERN.fullmatch(bare))


def remote_blanked(name: str) -> bool:
    """Return whether Claude Code expands a reference to ``name`` to the empty string toward a remote server.

    Args:
        name: The variable name as written, in any case, with or without a leading ``INPUT_``.

    Returns:
        True when Claude Code reads the variable as empty in a server's ``url`` or ``headers``.
    """
    if plain_blanked(name):
        return True
    bare = name.upper().removeprefix("INPUT_")
    return bare in _REMOTE_INPUT or bool(
        _GIT_CONFIG.fullmatch(bare)
        or _CARGO_REGISTRY.fullmatch(bare)
        or _PACKAGE_CREDENTIAL.match(bare.replace("-", "_"))
        or _BUNDLER_HOST.match(bare)
    )
