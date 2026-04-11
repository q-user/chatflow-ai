import uuid

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.database.models.user import UserTable


class OTPService:
    """OTP generation and verification via Redis.

    Redis keys:
    - otp:{user_id} → 6-digit code (TTL=300s)
    - otp_rate:{user_id} → rate-limit flag (TTL=60s)
    """

    OTP_TTL = 300  # 5 минут
    RATE_LIMIT_TTL = 60  # 1 минута

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def generate_code(self, user_id: uuid.UUID) -> str:
        """Generate a 6-digit OTP code for a user.

        Rate-limited to 1 request per 60 seconds per user.

        :raises RateLimitExceeded: If code was generated less than 60s ago.
        """
        rate_key = f"otp_rate:{user_id}"
        exists = await self._redis.exists(rate_key)
        if exists:
            raise RateLimitExceeded("OTP code can be generated once per minute")

        code = self._generate_code()
        otp_key = f"otp:{user_id}"

        # Атомарно: записываем код + rate-limit флаг
        async with self._redis.pipeline(transaction=True) as pipe:
            await pipe.set(otp_key, code, ex=self.OTP_TTL)
            await pipe.set(rate_key, "1", ex=self.RATE_LIMIT_TTL)
            await pipe.execute()

        return code

    async def verify_code(self, user_id: uuid.UUID, code: str) -> bool:
        """Verify an OTP code for a user.

        Uses atomic GETDEL to prevent replay attacks.
        The key is consumed regardless of code correctness — this prevents
        brute-force retries but also means a wrong code consumes the OTP.
        Returns True if code was valid, False otherwise.
        """
        otp_key = f"otp:{user_id}"
        stored_code = await self._redis.getdel(otp_key)
        if stored_code is None:
            return False
        return stored_code.decode() == code

    @staticmethod
    def _generate_code() -> str:
        """Generate a 6-digit numeric code."""
        import secrets

        return f"{secrets.randbelow(1_000_000):06d}"

    async def verify_and_link_messenger(
        self,
        user_id: uuid.UUID,
        code: str,
        messenger_type: str,  # Already validated as Literal["TG", "YM"] at schema level
        messenger_id: str,
        session: AsyncSession,
    ) -> None:
        """Verify OTP and link messenger to user.

        :raises InvalidOTPError: If code is invalid or expired.
        :raises UserNotFoundError: If user doesn't exist.
        """
        # Атомарная верификация (GETDEL)
        if not await self.verify_code(user_id, code):
            raise InvalidOTPError("Invalid or expired OTP code")

        messenger_field = self._MESSENGER_MAP.get(messenger_type)
        # messenger_type уже валидирован схемой — это не должно случиться
        if messenger_field is None:  # pragma: no cover
            raise UnknownMessengerTypeError(messenger_type)

        user = await session.get(UserTable, user_id)
        if user is None:
            raise UserNotFoundError("User not found")

        setattr(user, messenger_field, messenger_id)
        # session.commit() вызывается на уровне роутера (get_db_session)

    # Маппинг messenger_type → поле UserTable
    _MESSENGER_MAP: dict[str, str] = {
        "TG": "telegram_id",
        "YM": "yandex_id",
    }


class RateLimitExceeded(Exception):
    """Raised when OTP generation is rate-limited."""

    pass


class InvalidOTPError(Exception):
    """Raised when OTP code is invalid or expired."""

    pass


class UnknownMessengerTypeError(Exception):
    """Raised when messenger_type is not recognized."""

    def __init__(self, messenger_type: str) -> None:
        self.messenger_type = messenger_type
        super().__init__(f"Unknown messenger type: {messenger_type}. Expected TG or YM.")


class UserNotFoundError(Exception):
    """Raised when user is not found."""

    pass
