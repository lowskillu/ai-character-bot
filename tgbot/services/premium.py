"""Premium tier: the one place that decides whether a grant is still valid.

There were three different answers to "is this user premium" in the tree:

* ``services/profile.is_premium()`` compared ``premium_until`` to now — correct;
* ``middlewares/database`` carried its own copy of that comparison;
* ``handlers/photo.py``, ``handlers/menu.py`` and ``handlers/customization.py``
  read ``user.premium_level`` raw and never looked at the expiry at all.

The third group is the one that mattered: an expired subscriber kept the 50
photos/day quota instead of dropping to the free tier, kept four profile slots,
and was shown "✅ Активен до <дата в прошлом>" on the stats screen.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tgbot.database.models import User

logger = logging.getLogger(__name__)


def effective_level(user: Optional[User]) -> int:
    """Premium level with the expiry already applied; 0 when not premium.

    A NULL ``premium_until`` means a grant with no end date, not an expired one.
    """
    if user is None:
        return 0
    level = getattr(user, "premium_level", 0) or 0
    if level < 1:
        return 0
    until = getattr(user, "premium_until", None)
    if until is not None and until <= datetime.utcnow():
        return 0
    return level


def is_active(user: Optional[User]) -> bool:
    return effective_level(user) >= 1


class AmbiguousUsername(Exception):
    """More than one row carries this username.

    Reachable by design: the UNIQUE constraint on users.username was dropped
    because Telegram frees usernames and hands them to other people, and a
    dormant account keeps whatever @name it had when it last spoke. So two rows
    genuinely can share one.
    """

    def __init__(self, username: str, user_ids: list[int]):
        super().__init__(f"{username} matches {len(user_ids)} users: {user_ids}")
        self.username = username
        self.user_ids = user_ids


async def resolve_user(session: AsyncSession, identifier: str) -> Optional[User]:
    """Find a user by numeric id or by @username.

    Numeric ids are accepted so an admin has a way through when a username is
    ambiguous — otherwise that user simply could not be granted anything.
    """
    identifier = identifier.strip().lstrip("@")
    if identifier.isdigit():
        return await session.get(User, int(identifier))

    rows = list(
        (await session.execute(select(User).where(User.username == identifier)))
        .scalars()
        .all()
    )
    if len(rows) > 1:
        raise AmbiguousUsername(identifier, [u.id for u in rows])
    return rows[0] if rows else None


async def grant_premium(
    session: AsyncSession, identifier: str, level: int, days: int
) -> Optional[User]:
    """Grant premium by id or @username. Returns the user, or None if not found.

    Was ``scalar_one_or_none()``, which raises MultipleResultsFound on a shared
    username — swallowed by a blanket except and reported to the admin as a
    generic "не удалось", with no hint that the name was the problem.

    Raises :class:`AmbiguousUsername` so the caller can say which ids collided.
    """
    user = await resolve_user(session, identifier)
    if user is None:
        logger.error("Пользователь %s не найден", identifier)
        return None

    user.premium_level = level
    user.premium_until = datetime.utcnow() + timedelta(days=days)
    await session.flush()
    logger.info("Премиум %s выдан %s (id=%s) до %s", level, identifier, user.id, user.premium_until)
    return user
