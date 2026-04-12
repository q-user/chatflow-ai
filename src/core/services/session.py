"""Redis-based FSM for data accumulation sessions."""

import json
import uuid

from pydantic import BaseModel
from redis.asyncio import Redis

from core.domain.incoming import IncomingEnvelope


class SessionSnapshot(BaseModel):
    """Snapshot of accumulated session data for Celery task handoff."""

    user_id: uuid.UUID
    company_id: uuid.UUID | None = None  # filled by hook_router
    bot_instance_id: uuid.UUID | None = None  # filled by hook_router
    module_type: str | None = None  # filled by hook_router
    chat_id: str | None = None  # filled by hook_router — destination for results
    messenger_type: str | None = None  # filled by hook_router — "TG" / "YM"
    items: list[dict]  # [{"text": ..., "file_path": ..., "file_type": ...}]


class SessionService:
    """Redis-based FSM for data accumulation sessions.

    Redis keys:
    - session:{user_id}:state → current state ("idle" / "collecting")
    - session:{user_id}:payload → Redis list of accumulated items (JSON)
    - session:{user_id}:files → Redis list of downloaded file paths

    TTL: 3600 seconds (1 hour) — auto-cleanup for stale sessions.
    """

    SESSION_TTL = 3600

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    # ──────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────

    async def handle_new(self, user_id: uuid.UUID) -> None:
        """Start a new accumulation session.

        Resets any existing session state and transitions to "collecting".
        """
        pipe = self._redis.pipeline(transaction=True)
        await pipe.delete(
            self._state_key(user_id),
            self._payload_key(user_id),
            self._files_key(user_id),
        )
        await pipe.set(
            self._state_key(user_id),
            "collecting",
            ex=self.SESSION_TTL,
        )
        await pipe.execute()

    async def accumulate(self, user_id: uuid.UUID, envelope: IncomingEnvelope) -> None:
        """Add incoming data to the active session.

        Stores text/file metadata as JSON in a Redis list.
        Refreshes TTL on state and payload keys.
        """
        item = {
            "text": envelope.text,
            "file_id": envelope.file_id,
            "file_type": envelope.file_type,
            "file_name": envelope.file_name,
        }

        pipe = self._redis.pipeline(transaction=True)
        await pipe.rpush(self._payload_key(user_id), json.dumps(item))  # ty: ignore[invalid-await]
        await pipe.expire(self._payload_key(user_id), self.SESSION_TTL)
        await pipe.expire(self._state_key(user_id), self.SESSION_TTL)
        await pipe.execute()

    async def handle_compile(self, user_id: uuid.UUID) -> SessionSnapshot | None:
        """Finalize the session and return a snapshot for Celery.

        :returns: SessionSnapshot if session exists and is collecting, else None.
        """
        state = await self.get_state(user_id)
        if state != "collecting":
            return None

        pipe = self._redis.pipeline(transaction=True)
        await pipe.lrange(self._payload_key(user_id), 0, -1)  # ty: ignore[invalid-await]
        await pipe.delete(
            self._state_key(user_id),
            self._payload_key(user_id),
            self._files_key(user_id),
        )
        results = await pipe.execute()

        raw_items = results[0]
        items = [
            json.loads(r.decode() if isinstance(r, bytes) else r) for r in raw_items
        ]

        return SessionSnapshot(
            user_id=user_id,
            # company_id, bot_instance_id, module_type — filled by hook_router
            items=items,
        )

    async def get_state(self, user_id: uuid.UUID) -> str | None:
        """Current session state: "idle" / "collecting" / None."""
        raw = await self._redis.get(self._state_key(user_id))
        if raw is None:
            return None
        return raw.decode() if isinstance(raw, bytes) else raw

    # ──────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────

    @staticmethod
    def _state_key(user_id: uuid.UUID) -> str:
        return f"session:{user_id}:state"

    @staticmethod
    def _payload_key(user_id: uuid.UUID) -> str:
        return f"session:{user_id}:payload"

    @staticmethod
    def _files_key(user_id: uuid.UUID) -> str:
        return f"session:{user_id}:files"
