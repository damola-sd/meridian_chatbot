import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

SESSION_TTL_MINUTES = 30

# ---------------------------------------------------------------------------
# Session dataclass
# ---------------------------------------------------------------------------

@dataclass
class Session:
    """
    Holds all per-conversation state for a single customer session.

    history stores messages in the OpenAI format:
        {"role": "user" | "assistant" | "tool", "content": ...}
    It is passed directly to the OpenAI API on every turn.
    """

    session_id: str
    customer_id: str | None = None
    customer_name: str | None = None
    customer_email: str | None = None
    failed_pin_attempts: int = 0
    history: list[dict] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_active: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------

    @property
    def is_authenticated(self) -> bool:
        return self.customer_id is not None

    @property
    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) - self.last_active > timedelta(minutes=SESSION_TTL_MINUTES)

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def touch(self) -> None:
        """Refresh the idle TTL on every interaction."""
        self.last_active = datetime.now(timezone.utc)

    def authenticate(self, customer_id: str, name: str, email: str) -> None:
        self.customer_id = customer_id
        self.customer_name = name
        self.customer_email = email
        self.failed_pin_attempts = 0
        logger.info("Session %s authenticated as customer %s", self.session_id, customer_id)

    def record_failed_pin(self) -> None:
        self.failed_pin_attempts += 1
        logger.warning(
            "Session %s — failed PIN attempt #%d",
            self.session_id,
            self.failed_pin_attempts,
        )

    def add_message(self, message: dict) -> None:
        self.history.append(message)

    def add_messages(self, messages: list[dict]) -> None:
        self.history.extend(messages)


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
# Single dict for the process lifetime — appropriate for a single Railway
# container. Swap for Redis if horizontal scaling is ever needed; the
# Session interface above stays unchanged.

_store: dict[str, Session] = {}


def get_or_create(session_id: str) -> Session:
    """
    Return an existing live session or create a fresh one.
    Expired sessions are silently replaced (customer must re-authenticate).
    """
    existing = _store.get(session_id)

    if existing is not None and not existing.is_expired:
        existing.touch()
        return existing

    if existing is not None:
        logger.info("Session %s expired — starting fresh", session_id)

    session = Session(session_id=session_id)
    _store[session_id] = session
    logger.info("Session %s created", session_id)
    return session


def delete(session_id: str) -> None:
    _store.pop(session_id, None)


def cleanup_expired() -> int:
    """
    Remove all expired sessions from memory.
    Call periodically from a FastAPI background task.
    Returns the number of sessions removed.
    """
    expired = [sid for sid, s in _store.items() if s.is_expired]
    for sid in expired:
        del _store[sid]
    if expired:
        logger.info("Cleaned up %d expired session(s)", len(expired))
    return len(expired)


def active_count() -> int:
    return sum(1 for s in _store.values() if not s.is_expired)
