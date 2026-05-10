import secrets
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

    MAX_COLLISION_RETRIES = 10

    async def generate_code(self, user_id: uuid.UUID) -> str:
        """Generate a 6-digit OTP code for a user.

        Writes two keys atomically:
        - otp:{user_id} → code (for web cabinet verification)
        - otp_reverse:{code} → user_id (for bot reverse lookup)

        Rate-limited to 1 request per 60 seconds per user.
        Handles collisions by retrying up to MAX_COLLISION_RETRIES.

        :raises RateLimitExceeded: If code was generated less than 60s ago.
        """
        rate_key = f"otp_rate:{user_id}"
        exists = await self._redis.exists(rate_key)
        if exists:
            raise RateLimitExceeded("OTP code can be generated once per minute")

        otp_key = f"otp:{user_id}"

        for _ in range(self.MAX_COLLISION_RETRIES):
            code = self._generate_code()
            reverse_key = f"otp_reverse:{code}"
            collision = await self._redis.exists(reverse_key)
            if not collision:
                break
        else:
            # All retries exhausted — use timestamped code as last resort
            import time

            code = f"{int(time.time()) % 1_000_000:06d}"
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
        return f"{secrets.randbelow(1_000_000):06d}"


    async def generate_invite_code(self, company_id: uuid.UUID) -> str:
        """Generate a 6-digit invite code bound to a company.

        Stores invite:{code} → str(company_id) with TTL=86400s (24h).
        No rate-limiting — invites are cheap and stateless.
        Handles collisions by retrying up to MAX_COLLISION_RETRIES.
        """
        for _ in range(self.MAX_COLLISION_RETRIES):
            code = self._generate_code()
            key = f"invite:{code}"
            collision = await self._redis.exists(key)
            if not collision:
                break
        else:
            # All retries exhausted — use timestamped code as last resort
            import time

            code = f"{int(time.time()) % 1_000_000:06d}"
            key = f"invite:{code}"

        await self._redis.set(key, str(company_id), ex=86_400)
        return code

    async def verify_invite_code(self, code: str) -> uuid.UUID | None:
        """Verify an invite code and return the bound company_id.

        Atomically deletes the key (GETDEL) so codes are single-use.
        :returns: company_id if valid, None otherwise.
        """
        key = f"invite:{code}"
        raw = await self._redis.getdel(key)
        if raw is None:
            return None
        return uuid.UUID(raw.decode() if isinstance(raw, bytes) else raw)


class RateLimitExceeded(Exception):
    """Raised when OTP generation is rate-limited."""

    pass
