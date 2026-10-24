import asyncio
import logging
from typing import AsyncIterable, Iterable, Optional, Union

from aiogram import Bot
from aiogram import exceptions
from aiogram.types import InlineKeyboardMarkup

from tgbot.database.models import User

# Telegram caps bulk sending at roughly 30 messages/second. Staying just under
# it is what keeps TelegramRetryAfter rare; going faster only converts into
# flood-wait sleeps, so there is nothing to gain.
SEND_INTERVAL = 0.05


async def send_message(
    bot: Bot,
    user_id: Union[int, str],
    text: str,
    disable_notification: bool = False,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
) -> bool:
    """
    Safe messages sender

    :param bot: Bot instance.
    :param user_id: user id. If str - must contain only digits.
    :param text: text of the message.
    :param disable_notification: disable notification or not.
    :param reply_markup: reply markup.
    :return: success.
    """
    try:
        await bot.send_message(
            user_id,
            text,
            disable_notification=disable_notification,
            reply_markup=reply_markup,
        )
    except exceptions.TelegramBadRequest as e:
        logging.error("Target [ID:%s]: Bad Request: %s", user_id, e)
    except exceptions.TelegramForbiddenError:
        logging.error(f"Target [ID:{user_id}]: got TelegramForbiddenError")
    except exceptions.TelegramRetryAfter as e:
        logging.error(
            f"Target [ID:{user_id}]: Flood limit is exceeded. Sleep {e.retry_after} seconds."
        )
        await asyncio.sleep(e.retry_after)
        return await send_message(
            bot, user_id, text, disable_notification, reply_markup
        )  # Recursive call
    except exceptions.TelegramAPIError:
        logging.exception(f"Target [ID:{user_id}]: failed")
    else:
        logging.info(f"Target [ID:{user_id}]: success")
        return True
    return False


def _user_id(user: Union[User, int, dict]) -> Optional[int]:
    if isinstance(user, int):
        return user
    if isinstance(user, dict):
        return user.get("id")
    return getattr(user, "id", None)


async def broadcast(
    bot: Bot,
    users: Union[Iterable[Union[User, int, dict]], AsyncIterable[Union[User, int, dict]]],
    text: Optional[str] = "",
    photo_id: Optional[str] = None,
    disable_notification: bool = False,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
) -> int:
    """Send to every user, returning how many actually received it.

    Accepts an async iterable so the caller can stream the user table instead of
    materialising it: the admin broadcast used to load every row into memory
    before sending the first message.
    """
    count = 0

    async def _send_photo(user_id: int) -> bool:
        """Deliver the photo, waiting out one flood limit. True on success.

        The retry matters: the text path has always retried after a flood wait
        (send_message recurses), so without it a rate-limited photo broadcast
        silently skipped everyone it hit the limit on while a text broadcast of
        the same size reached everybody.
        """
        for attempt in (1, 2):
            try:
                await bot.send_photo(
                    user_id,
                    photo=photo_id,
                    caption=text or "",
                    disable_notification=disable_notification,
                    reply_markup=reply_markup,
                )
                return True
            except exceptions.TelegramRetryAfter as e:
                # Photos went through a bare `except: pass`, so a flood wait was
                # indistinguishable from a blocked user and the rest of the run
                # kept hammering the same limit.
                logging.warning("Broadcast flood limit: sleeping %ss", e.retry_after)
                await asyncio.sleep(e.retry_after)
                if attempt == 2:
                    logging.error("Target [ID:%s]: still rate limited, skipping", user_id)
            except Exception as e:  # noqa: BLE001 — one bad recipient must not stop the run
                logging.debug("Broadcast to %s failed: %s", user_id, e)
                return False
        return False

    async def _send_one(user) -> None:
        nonlocal count
        user_id = _user_id(user)
        if user_id is None:
            return  # skip unknown type
        if photo_id:
            delivered = await _send_photo(user_id)
        else:
            delivered = await send_message(
                bot, user_id, text or "", disable_notification, reply_markup
            )
        if delivered:
            count += 1

    try:
        if isinstance(users, AsyncIterable):
            async for user in users:
                await _send_one(user)
                await asyncio.sleep(SEND_INTERVAL)
        else:
            for user in users:
                await _send_one(user)
                await asyncio.sleep(SEND_INTERVAL)
    finally:
        logging.info(f"BROADCAST: {count} messages successful sent.")

    return count
