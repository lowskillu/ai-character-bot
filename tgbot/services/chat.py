"""Chat use case: load context, then persist a turn.

Exists to keep database work off the critical path of the OpenRouter call.

The handler used to wrap the whole exchange in one ``_get_session()`` block,
which opens a pooled connection *and* a write transaction and held both across
a network call that can take tens of seconds. With a pool of 20 that capped the
bot at roughly 20 simultaneous conversations, and every one of them sat
``idle in transaction`` on the server, blocking autovacuum.

Everything here returns frozen dataclasses, never live ORM instances. That is
load-bearing: once the session closes, touching an attribute on a detached
instance raises ``MissingGreenlet``, so the profile is serialised while the
session is still open.
"""

import json
import logging
from dataclasses import dataclass
from typing import Optional, Tuple

from sqlalchemy import select

from tgbot.database.models import Profile
from tgbot.database.orm import AsyncORM
from tgbot.services.dialog_history import (
    get_profile_history_from_db,
    save_profile_message,
    trim_profile_history,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Turn:
    role: str  # "user" | "bot"
    text: str


@dataclass(frozen=True)
class ChatContext:
    """Everything the LLM call needs, fully detached from the ORM."""

    profile_id: int
    profile_name: str
    description_for_ai: str
    history: Tuple[Turn, ...]


from tgbot.services.image_prompts import format_profile_value


def serialize_profile_for_ai(profile: Profile) -> str:
    """Render a profile as the compact JSON blob the system prompt embeds.

    Must be called while the profile's session is still open.
    """
    try:
        raw_appearance = json.loads(profile.appearance) if profile.appearance else {}
    except Exception:
        raw_appearance = {}
    try:
        raw_body = json.loads(profile.body_type) if profile.body_type else {}
    except Exception:
        raw_body = {}

    appearance = {k: format_profile_value(v) for k, v in raw_appearance.items() if v}
    body = {k: format_profile_value(v) for k, v in raw_body.items() if v}

    profile_dict = {
        "name": profile.name,
        "appearance": appearance,
        "body": body,
        "clothing": profile.clothing,
        "personality": profile.personality,
        "location": profile.location,
        "role": profile.role,
        "description": profile.description,
    }
    return json.dumps(
        {k: v for k, v in profile_dict.items() if v is not None},
        ensure_ascii=False,
    )


async def load_chat_context(user_id: int, profile_id: int) -> Optional[ChatContext]:
    """Read the profile and recent history in one short transaction.

    Returns None when the profile does not exist or is not this user's. The
    ``user_id`` predicate is what stops one user reading another's profile by
    guessing an id.
    """
    async with AsyncORM.users._get_session() as session:
        result = await session.execute(
            select(Profile).where(Profile.id == profile_id, Profile.user_id == user_id)
        )
        profile = result.scalar_one_or_none()
        if profile is None or not profile.name:
            return None

        # Serialised here, inside the session, deliberately.
        context = ChatContext(
            profile_id=profile.id,
            profile_name=profile.name,
            description_for_ai=serialize_profile_for_ai(profile),
            history=tuple(
                Turn(role=row["role"], text=row["text"])
                for row in await get_profile_history_from_db(session, user_id, profile_id)
            ),
        )

    return context


async def save_turn(user_id: int, profile_id: int, user_text: str, bot_text: str) -> None:
    """Persist one exchange in a single short transaction.

    Both rows go in, then the history is trimmed once. Trimming used to run
    inside each save, so one exchange cost two SELECTs and two DELETEs on top of
    the inserts.
    """
    async with AsyncORM.users._get_session() as session:
        await save_profile_message(session, user_id, profile_id, "user", user_text)
        await save_profile_message(session, user_id, profile_id, "bot", bot_text)
        await trim_profile_history(session, user_id, profile_id)
