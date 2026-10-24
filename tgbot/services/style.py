import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from tgbot.database.models import User
from sqlalchemy.exc import SQLAlchemyError
import asyncio

logger = logging.getLogger(__name__)

DEFAULT_STYLE = "anime"

async def get_user_style(session: AsyncSession, user_id: int) -> str:
    try:
        stmt = select(User.style).where(User.id == user_id)
        result = await asyncio.wait_for(session.execute(stmt), timeout=2)
        style = result.scalar_one_or_none()
        return style or DEFAULT_STYLE
    except Exception as e:
        logger.error(f"Failed to get style for user {user_id}: {e}")
        return DEFAULT_STYLE

async def set_user_style(session: AsyncSession, user_id: int, style: str) -> bool:
    retries = 2
    for attempt in range(retries + 1):
        try:
            stmt = update(User).where(User.id == user_id).values(style=style)
            await asyncio.wait_for(session.execute(stmt), timeout=2)
            return True
        except (SQLAlchemyError, asyncio.TimeoutError) as e:
            logger.warning(f"Attempt {attempt+1}: Failed to set style for user {user_id}: {e}")
            await asyncio.sleep(0.2)
        except Exception as e:
            logger.error(f"Unexpected error setting style for user {user_id}: {e}")
            return False
    return False 