"""Admin access control, tested through the dispatcher.

AdminFilter used to be attached to ``admin_router.message`` only. Every
callback_query handler was therefore open to anyone: a non-admin could open the
admin menu, press "broadcast" to put themselves into BroadcastState.BS1 — where
AdminFilter then rejected their follow-up messages, stranding them — and reach
agree_and_start, which broadcasts to the entire user table.

Asserted behaviourally rather than by inspecting aiogram's filter internals,
which are private and change between versions.
"""

from datetime import datetime

import pytest
from aiogram import Bot, Dispatcher
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from tgbot.handlers.admin import admin_router

ADMIN_ID = 1111
STRANGER_ID = 2222

FAKE_TOKEN = "42:AAHfiqksKZ8WmR2zSjiQ7_v4_Jmn2pTz1cM"


class _Config:
    """Just enough of the Config shape for AdminFilter."""

    class _TgBot:
        admin_ids = [ADMIN_ID]

    tg_bot = _TgBot()


@pytest.fixture(scope="module")
def bot():
    return Bot(token=FAKE_TOKEN)


@pytest.fixture(scope="module")
def dp():
    # Module-scoped: routers are module-level singletons and aiogram refuses to
    # attach one to a second Dispatcher.
    dispatcher = Dispatcher()
    dispatcher.include_router(admin_router)
    return dispatcher


def _callback(user_id: int, data: str) -> Update:
    user = User(id=user_id, is_bot=False, first_name="T")
    chat = Chat(id=user_id, type="private")
    message = Message(message_id=1, date=datetime.now(), chat=chat, from_user=user)
    return Update(
        update_id=1,
        callback_query=CallbackQuery(
            id="1",
            from_user=user,
            chat_instance="1",
            data=data,
            message=message,
        ),
    )


@pytest.mark.parametrize("data", ["broadcast", "back_admin"])
async def test_stranger_cannot_reach_admin_callbacks(dp, bot, data):
    result = await dp.feed_update(bot, _callback(STRANGER_ID, data), config=_Config())
    assert result is UNHANDLED, f"non-admin reached the {data!r} callback"


async def test_stranger_cannot_reach_admin_command(dp, bot):
    user = User(id=STRANGER_ID, is_bot=False, first_name="T")
    chat = Chat(id=STRANGER_ID, type="private")
    update = Update(
        update_id=2,
        message=Message(
            message_id=2, date=datetime.now(), chat=chat, from_user=user, text="/admin"
        ),
    )
    result = await dp.feed_update(bot, update, config=_Config())
    assert result is UNHANDLED
