from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from telegram import Update
from telegram.error import BadRequest, Forbidden

from gotbot.config import Settings
from gotbot.handlers import comment, error_handler, gotmeme, help_command, start, unknown
from gotbot.memes import EmptyMemeLibrary, Meme, MemeStorageError


class HandlerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.message = SimpleNamespace(text="/unknown", reply_text=AsyncMock(), reply_photo=AsyncMock())
        self.update = Mock(spec=Update)
        self.update.effective_message = self.message
        self.update.effective_user = SimpleNamespace(id=42, username="jon", full_name="Jon Snow")
        self.repository = Mock()
        self.repository.random_meme.return_value = Meme("jon.jpg", b"photo")
        self.context = SimpleNamespace(
            args=[],
            bot=SimpleNamespace(send_message=AsyncMock()),
            bot_data={
                "memes": self.repository,
                "settings": Settings("123456:test-token", "bucket", developer_chat_id=99),
            },
            error=None,
        )

    async def test_start_help_and_unknown(self):
        for handler, expected in ((start, "Winter"), (help_command, "/gotmeme"), (unknown, "/help")):
            with self.subTest(handler=handler.__name__):
                self.message.reply_text.reset_mock()
                await handler(self.update, self.context)
                self.assertIn(expected, self.message.reply_text.await_args.args[0])

    async def test_meme_is_uploaded(self):
        await gotmeme(self.update, self.context)
        self.message.reply_photo.assert_awaited_once_with(photo=b"photo", filename="jon.jpg")

    async def test_empty_or_unavailable_library(self):
        for error, expected in ((EmptyMemeLibrary(), "empty"), (MemeStorageError(), "try again")):
            with self.subTest(error=type(error).__name__):
                self.message.reply_text.reset_mock()
                self.repository.random_meme.side_effect = error
                await gotmeme(self.update, self.context)
                self.assertIn(expected, self.message.reply_text.await_args.args[0])
                self.message.reply_photo.assert_not_awaited()

    async def test_feedback_sent_before_acknowledgement(self):
        self.context.args = ["Great", "memes!"]

        async def send_message(**kwargs):
            self.message.reply_text.assert_not_awaited()

        self.context.bot.send_message.side_effect = send_message
        await comment(self.update, self.context)
        delivery = self.context.bot.send_message.await_args.kwargs
        self.assertEqual(delivery["chat_id"], 99)
        self.assertIn("@jon (ID 42)", delivery["text"])
        self.assertIn("Great memes!", delivery["text"])
        self.assertIn("Thanks", self.message.reply_text.await_args.args[0])

    async def test_feedback_without_username(self):
        self.update.effective_user.username = None
        self.context.args = ["Hello"]
        await comment(self.update, self.context)
        self.assertIn("Jon Snow (ID 42)", self.context.bot.send_message.await_args.kwargs["text"])

    async def test_feedback_without_user(self):
        self.update.effective_user = None
        self.context.args = ["Hello"]
        await comment(self.update, self.context)
        self.assertIn("Anonymous sender", self.context.bot.send_message.await_args.kwargs["text"])

    async def test_feedback_requires_text_and_respects_telegram_length(self):
        for args in ([], [" "], ["x" * 3001], ["\U0001f600" * 1501]):
            with self.subTest(length=sum(map(len, args))):
                self.context.args = args
                await comment(self.update, self.context)
                self.context.bot.send_message.assert_not_awaited()

    async def test_feedback_can_be_disabled(self):
        self.context.bot_data["settings"] = Settings("123456:test-token", "bucket")
        self.context.args = ["Hello"]
        await comment(self.update, self.context)
        self.context.bot.send_message.assert_not_awaited()
        self.assertIn("not configured", self.message.reply_text.await_args.args[0])

    async def test_feedback_delivery_failure_is_not_acknowledged_as_success(self):
        self.context.args = ["Hello"]
        self.context.bot.send_message.side_effect = Forbidden("not allowed")
        await comment(self.update, self.context)
        self.assertIn("couldn't be delivered", self.message.reply_text.await_args.args[0])

    async def test_updates_without_message_are_ignored(self):
        self.update.effective_message = None
        for handler in (start, help_command, gotmeme, comment, unknown):
            await handler(self.update, self.context)
        self.repository.random_meme.assert_not_called()
        self.context.bot.send_message.assert_not_awaited()

    async def test_error_logs_exclude_exception_payload(self):
        self.context.error = BadRequest("sensitive-token-and-user-content")
        with self.assertLogs("gotbot.handlers", level="ERROR") as logs:
            await error_handler(self.update, self.context)
        self.assertIn("BadRequest", logs.output[0])
        self.assertNotIn("sensitive-token-and-user-content", logs.output[0])
        self.message.reply_text.assert_awaited_once()

    async def test_error_notification_failure_does_not_escape(self):
        self.context.error = BadRequest("failure")
        self.message.reply_text.side_effect = Forbidden("blocked")
        await error_handler(self.update, self.context)

    async def test_background_error_has_no_update_to_reply_to(self):
        self.context.error = BadRequest("failure")
        await error_handler(None, self.context)
        self.message.reply_text.assert_not_awaited()
