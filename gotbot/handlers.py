"""Telegram commands. Blocking S3 operations run outside the event loop."""

import asyncio
import logging

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from gotbot.memes import EmptyMemeLibrary, MemeStorageError


logger = logging.getLogger(__name__)
HELP_TEXT = (
    "/start - Meet GotBot\n"
    "/help - Show available commands\n"
    "/gotmeme - Get a random Game of Thrones meme\n"
    "/comment <message> - Send feedback to the maintainer\n\n"
    "Works in private chats and groups. In a group, you can use /gotmeme@YourBotName."
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message:
        await update.effective_message.reply_text(
            "Winter is coming. So are the memes!\n"
            "I'm GotBot, your Game of Thrones meme companion.\n\n"
            "Use /gotmeme for a random meme or /help for all commands."
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message:
        await update.effective_message.reply_text(HELP_TEXT)


async def gotmeme(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return
    try:
        meme = await asyncio.to_thread(context.bot_data["memes"].random_meme)
    except EmptyMemeLibrary:
        await message.reply_text("The meme library is empty for now. Please come back later!")
        return
    except MemeStorageError:
        logger.warning("Meme storage unavailable")
        await message.reply_text("The ravens couldn't fetch a meme. Please try again shortly.")
        return
    await message.reply_photo(photo=meme.content, filename=meme.filename)


async def comment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return
    text = " ".join(context.args or []).strip()
    if not text:
        await message.reply_text("Use /comment <message> to send feedback to the maintainer.")
        return
    # Leave room for the sender information within Telegram's message limit.
    if len(text.encode("utf-16-le")) // 2 > 3000:
        await message.reply_text("Your feedback is too long. Please use at most 3,000 characters.")
        return
    developer_id = context.bot_data["settings"].developer_chat_id
    if developer_id is None:
        await message.reply_text("Feedback is not configured for this bot. Please contact its maintainer.")
        return
    user = update.effective_user
    if user is None:
        sender = "Anonymous sender"
    elif user.username:
        sender = f"@{user.username} (ID {user.id})"
    else:
        sender = f"{user.full_name} (ID {user.id})"
    try:
        await context.bot.send_message(
            chat_id=developer_id,
            text=f"New GotBot feedback\nFrom: {sender}\n\n{text}",
        )
    except TelegramError:
        logger.warning("Feedback delivery failed")
        await message.reply_text("Your feedback couldn't be delivered. Please try again later.")
        return
    await message.reply_text("Thanks! Your feedback has been sent to the maintainer.")


async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return
    command = (message.text or "").split(maxsplit=1)
    mention = command[0].partition("@")[2] if command else ""
    if mention and mention.lower() != context.bot.username.lower():
        return
    await message.reply_text("Unknown command. Use /help to see what I can do.")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Exception text and update payloads may include tokens, URLs or private messages.
    logger.error("Update processing failed (%s)", type(context.error).__name__)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text("Something went wrong. Please try again later.")
        except TelegramError:
            logger.warning("Unable to send the error notification")
