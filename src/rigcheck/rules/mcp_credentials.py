"""The variables Claude Code 2.1.288 expands to the empty string in a remote MCP server's ``url`` and ``headers``.

See ``docs/research/mcp-credential-blanking.md`` for the probe this encodes.
"""

import re

_REMOTE_BLANKED: frozenset[str] = frozenset(
    {
        "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
        "ACTIONS_ID_TOKEN_REQUEST_URL",
        "ACTIONS_RUNTIME_TOKEN",
        "ACTIONS_RUNTIME_URL",
        "AGENT_PROXY_AUTH_TOKEN",
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
        "CLAUDE_BG_AUTH_SNAPSHOT_PATH",
        "CLAUDE_BG_CLAIM_AUTH",
        "CLAUDE_BG_PTY_AUTH",
        "CLAUDE_BG_RV_AUTH",
        "CLAUDE_BG_SOCKET_TOKENS_PATH",
        "CLAUDE_BRIDGE_OAUTH_TOKEN",
        "CLAUDE_CODE_API_KEY_FILE_DESCRIPTOR",
        "CLAUDE_CODE_ARTIFACTS_API_TOKEN",
        "CLAUDE_CODE_CLIENT_CERT",
        "CLAUDE_CODE_CLIENT_KEY",
        "CLAUDE_CODE_CLIENT_KEY_PASSPHRASE",
        "CLAUDE_CODE_GATEWAY_TOKEN_FILE_DESCRIPTOR",
        "CLAUDE_CODE_HFI_BEARER_TOKEN",
        "CLAUDE_CODE_HOST_CREDS_FILE",
        "CLAUDE_CODE_MCP_SERVE_AUTH_TOKEN",
        "CLAUDE_CODE_MEMORY_API_TOKEN",
        "CLAUDE_CODE_MESSAGING_TOKEN",
        "CLAUDE_CODE_OAUTH_REFRESH_TOKEN",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR",
        "CLAUDE_CODE_SLACK_TAG_TOKEN",
        "CLAUDE_CODE_WEBSOCKET_AUTH_FILE_DESCRIPTOR",
        "CLAUDE_SESSION_INGRESS_TOKEN_FILE",
        "CLAUDE_TRUSTED_DEVICE_TOKEN",
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
        "ENVIRONMENT_SERVICE_KEY",
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
        "MCP_CLIENT_SECRET",
        "MCP_XAA_IDP_CLIENT_SECRET",
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
        "SELF_HOSTED_RUNNER_ENVIRONMENT_SECRET",
        "SELF_HOSTED_RUNNER_POOL_SECRET",
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

_TELEMETRY = re.compile(r"OTEL_.*|CLAUDE_CODE_OTEL_DIAG_STDERR|CLAUDE_CODE_ARTIFACT.*_BASE_URL|CLAUDE_CODE_MEMORY_API_(?:BASE_URL|TOKEN)", re.ASCII)

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


def remote_blanked(name: str) -> bool:
    """Return whether Claude Code expands a reference to ``name`` to the empty string toward a remote server.

    Args:
        name: The variable name as written, in any case, with or without a leading ``INPUT_``.

    Returns:
        True when Claude Code reads the variable as empty in a server's ``url`` or ``headers``.
    """
    upper = name.upper()
    bare = upper.removeprefix("INPUT_")
    if bare in _REMOTE_BLANKED:
        return True
    return bool(
        _TELEMETRY.fullmatch(bare)
        or _GIT_CONFIG.fullmatch(bare)
        or _CARGO_REGISTRY.fullmatch(bare)
        or _PACKAGE_CREDENTIAL.match(bare.replace("-", "_"))
        or _BUNDLER_HOST.match(bare)
    )
