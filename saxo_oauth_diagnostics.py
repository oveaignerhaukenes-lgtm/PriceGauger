"""Read-only, secret-free OAuth preflight for operator diagnosis.

No Saxo calls, token access, database changes or session mutation.
"""
from __future__ import annotations

import hashlib
from urllib.parse import urlsplit, urlunsplit

from saxo_auth import LIVE_AUTH_BASE_URL, SIM_AUTH_BASE_URL, SaxoOAuthConfig


def safe_oauth_runtime_preflight(config: SaxoOAuthConfig) -> dict[str, str | int | bool]:
    """Return only safe diagnostics for the effective running configuration.

    The configured AppKey is never returned: compare the last few characters
    and an SHA-256 fingerprint to the independently inspected LIVE app key.
    Do not include the AppSecret, state, code, token or redirect query values.
    """
    key = config.client_id
    parsed = urlsplit(config.redirect_uri)
    redirect_without_query = urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, "", "")
    )
    expected_base = (
        LIVE_AUTH_BASE_URL if config.environment == "live" else SIM_AUTH_BASE_URL
    )
    actual_auth_endpoint = config.authorization_url
    return {
        "environment": config.environment.upper(),
        "oauth_flow": "authorization_code",
        "auth_endpoint": actual_auth_endpoint,
        "auth_endpoint_matches_environment": actual_auth_endpoint == f"{expected_base}/authorize",
        "redirect_uri_without_query": redirect_without_query,
        "redirect_contains_query": bool(parsed.query or parsed.fragment),
        "client_id_suffix": f"...{key[-5:]}" if len(key) > 5 else "[short]",
        "client_id_length": len(key),
        "client_id_sha256_prefix": hashlib.sha256(key.encode("utf-8")).hexdigest()[:16],
        "client_id_contains_quotes_or_controls": any(
            ch in {'"', "'"} or ord(ch) < 32 or ord(ch) == 127 for ch in key
        ),
    }
