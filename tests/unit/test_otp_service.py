"""Unit tests for OTPService with fakeredis."""

import uuid

import pytest
from fakeredis import FakeAsyncRedis

from core.services.otp import OTPService, RateLimitExceeded


@pytest.fixture
def fake_redis() -> FakeAsyncRedis:
    return FakeAsyncRedis(decode_responses=False)


@pytest.fixture
def otp_service(fake_redis: FakeAsyncRedis) -> OTPService:
    return OTPService(fake_redis)


@pytest.fixture
def user_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.mark.asyncio
async def test_generate_code_returns_6_digits(
    otp_service: OTPService, user_id: uuid.UUID
):
    """Generated code is a 6-digit string."""
    code = await otp_service.generate_code(user_id)

    assert isinstance(code, str)
    assert len(code) == 6
    assert code.isdigit()


@pytest.mark.asyncio
async def test_generate_code_stores_in_redis(
    otp_service: OTPService, fake_redis: FakeAsyncRedis, user_id: uuid.UUID
):
    """Generated code is stored in Redis with correct key and TTL."""
    code = await otp_service.generate_code(user_id)

    stored = await fake_redis.get(f"otp:{user_id}")
    assert stored is not None
    assert stored.decode() == code

    # Check TTL is set (should be > 0)
    ttl = await fake_redis.ttl(f"otp:{user_id}")
    assert ttl > 0
    assert ttl <= OTPService.OTP_TTL  # 300 seconds


@pytest.mark.asyncio
async def test_generate_code_rate_limit(otp_service: OTPService, user_id: uuid.UUID):
    """Second generate within 60s raises RateLimitExceeded."""
    # First call — success
    await otp_service.generate_code(user_id)

    # Second call — rate limited
    with pytest.raises(RateLimitExceeded, match="once per minute"):
        await otp_service.generate_code(user_id)


@pytest.mark.asyncio
async def test_generate_code_rate_limit_key(
    otp_service: OTPService, fake_redis: FakeAsyncRedis, user_id: uuid.UUID
):
    """Rate limit flag is stored with correct TTL."""
    await otp_service.generate_code(user_id)

    ttl = await fake_redis.ttl(f"otp_rate:{user_id}")
    assert ttl > 0
    assert ttl <= OTPService.RATE_LIMIT_TTL  # 60 seconds


@pytest.mark.asyncio
async def test_verify_code_valid(otp_service: OTPService, user_id: uuid.UUID):
    """Valid code verification returns True."""
    code = await otp_service.generate_code(user_id)

    result = await otp_service.verify_code(user_id, code)
    assert result is True


@pytest.mark.asyncio
async def test_verify_code_invalid(otp_service: OTPService, user_id: uuid.UUID):
    """Wrong code returns False."""
    await otp_service.generate_code(user_id)

    result = await otp_service.verify_code(user_id, "000000")
    assert result is False


@pytest.mark.asyncio
async def test_verify_code_no_key(otp_service: OTPService, user_id: uuid.UUID):
    """Verify without any generated code returns False."""
    result = await otp_service.verify_code(user_id, "123456")
    assert result is False


@pytest.mark.asyncio
async def test_verify_code_idempotent(otp_service: OTPService, user_id: uuid.UUID):
    """Second verification of same code returns False (GETDEL removes key)."""
    code = await otp_service.generate_code(user_id)

    # First verify — success
    assert await otp_service.verify_code(user_id, code) is True

    # Second verify — code consumed
    assert await otp_service.verify_code(user_id, code) is False


@pytest.mark.asyncio
async def test_verify_code_different_users(
    otp_service: OTPService,
):
    """Codes for different users are independent."""
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()

    code_a = await otp_service.generate_code(user_a)
    code_b = await otp_service.generate_code(user_b)

    assert code_a != code_b  # Different users → different codes
    assert await otp_service.verify_code(user_a, code_a) is True
    assert await otp_service.verify_code(user_b, code_b) is True
    assert await otp_service.verify_code(user_a, code_b) is False


@pytest.mark.asyncio
async def test_generate_code_overwrites_previous(
    otp_service: OTPService, fake_redis: FakeAsyncRedis, user_id: uuid.UUID
):
    """Generating a new code replaces the old one."""
    # First generation (then delete to reset rate limit)
    code1 = await otp_service.generate_code(user_id)

    # Delete rate limit key to allow second generation
    await fake_redis.delete(f"otp_rate:{user_id}")

    code2 = await otp_service.generate_code(user_id)

    # Old code should be overwritten
    stored = await fake_redis.get(f"otp:{user_id}")
    assert stored.decode() == code2
    assert code1 != code2  # Different codes


@pytest.mark.asyncio
async def test_verify_code_consumes_key_on_invalid(
    otp_service: OTPService, user_id: uuid.UUID
):
    """Invalid verification ALSO consumes the OTP (GETDEL is atomic).

    This is a trade-off: wrong codes consume the OTP, preventing
    brute-force retries but also protecting against replay attacks.
    """
    code = await otp_service.generate_code(user_id)

    # Wrong code — consumes the key
    assert await otp_service.verify_code(user_id, "999999") is False

    # Real code no longer works — key was consumed by GETDEL
    assert await otp_service.verify_code(user_id, code) is False
