import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from decouple import AutoConfig

from gotbot.config import ConfigurationError, load_settings


class SettingsTests(unittest.TestCase):
    def load(self, **overrides):
        values = {"TELEGRAM_TOKEN": "123456:test-token", "AWS_STORAGE_BUCKET_NAME": "memes"}
        values.update(overrides)
        return load_settings(lambda name, default="": values.get(name, default))

    def test_defaults(self):
        settings = self.load()
        self.assertEqual(settings.bot_mode, "polling")
        self.assertEqual(settings.aws_region, "eu-central-1")
        self.assertEqual(settings.cache_ttl, 300)
        self.assertIsNone(settings.developer_chat_id)

    def test_required_settings(self):
        for name in ("TELEGRAM_TOKEN", "AWS_STORAGE_BUCKET_NAME"):
            with self.subTest(name=name), self.assertRaises(ConfigurationError):
                self.load(**{name: " "})

    def test_invalid_settings(self):
        invalid = {
            "BOT_MODE": ["unknown"],
            "MEME_CACHE_TTL": ["0", "-1", "abc", "86401"],
            "PORT": ["0", "65536", "abc"],
            "DEVELOPER_CHAT_ID": ["username", "0"],
            "LOG_LEVEL": ["verbose"],
        }
        for name, values in invalid.items():
            for value in values:
                with self.subTest(name=name, value=value), self.assertRaises(ConfigurationError):
                    self.load(**{name: value})

    def test_feedback_group_and_prefix(self):
        settings = self.load(DEVELOPER_CHAT_ID="-100123", MEME_PREFIX="got/", MEME_CACHE_TTL="60")
        self.assertEqual(settings.developer_chat_id, -100123)
        self.assertEqual(settings.meme_prefix, "got/")
        self.assertEqual(settings.cache_ttl, 60)

    def test_webhook_configuration(self):
        settings = self.load(
            BOT_MODE="webhook", WEBHOOK_URL="https://bot.example.com/base/",
            WEBHOOK_SECRET="a-secret_123", PORT="9000",
        )
        self.assertEqual(settings.webhook_url, "https://bot.example.com/base")
        self.assertEqual(settings.port, 9000)

    def test_invalid_webhook_urls(self):
        for url in (
            "", "http://example.com", "https://", "https://user:password@example.com",
            "https://example.com?token=secret", "https://example.com#part",
            "https://example.com:99999", "https://example.com:1234", "https://[invalid",
        ):
            with self.subTest(url=url), self.assertRaises(ConfigurationError):
                self.load(BOT_MODE="webhook", WEBHOOK_URL=url, WEBHOOK_SECRET="secret")

    def test_webhook_requires_valid_secret(self):
        for secret in ("", "spaces are invalid", "a" * 257):
            with self.subTest(secret=secret), self.assertRaises(ConfigurationError):
                self.load(BOT_MODE="webhook", WEBHOOK_URL="https://example.com", WEBHOOK_SECRET=secret)

    def test_explicit_aws_credentials_are_optional_but_must_be_complete(self):
        for partial in (
            {"AWS_ACCESS_KEY_ID": "access"}, {"AWS_SECRET_ACCESS_KEY": "secret"},
            {"AWS_SESSION_TOKEN": "session"},
        ):
            with self.subTest(partial=partial), self.assertRaises(ConfigurationError):
                self.load(**partial)
        settings = self.load(AWS_ACCESS_KEY_ID="access", AWS_SECRET_ACCESS_KEY="secret", AWS_SESSION_TOKEN="session")
        self.assertEqual(settings.aws_session_token, "session")

    def test_settings_repr_omits_secrets(self):
        settings = self.load(AWS_ACCESS_KEY_ID="private-access", AWS_SECRET_ACCESS_KEY="private-secret")
        self.assertNotIn(settings.telegram_token, repr(settings))
        self.assertNotIn("private-access", repr(settings))
        self.assertNotIn("private-secret", repr(settings))

    def test_environment_overrides_dotenv(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, ".env").write_text(
                "TELEGRAM_TOKEN=123456:from-file\nAWS_STORAGE_BUCKET_NAME=file-bucket\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"AWS_STORAGE_BUCKET_NAME": "env-bucket"}, clear=True):
                settings = load_settings(AutoConfig(search_path=directory))
        self.assertEqual(settings.bucket_name, "env-bucket")
        self.assertEqual(settings.telegram_token, "123456:from-file")
