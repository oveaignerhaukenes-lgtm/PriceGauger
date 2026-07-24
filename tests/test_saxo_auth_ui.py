from __future__ import annotations

from saxo_auth_ui import build_signed_oauth_state, valid_signed_oauth_state


def test_signed_state_survives_without_streamlit_session() -> None:
    state = build_signed_oauth_state("secret-value", now=1_000)

    assert valid_signed_oauth_state(state, "secret-value", now=1_120)


def test_signed_state_rejects_wrong_secret() -> None:
    state = build_signed_oauth_state("correct-secret", now=1_000)

    assert not valid_signed_oauth_state(state, "wrong-secret", now=1_010)


def test_signed_state_rejects_tampering() -> None:
    state = build_signed_oauth_state("secret-value", now=1_000)
    timestamp, nonce, signature = state.split(".", 2)
    tampered = f"{timestamp}.{nonce}x.{signature}"

    assert not valid_signed_oauth_state(tampered, "secret-value", now=1_010)


def test_signed_state_expires() -> None:
    state = build_signed_oauth_state("secret-value", now=1_000)

    assert not valid_signed_oauth_state(state, "secret-value", now=1_601, max_age_seconds=600)
