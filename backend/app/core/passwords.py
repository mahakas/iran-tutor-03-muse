"""Password hashing (Argon2id) and password policy.

Passwords are never stored or logged in plaintext. Only the Argon2id digest produced
here is persisted (`users.password_hash`). Existing digests that no longer match the
current cost parameters are transparently upgraded on the next successful login.

`argon2-cffi` is the only supported backend; if it is missing the module raises at
startup rather than silently falling back to a weaker hash.
"""

from __future__ import annotations

import logging
import secrets

logger = logging.getLogger(__name__)

try:  # pragma: no cover - import guard only
    from argon2 import PasswordHasher
    from argon2.exceptions import InvalidHashError, VerifyMismatchError, VerificationError
    from argon2.low_level import Type
except ModuleNotFoundError as error:  # pragma: no cover
    raise RuntimeError(
        "argon2-cffi is required for password authentication. "
        "Install it with `pip install -r requirements.txt`."
    ) from error

# RFC 9106 low-memory profile tuned for a web request path:
# 64 MiB, 3 passes, 4 lanes. Argon2id resists both GPU cracking and side channels.
_PASSWORD_HASHER = PasswordHasher(
    time_cost=3,
    memory_cost=64 * 1024,
    parallelism=4,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128
# Very short passwords are allowed only by an explicit environment opt-in used by
# development seeds and the test suite (`PASSWORD_MIN_LENGTH`). Production guard
# refuses such a configuration.
_DEFAULT_MIN_PASSWORD_LENGTH = MIN_PASSWORD_LENGTH

# A constant digest used to burn comparable CPU time when the account does not exist,
# so a failed login for an unknown phone is not measurably faster than a wrong password.
_DUMMY_HASH = _PASSWORD_HASHER.hash("darsyar-timing-equalizer-not-a-real-password")


def hash_password(password: str) -> str:
    """Return an Argon2id digest for `password`. Never returns the input."""
    if not password:
        raise ValueError("password must not be empty")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise ValueError("password is too long")
    return _PASSWORD_HASHER.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    """Constant-time-ish verification. Returns False for missing/unknown hashes."""
    if not password or not password_hash:
        # Burn the same work as a real verification to blunt timing enumeration.
        burn_verification()
        return False
    try:
        return _PASSWORD_HASHER.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    except Exception:  # noqa: BLE001 - never leak hashing internals to callers
        logger.exception("password.verify_failed")
        return False


def burn_verification() -> None:
    """Spend the same time as a real verify (used when no account/hash exists)."""
    try:
        _PASSWORD_HASHER.verify(_DUMMY_HASH, "darsyar-timing-equalizer-not-a-real-password")
    except Exception:  # noqa: BLE001 - the result is irrelevant by design
        pass


def needs_rehash(password_hash: str | None) -> bool:
    if not password_hash:
        return False
    try:
        return _PASSWORD_HASHER.check_needs_rehash(password_hash)
    except Exception:  # noqa: BLE001
        return True


def password_policy_error(password: str, *, min_length: int | None = None) -> str | None:
    """Return a Persian validation message, or `None` when the password is acceptable."""
    cleaned = password or ""
    required = max(1, int(min_length if min_length is not None else _DEFAULT_MIN_PASSWORD_LENGTH))
    if len(cleaned) < required:
        return f"رمز عبور باید حداقل {required} کاراکتر باشد."
    if len(cleaned) > MAX_PASSWORD_LENGTH:
        return f"رمز عبور نباید بیشتر از {MAX_PASSWORD_LENGTH} کاراکتر باشد."
    if cleaned.strip() != cleaned:
        return "رمز عبور نباید با فاصله شروع یا پایان یابد."
    if not any(ch.isalpha() for ch in cleaned):
        return "رمز عبور باید حداقل یک حرف داشته باشد."
    if not any(ch.isdigit() for ch in cleaned):
        return "رمز عبور باید حداقل یک رقم داشته باشد."
    if cleaned.lower() in _COMMON_PASSWORDS:
        return "این رمز عبور بسیار رایج است؛ رمز دیگری انتخاب کنید."
    return None


_COMMON_PASSWORDS = frozenset(
    {
        "12345678",
        "123456789",
        "1234567890",
        "password",
        "password1",
        "qwerty123",
        "11111111",
        "abcd1234",
        "iloveyou",
        "admin123",
    }
)


def generate_temporary_password(length: int = 14) -> str:
    """Random password for admin-created accounts. Always satisfies the policy."""
    alphabet = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    while True:
        candidate = "".join(secrets.choice(alphabet) for _ in range(max(12, length)))
        candidate = candidate[:10] + str(secrets.randbelow(10)) + candidate[10:]
        if password_policy_error(candidate) is None:
            return candidate[:MAX_PASSWORD_LENGTH]
