from __future__ import annotations

import hashlib

from saxo_auth import SaxoOAuthConfig
from saxo_oauth_diagnostics import safe_oauth_runtime_preflight


def test_live_preflight_exposes_only_masked_app_key_and_sanitized_redirect():
    config = SaxoOAuthConfig(
        client_id="1234-5678-9012-ABCD",
        client_secret="secret-MUST-NEVER-PRINT",
        redirect_uri="https://example.test/Saxo_OpenAPI?code=SENSITIVE_CODE#state",
        environment="live",
    )
    data = safe_oauth_runtime_preflight(config)
    assert data["environment"] == "LIVE"
    assert data["auth_endpoint"] == "https://live.logonvalidation.net/authorize"
    assert data["auth_endpoint_matches_environment"] is True
    assert data["oauth_flow"] == "authorization_code"
    assert data["redirect_uri_without_query"] == "https://example.test/Saxo_OpenAPI"
    assert data["redirect_contains_query"] is True
    assert data["client_id_suffix"] == "...-ABCD"
    assert data["client_id_length"] == len(config.client_id)
    assert data["client_id_sha256_prefix"] == hashlib.sha256(
        config.client_id.encode()
    ).hexdigest()[:16]
    assert config.client_id not in str(data)
    assert config.client_secret not in str(data)
    assert "SENSITIVE_CODE" not in str(data)


def test_preflight_flags_wrong_authorize_environment_and_quoted_key():
    cfg = SaxoOAuthConfig(
        client_id="'wrongly-quoted-key'",
        client_secret="hidden",
        redirect_uri="https://example.test/Saxo_OpenAPI",
        environment="live",
        auth_base_url="https://sim.logonvalidation.net",
    )
    d = safe_oauth_runtime_preflight(cfg)
    assert d["auth_endpoint_matches_environment"] is False
    assert d["client_id_contains_quotes_or_controls"] is True
    assert d["redirect_contains_query"] is False


def test_short_key_is_not_disclosed():
    cfg = SaxoOAuthConfig(
        client_id="abc",
        client_secret="hidden",
        redirect_uri="https://example.test/Saxo_OpenAPI",
    )
    data = safe_oauth_runtime_preflight(cfg)
    assert data["client_id_suffix"] == "[short]"
    assert "abc" not in str(data)
