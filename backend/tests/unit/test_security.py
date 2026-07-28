"""Password hashing and session tokens."""

from __future__ import annotations

from api.security import (
    hash_password,
    hash_token,
    new_session_token,
    session_expiry,
    utc_now,
    verify_password,
)


class TestPasswordHashing:
    def test_round_trip(self) -> None:
        digest, salt = hash_password("correct horse battery staple")
        assert verify_password("correct horse battery staple", digest, salt)

    def test_wrong_password_is_rejected(self) -> None:
        digest, salt = hash_password("correct horse battery staple")
        assert not verify_password("Correct horse battery staple", digest, salt)

    def test_the_same_password_hashes_differently_each_time(self) -> None:
        """A per-user salt means two people with the same password have different
        digests, so cracking one does not crack the other."""
        first, first_salt = hash_password("same password")
        second, second_salt = hash_password("same password")
        assert first != second
        assert first_salt != second_salt

    def test_a_corrupt_salt_fails_the_login_rather_than_crashing(self) -> None:
        assert not verify_password("anything", "deadbeef", "not-hex")

    def test_unicode_passwords_work(self) -> None:
        digest, salt = hash_password("paßwort-日本語-🔑")
        assert verify_password("paßwort-日本語-🔑", digest, salt)

    def test_the_plaintext_never_appears_in_the_digest(self) -> None:
        digest, salt = hash_password("hunter2")
        assert "hunter2" not in digest
        assert "hunter2" not in salt


class TestSessionTokens:
    def test_the_stored_value_is_a_hash_of_the_issued_one(self) -> None:
        """A leaked database yields no usable session: the raw token cannot be
        recovered from its SHA-256."""
        raw, stored = new_session_token()
        assert stored != raw
        assert hash_token(raw) == stored

    def test_tokens_are_unique(self) -> None:
        assert len({new_session_token()[0] for _ in range(200)}) == 200

    def test_tokens_carry_enough_entropy(self) -> None:
        """32 bytes, url-safe base64 -- comfortably beyond brute force."""
        raw, _ = new_session_token()
        assert len(raw) >= 40

    def test_hashing_is_deterministic(self) -> None:
        assert hash_token("abc") == hash_token("abc")


class TestTimestamps:
    def test_expiry_is_in_the_future_and_sorts_against_now(self) -> None:
        """Both use the same format, so `WHERE expires_at > ?` compares correctly as
        strings -- which is the whole reason timestamps are stored as ISO text."""
        assert session_expiry(1) > utc_now()

    def test_format_matches_the_schema_defaults(self) -> None:
        stamp = utc_now()
        assert len(stamp) == 20
        assert stamp.endswith("Z")
        assert stamp[4] == "-" and stamp[10] == "T"

    def test_a_longer_ttl_expires_later(self) -> None:
        assert session_expiry(24) > session_expiry(1)
