"""Password hashing and session tokens.

Uses only the standard library. :func:`hashlib.scrypt` is a memory-hard KDF built
into CPython, so `passlib` or `argon2-cffi` would add a dependency (and a C build)
for a guarantee already available.

Two rules this module exists to enforce:

* A password is never stored, only its scrypt digest with a per-user salt.
* A session token is never stored, only its SHA-256. A leaked database therefore
  yields no usable session, because the raw token cannot be recovered from the hash.
  Tokens are hashed with plain SHA-256 rather than scrypt because they are already
  256 bits of entropy from a CSPRNG — there is no guessable password to slow down,
  and a KDF on the read path would add latency to every request for nothing.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

# Roughly 100 ms per hash on current hardware: slow enough to make offline guessing
# expensive, fast enough that signing in does not feel broken.
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_KEY_LEN = 64
_SALT_BYTES = 16
_TOKEN_BYTES = 32

MIN_PASSWORD_LENGTH = 12
"""Length is the only password rule enforced.

Composition rules ("one uppercase, one symbol") measurably push people towards
`Password1!` and a sticky note. Current NIST guidance is to require length, screen
against known-breached passwords, and stop there.
"""


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """Hash a password with scrypt.

    Args:
        password: The plaintext password.
        salt: Hex-encoded salt. Generated if omitted — supply one only to verify
            an existing hash.

    Returns:
        ``(hash_hex, salt_hex)``, both suitable for storage.
    """
    salt_bytes = bytes.fromhex(salt) if salt else secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt_bytes,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_KEY_LEN,
    )
    return digest.hex(), salt_bytes.hex()


def verify_password(password: str, stored_hash: str, stored_salt: str) -> bool:
    """Check a password against a stored hash.

    Args:
        password: The plaintext to check.
        stored_hash: Hex digest from the database.
        stored_salt: Hex salt from the database.

    Returns:
        ``True`` if the password matches.
    """
    try:
        candidate, _ = hash_password(password, stored_salt)
    except ValueError:
        # A malformed salt means a corrupt row, which is a failed login, not a crash.
        return False
    # Constant-time: a byte-by-byte comparison leaks how much of the digest matched,
    # which is enough to reconstruct it one byte at a time.
    return hmac.compare_digest(candidate, stored_hash)


def new_session_token() -> tuple[str, str]:
    """Mint a session token.

    Returns:
        ``(raw_token, token_sha256)``. The raw token goes to the client in a cookie
        and is never written down; only the hash is stored.
    """
    raw = secrets.token_urlsafe(_TOKEN_BYTES)
    return raw, hash_token(raw)


def hash_token(raw_token: str) -> str:
    """Hash a session token for lookup.

    Args:
        raw_token: The token as presented by the client.

    Returns:
        Its SHA-256 hex digest.
    """
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def session_expiry(ttl_hours: int) -> str:
    """Return an ISO-8601 UTC expiry timestamp.

    Args:
        ttl_hours: Session lifetime in hours.

    Returns:
        The expiry, formatted to match the timestamps written by SQL defaults so
        string comparison in ``WHERE expires_at > ?`` is correct.
    """
    return (datetime.now(UTC) + timedelta(hours=ttl_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_now() -> str:
    """Return the current time as an ISO-8601 UTC timestamp.

    Returns:
        The current time in the same format used throughout the schema.
    """
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
