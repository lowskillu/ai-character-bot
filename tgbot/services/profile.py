import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from tgbot.database.models import Profile, User
from tgbot.services import premium
from typing import List, Optional

logger = logging.getLogger(__name__)

async def get_user_profiles(session: AsyncSession, user_id: int) -> List[Profile]:
    try:
        result = await session.execute(
            select(Profile).where(Profile.user_id == user_id)
        )
        return list(result.scalars().all())
    except Exception as e:
        logger.error(f"could not load profiles of user {user_id}: {e}")
        return []

async def is_premium(session: AsyncSession, user_id: int) -> bool:
    """True when the user currently holds an unexpired premium level.

    This used to read ``getattr(user, "is_premium", False)`` — a field the User
    model has never had — so it returned False for everybody and premium was
    silently dead: paying users were still capped at 2 profiles.

    The expiry rule itself lives in services/premium.py; four other call sites
    had each written their own version of it, and three of them were wrong.
    """
    try:
        result = await session.execute(
            select(User).where(User.id == user_id)
        )
        return premium.is_active(result.scalar_one_or_none())
    except Exception as e:
        logger.error(f"could not check premium of user {user_id}: {e}")
        return False

async def create_profile(
    session: AsyncSession,
    user_id: int,
    name: str,
    style: str,
    description: Optional[str] = None,
    appearance: Optional[str] = None,
    body_type: Optional[str] = None,
    clothing: Optional[str] = None,
    personality: Optional[str] = None,
    location: Optional[str] = None,
    role: Optional[str] = None,
    reference_photo_url: Optional[str] = None,
) -> Optional[Profile]:
    try:
        profile = Profile(
            user_id=user_id,
            name=name,
            style=style,
            description=description,
            appearance=appearance,
            body_type=body_type,
            clothing=clothing,
            personality=personality,
            location=location,
            role=role,
            reference_photo_url=reference_photo_url,
        )
        session.add(profile)
        await session.flush()  # Assigns profile.id
        return profile
    except Exception as e:
        logger.error(f"could not create a profile for user {user_id}: {e}")
        return None

async def update_profile(
    session: AsyncSession,
    user_id: int,
    profile_id: int,
    **fields,
) -> Optional[Profile]:
    """Update a profile in place, returning it (or None if it isn't this user's).

    The wizard used to "edit" by deleting the row and inserting a new one. Both
    profile_message_history foreign keys are ON DELETE CASCADE, so changing a
    character's outfit silently destroyed the entire conversation with it — and
    handed it a new id, orphaning anything that referenced the old one.

    The ``user_id`` predicate is what stops one user editing another's profile
    by guessing an id.
    """
    try:
        result = await session.execute(
            select(Profile).where(Profile.id == profile_id, Profile.user_id == user_id)
        )
        profile = result.scalar_one_or_none()
        if not profile:
            return None
        for key, value in fields.items():
            setattr(profile, key, value)
        await session.flush()
        return profile
    except Exception as e:
        logger.error(f"could not update profile {profile_id} of user {user_id}: {e}")
        return None


async def delete_profile(session: AsyncSession, user_id: int, profile_id: int) -> bool:
    try:
        result = await session.execute(
            select(Profile).where(Profile.id == profile_id, Profile.user_id == user_id)
        )
        profile = result.scalar_one_or_none()
        if not profile:
            return False
        await session.delete(profile)
        return True
    except Exception as e:
        logger.error(f"could not delete profile {profile_id} of user {user_id}: {e}")
        return False

async def delete_all_profiles_for_user(session: AsyncSession, user_id: int) -> None:
    """Delete every profile of a user."""
    from tgbot.database.models import Profile
    await session.execute(
        delete(Profile).where(Profile.user_id == user_id)
    )
    # No commit here: the caller owns the transaction

# get_profile_by_id() stood here unused, and it looked up a profile by id alone
# with no user_id predicate — the exact shape that would let one user read
# another's character by guessing an id. Callers that need a profile use
# load_chat_context or update_profile, both of which scope by user.

async def set_active_profile(redis, user_id: int, profile_id: int):
    """Store the active profile pointer in Redis."""
    try:
        await redis.set(f"active_profile:{user_id}", profile_id)
        logger.info(f"Set active profile for user {user_id}: {profile_id}")
    except Exception as e:
        logger.error(f"Failed to set active profile for user {user_id}: {e}")

async def get_active_profile(redis, user_id: int) -> Optional[int]:
    """Read the active profile pointer from Redis."""
    try:
        profile_id = await redis.get(f"active_profile:{user_id}")
        return int(profile_id) if profile_id else None
    except Exception as e:
        logger.error(f"Failed to get active profile for user {user_id}: {e}")
        return None 

# CHARACTER_NAMES_RU/EN lived here as a second, longer copy of the lists in
# misc/localization.py. Both were live: the name keyboard read this one, while
# handle_customize_random shadowed it with a local import of the other, so the
# two screens offered different pools. Localized data belongs in localization.py.