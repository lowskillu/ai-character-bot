"""Per-profile conversation history in Postgres.

Only the last :data:`HISTORY_LIMIT` turns are kept; the rest are trimmed as new
ones arrive.
"""

from datetime import datetime, timedelta

from sqlalchemy import delete, desc, select

from tgbot.database.models import ProfileMessageHistory

# How many rows survive per (user, profile). The composite index
# ix_pmh_user_profile_created is what makes both the read and the trim cheap.
HISTORY_LIMIT = 10

# Rows older than this are dropped wholesale by delete_old_profile_messages.
RETENTION_DAYS = 45


async def get_profile_history(state, profile_id: int) -> list:
    data = await state.get_data()
    return data.get(f"chat_history_{profile_id}", [])


async def set_profile_history(state, profile_id: int, history: list):
    last_dt = datetime.utcnow().isoformat() if history else None
    await state.update_data(
        **{f"chat_history_{profile_id}": history, f"chat_history_{profile_id}_last": last_dt}
    )


# --- history in the database ---

async def save_profile_message(session, user_id: int, profile_id: int, role: str, text: str):
    """Append one row. Trimming is a separate call — see :func:`trim_profile_history`.

    An explicit ``created_at`` rather than the column's server default: in
    Postgres ``now()`` is the *transaction* timestamp, so a user turn and the
    bot turn saved in one transaction would share a timestamp and the ORDER BY
    that reads them back could return them in either order.
    """
    session.add(
        ProfileMessageHistory(
            user_id=user_id,
            profile_id=profile_id,
            role=role,
            text=text,
            created_at=datetime.utcnow(),
        )
    )
    await session.flush()


async def trim_profile_history(
    session, user_id: int, profile_id: int, keep: int = HISTORY_LIMIT
) -> None:
    """Drop everything but the newest ``keep`` rows for this profile.

    One statement. This used to be a SELECT of the ids to drop followed by a
    DELETE against that list, and it ran once per saved row — so persisting a
    single exchange cost six round trips on the hot path instead of three.
    """
    newest = (
        select(ProfileMessageHistory.id)
        .where(
            ProfileMessageHistory.user_id == user_id,
            ProfileMessageHistory.profile_id == profile_id,
        )
        .order_by(desc(ProfileMessageHistory.created_at))
        .limit(keep)
        .scalar_subquery()
    )
    await session.execute(
        delete(ProfileMessageHistory).where(
            ProfileMessageHistory.user_id == user_id,
            ProfileMessageHistory.profile_id == profile_id,
            ProfileMessageHistory.id.not_in(newest),
        )
    )


async def get_profile_history_from_db(session, user_id: int, profile_id: int, limit: int = HISTORY_LIMIT) -> list:
    q = (
        select(ProfileMessageHistory.role, ProfileMessageHistory.text)
        .where(
            ProfileMessageHistory.user_id == user_id,
            ProfileMessageHistory.profile_id == profile_id,
        )
        .order_by(desc(ProfileMessageHistory.created_at))
        .limit(limit)
    )
    result = await session.execute(q)
    rows = result.all()
    # Oldest first
    return [{"role": r, "text": t} for r, t in reversed(rows)]


async def delete_old_profile_messages(session):
    """Delete history rows older than RETENTION_DAYS."""
    threshold = datetime.utcnow() - timedelta(days=RETENTION_DAYS)
    await session.execute(
        delete(ProfileMessageHistory).where(ProfileMessageHistory.created_at < threshold)
    )
