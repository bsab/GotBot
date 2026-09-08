"""Environment configuration, loaded only when the application starts."""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
import re
from urllib.parse import urlsplit

from decouple import AutoConfig


class ConfigurationError(ValueError):
    """A required setting is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    telegram_token: str = field(repr=False)
    bucket_name: str
    aws_access_key_id: str = field(default="", repr=False)
    aws_secret_access_key: str = field(default="", repr=False)
    aws_session_token: str = field(default="", repr=False)
    aws_region: str = "eu-central-1"
    meme_prefix: str = ""
    cache_ttl: int = 300
    developer_chat_id: int | None = None
    bot_mode: str = "polling"
    webhook_url: str = ""
    webhook_secret: str = field(default="", repr=False)
    port: int = 8080
    log_level: str = "INFO"


def load_settings(reader: Callable[..., str] | None = None) -> Settings:
    if reader is None:
        reader = AutoConfig(search_path=str(Path(__file__).resolve().parent.parent))

    def text(name: str, default: str = "") -> str:
        return reader(name, default=default).strip()

    def integer(name: str, default: str, minimum: int, maximum: int) -> int:
        try:
            value = int(text(name, default))
        except ValueError:
            raise ConfigurationError(f"{name} must be an integer.") from None
        if not minimum <= value <= maximum:
            raise ConfigurationError(f"{name} must be between {minimum} and {maximum}.")
        return value

    token = text("TELEGRAM_TOKEN")
    bucket = text("AWS_STORAGE_BUCKET_NAME")
    if not token or not bucket:
        raise ConfigurationError("TELEGRAM_TOKEN and AWS_STORAGE_BUCKET_NAME are required.")

    access_key = text("AWS_ACCESS_KEY_ID")
    secret_key = text("AWS_SECRET_ACCESS_KEY")
    session_token = text("AWS_SESSION_TOKEN")
    if bool(access_key) != bool(secret_key) or (session_token and not access_key):
        raise ConfigurationError("Set both AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY, or use the AWS credential chain.")

    mode = text("BOT_MODE", "polling").lower()
    if mode not in {"polling", "webhook"}:
        raise ConfigurationError("BOT_MODE must be polling or webhook.")

    webhook_url = text("WEBHOOK_URL").rstrip("/")
    secret = text("WEBHOOK_SECRET")
    if mode == "webhook":
        try:
            parsed = urlsplit(webhook_url)
            valid_url = (
                parsed.scheme == "https" and parsed.hostname and parsed.port in {None, 443, 80, 88, 8443}
                and not parsed.username and not parsed.password
                and not parsed.query and not parsed.fragment
            )
        except ValueError:
            valid_url = False
        if not valid_url:
            raise ConfigurationError("WEBHOOK_URL must be a public HTTPS base URL without credentials, query or fragment.")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", secret):
            raise ConfigurationError("WEBHOOK_SECRET must contain 1-256 letters, digits, underscores or hyphens.")

    developer_id = text("DEVELOPER_CHAT_ID")
    try:
        developer_chat_id = int(developer_id) if developer_id else None
    except ValueError:
        raise ConfigurationError("DEVELOPER_CHAT_ID must be an integer.") from None
    if developer_chat_id == 0:
        raise ConfigurationError("DEVELOPER_CHAT_ID must not be zero.")

    level = text("LOG_LEVEL", "INFO").upper()
    if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ConfigurationError("LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR or CRITICAL.")

    return Settings(
        telegram_token=token,
        bucket_name=bucket,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        aws_session_token=session_token,
        aws_region=text("AWS_REGION", "eu-central-1") or "eu-central-1",
        meme_prefix=text("MEME_PREFIX"),
        cache_ttl=integer("MEME_CACHE_TTL", "300", 1, 86400),
        developer_chat_id=developer_chat_id,
        bot_mode=mode,
        webhook_url=webhook_url,
        webhook_secret=secret,
        port=integer("PORT", "8080", 1, 65535),
        log_level=level,
    )
