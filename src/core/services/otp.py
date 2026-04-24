import uuid
from typing import Any, cast, Awaitable

from redis.asyncio import Redis


class OTPService:
    """OTP generation and verification via Redis.

    Redis keys:
    - otp:{user_id} → 6-digit code (TTL=300s)
    - otp_reverse:{code} → user_id (TTL=300s) — for bot reverse lookup
    - otp_rate:{user_id} → rate-limit flag (TTL=60s)

    Verification is idempotent: both verify_code() and verify_code_by_value()
    atomically delete BOTH keys to prevent cross-channel replay attacks.
    """

    OTP_TTL = 300  # 5 минут
    RATE_LIMIT_TTL = 60  # 1 минута

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def generate_code(self, user_id: uuid.UUID) -> str:
        """Generate a 6-digit OTP code for a user.

        Writes two keys atomically:
        - otp:{user_id} → code (for web cabinet verification)
        - otp_reverse:{code} → user_id (for bot reverse lookup)

        Rate-limited to 1 request per 60 seconds per user.

        :raises RateLimitExceeded: If code was generated less than 60s ago.
        """
        rate_key = f"otp_rate:{user_id}"
        exists = await self._redis.exists(rate_key)
        if exists:
            raise RateLimitExceeded("OTP code can be generated once per minute")

        code = self._generate_code()
        otp_key = f"otp:{user_id}"
        reverse_key = f"otp_reverse:{code}"

        # Атомарно: записываем код + reverse lookup + rate-limit флаг
        async with self._redis.pipeline(transaction=True) as pipe:
            await pipe.set(otp_key, code, ex=self.OTP_TTL)
            await pipe.set(reverse_key, str(user_id), ex=self.OTP_TTL)
            await pipe.set(rate_key, "1", ex=self.RATE_LIMIT_TTL)
            await pipe.execute()

        return code

    async def verify_code(self, user_id: uuid.UUID, code: str) -> bool:
        """Verify an OTP code for a user (web cabinet flow).

        Atomically deletes BOTH keys (otp:{user_id} and otp_reverse:{code})
        to prevent the bot from re-verifying the same code after the web
        cabinet has consumed it.

        Returns True if code was valid, False otherwise.
        """
        otp_key = f"otp:{user_id}"
        reverse_key = f"otp_reverse:{code}"

        async with self._redis.pipeline(transaction=True) as pipe:
            await pipe.getdel(otp_key)
            await pipe.getdel(reverse_key)
            results = await pipe.execute()

        stored = results[0]
        if stored is None:
            return False
        return stored.decode() == code

    async def verify_code_by_value(self, code: str) -> uuid.UUID | None:
        """Find user_id by OTP code value (reverse lookup, bot flow).

        Atomically deletes BOTH keys (otp_reverse:{code} and otp:{user_id})
        to prevent the web cabinet from re-verifying the same code after
        the bot has consumed it.

        :returns: user_id if code is valid, None otherwise.
        """
        reverse_key = f"otp_reverse:{code}"
        lua_script = """
        local user_id = redis.call('GETDEL', KEYS[1])
        if user_id then
            redis.call('DEL', 'otp:' .. user_id)
        end
        return user_id
        """
        user_id_bytes = await cast(
            Awaitable[Any], self._redis.eval(lua_script, 1, reverse_key)
        )
        if user_id_bytes is None:
            return None

        return uuid.UUID(user_id_bytes.decode())

    @staticmethod
    def _generate_code() -> str:
        """Generate a 6-digit numeric code."""
        import secrets

        return f"{secrets.randbelow(1_000_000):06d}"


class RateLimitExceeded(Exception):
    """Raised when OTP generation is rate-limited."""

    pass
