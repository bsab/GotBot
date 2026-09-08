"""Application factory and polling/webhook entry point."""

import logging

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError
from telegram import BotCommand
from telegram.error import TelegramError
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from gotbot.config import ConfigurationError, Settings, load_settings
from gotbot.handlers import comment, error_handler, gotmeme, help_command, start, unknown
from gotbot.memes import S3MemeRepository


logger = logging.getLogger(__name__)


async def register_commands(application: Application) -> None:
    await application.bot.set_my_commands([
        BotCommand("start", "Meet GotBot"),
        BotCommand("help", "Show available commands"),
        BotCommand("gotmeme", "Get a random Game of Thrones meme"),
        BotCommand("comment", "Send feedback to the maintainer"),
    ])


async def close_storage(application: Application) -> None:
    application.bot_data["s3_client"].close()


def build_application(settings: Settings) -> Application:
    application = (
        Application.builder()
        .token(settings.telegram_token)
        .concurrent_updates(8)
        .post_init(register_commands)
        .post_shutdown(close_storage)
        .build()
    )
    client = boto3.client(
        "s3",
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id or None,
        aws_secret_access_key=settings.aws_secret_access_key or None,
        aws_session_token=settings.aws_session_token or None,
        config=Config(
            connect_timeout=5,
            read_timeout=15,
            retries={"mode": "standard", "total_max_attempts": 3},
        ),
    )
    application.bot_data.update(
        settings=settings,
        s3_client=client,
        memes=S3MemeRepository(client, settings.bucket_name, settings.meme_prefix, settings.cache_ttl),
    )
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("gotmeme", gotmeme))
    application.add_handler(CommandHandler("comment", comment))
    application.add_handler(MessageHandler(filters.COMMAND, unknown))
    application.add_error_handler(error_handler)
    return application


def main() -> None:
    logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
    try:
        settings = load_settings()
    except ConfigurationError as exc:
        logger.error("Invalid configuration: %s", exc)
        raise SystemExit(2) from None

    logging.getLogger("gotbot").setLevel(settings.log_level)
    # Network debug logs can expose Telegram tokens and AWS signing details.
    for name in ("httpx", "httpcore", "telegram", "boto3", "botocore", "urllib3", "tornado.access"):
        logging.getLogger(name).setLevel(logging.CRITICAL)

    try:
        application = build_application(settings)
        logger.info("Starting GotBot in %s mode", settings.bot_mode)
        if settings.bot_mode == "webhook":
            application.run_webhook(
                listen="0.0.0.0",
                port=settings.port,
                url_path="telegram",
                webhook_url=f"{settings.webhook_url}/telegram",
                secret_token=settings.webhook_secret,
                allowed_updates=["message"],
                bootstrap_retries=0,
            )
        else:
            application.run_polling(allowed_updates=["message"], bootstrap_retries=0)
    except (TelegramError, BotoCoreError) as exc:
        logger.error("Bot startup or shutdown failed (%s). Check connectivity and configuration.", type(exc).__name__)
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
