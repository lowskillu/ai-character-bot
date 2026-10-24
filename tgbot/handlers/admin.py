import asyncio
import logging
from contextlib import suppress

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InaccessibleMessage, Message

from datetime import datetime, timedelta
from tgbot.database.models import User
from tgbot.database.orm import AsyncORM
from tgbot.filters.admin import AdminFilter
from tgbot.keyboards.inline import (
    admin_menu,
    back_admin,
    choose_menu,
)
from tgbot.misc.states import (
    BroadcastState,
)
from tgbot.services.broadcaster import broadcast
from tgbot.services.quotas import reset_user_quotas

admin_router = Router()
logger = logging.getLogger(__name__)
admin_router.message.filter(AdminFilter())
# The callback side was unguarded: any user could open the admin menu, press
# "broadcast" to put themselves into BroadcastState.BS1 — where AdminFilter then
# rejected their messages, leaving them permanently stuck — and reach
# agree_and_start, which broadcasts to the entire user table.
admin_router.callback_query.filter(AdminFilter())


@admin_router.callback_query(F.data == "back_admin")
@admin_router.message(Command("admin"))
async def admin_start(update: Message | CallbackQuery, state: FSMContext):
    if isinstance(update, Message):
        await update.answer("Admin-menu", reply_markup=admin_menu)
        return

    if update.message and not isinstance(update.message, InaccessibleMessage):
        await state.clear()
        await update.message.edit_text("Admin-menu", reply_markup=admin_menu)


# ======================================================================================================================
# Broadcast
@admin_router.callback_query(F.data == "broadcast")
async def broadcast_main(call: CallbackQuery, state: FSMContext):
    if not call.message or isinstance(call.message, InaccessibleMessage):
        await call.answer("Error!")
        return

    msg_to_edit = await call.message.edit_text(
        "<b>Send me a photo with a text to broadcast it\n└─❕Only text also works.</b>",
        reply_markup=back_admin,
    )
    await state.set_state(BroadcastState.BS1)
    await state.update_data(msg_to_edit=msg_to_edit.message_id)


@admin_router.message(BroadcastState.BS1, F.content_type.in_({"text", "photo"}))
async def receive_broadcast_data(message: Message, state: FSMContext):
    data = await state.get_data()
    msg_to_edit: int = data["msg_to_edit"]
    await message.delete()
    if message.photo:
        file_id = message.photo[-1].file_id
        await state.update_data(photo=file_id, text=message.caption)
        await asyncio.sleep(2)
        await message.bot.delete_message(message.chat.id, msg_to_edit)
        await message.answer_photo(
            photo=file_id,
            caption=f"{message.caption}\n\n"
            f"<b>Is everything correct? Start broadcast?</b>",
            reply_markup=choose_menu,
        )
        await state.set_state(BroadcastState.BS2)
        return
    else:
        if not message.text:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=msg_to_edit,
                text="There is no photo or text",
                reply_markup=choose_menu,
            )
            return

        await state.update_data(text=message.text)
        await message.bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=msg_to_edit,
            text=message.text + "\n\n<b>Is everything correct? Start broadcast?</b>",
            reply_markup=choose_menu,
        )
        await state.set_state(BroadcastState.BS2)
        return


@admin_router.callback_query(BroadcastState.BS2, F.data == "yes")
async def agree_and_start(call: CallbackQuery, state: FSMContext, bot):
    if not call.message or isinstance(call.message, InaccessibleMessage):
        await call.answer("Something went wrong!")
        return

    data = await state.get_data()
    text, photo_name, silent_mode = (
        data.get("text"),
        data.get("photo"),
        data.get("silent_mode"),
    )
    await state.clear()
    await call.message.delete()
    to_delete: Message = await call.message.answer("<b>Broadcast started</b>")
    # Streamed in keyset-paginated batches rather than `get_all()` with no
    # limit, which materialised the whole user table before sending anything.
    #
    # A broadcast to a large table runs for minutes and reads the user table as
    # it goes, so a database hiccup part-way through is a real possibility.
    # Without this the admin would be left staring at "Broadcast started"
    # forever, unable to tell whether it finished, stalled, or how far it got.
    failed: Exception | None = None
    try:
        done = await broadcast(
            bot,
            AsyncORM.users.iter_all(),
            text,
            photo_name,
            disable_notification=silent_mode,
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("Broadcast aborted: %s", e)
        done, failed = 0, e

    with suppress(Exception):
        await to_delete.delete()

    if failed is not None:
        await call.message.answer(
            f"<b>Broadcast failed</b>\n<code>{type(failed).__name__}</code>\n"
            "Some users may already have received it.",
            reply_markup=back_admin,
        )
        return

    await call.message.answer(
        f"<b>Broadcast done</b>\nReceived the message: <code>{done}</code>\n",
        reply_markup=back_admin,
    )


@admin_router.message(Command("free"))
async def admin_set_free(message: Message, redis=None):
    user_id = message.from_user.id
    async with AsyncORM.users._get_session() as session:
        user_obj = await session.get(User, user_id)
        if user_obj:
            user_obj.premium_level = 0
            user_obj.premium_until = None
            await session.commit()

    if redis:
        await reset_user_quotas(redis, user_id)

    await message.answer(
        "🔴 <b>Account switched to FREE</b>\n"
        "└─ All message and picture counters have been reset!"
    )


@admin_router.message(Command("prem"))
async def admin_set_prem(message: Message, redis=None):
    user_id = message.from_user.id
    async with AsyncORM.users._get_session() as session:
        user_obj = await session.get(User, user_id)
        if user_obj:
            user_obj.premium_level = 1
            user_obj.premium_until = datetime.utcnow() + timedelta(days=365)
            await session.commit()

    if redis:
        await reset_user_quotas(redis, user_id)

    await message.answer(
        "🟢 <b>Account switched to PREMIUM</b>\n"
        "└─ All message and picture counters have been reset!"
    )
