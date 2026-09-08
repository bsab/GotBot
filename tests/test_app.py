import asyncio
import http.client
from io import BytesIO
import json
import socket
import unittest
from unittest.mock import AsyncMock, Mock, patch

from telegram import Update
from telegram.error import InvalidToken
from telegram.ext import CommandHandler, MessageHandler
from telegram.request import HTTPXRequest

from gotbot.app import build_application, close_storage, main, register_commands
from gotbot.config import ConfigurationError, Settings


class ApplicationTests(unittest.TestCase):
    @patch("gotbot.app.boto3.client")
    def test_factory_registers_commands_without_network_requests(self, client):
        settings = Settings("123456:test-token", "bucket")
        application = build_application(settings)
        self.assertIs(application.bot_data["settings"], settings)
        self.assertEqual(application.concurrent_updates, 8)
        handlers = application.handlers[0]
        commands = [handler.commands for handler in handlers if isinstance(handler, CommandHandler)]
        self.assertEqual(commands, [frozenset([name]) for name in ("start", "help", "gotmeme", "comment")])
        self.assertIsInstance(handlers[-1], MessageHandler)
        self.assertEqual(len(application.error_handlers), 1)
        self.assertIs(application.post_init, register_commands)
        self.assertIs(application.post_shutdown, close_storage)
        client.return_value.get_paginator.assert_not_called()
        options = client.call_args.kwargs
        self.assertIsNone(options["aws_access_key_id"])
        self.assertEqual(options["config"].connect_timeout, 5)
        self.assertEqual(options["config"].retries["total_max_attempts"], 3)

    @patch("gotbot.app.boto3.client")
    def test_explicit_aws_credentials_are_passed_to_client(self, client):
        build_application(Settings(
            "123456:test-token", "bucket", aws_access_key_id="access",
            aws_secret_access_key="secret", aws_session_token="temporary",
        ))
        self.assertEqual(client.call_args.kwargs["aws_access_key_id"], "access")
        self.assertEqual(client.call_args.kwargs["aws_secret_access_key"], "secret")
        self.assertEqual(client.call_args.kwargs["aws_session_token"], "temporary")

    @patch("gotbot.app.build_application")
    @patch("gotbot.app.load_settings")
    def test_default_polling_startup(self, load, build):
        load.return_value = Settings("123456:test-token", "bucket")
        main()
        build.return_value.run_polling.assert_called_once_with(allowed_updates=["message"], bootstrap_retries=0)
        build.return_value.run_webhook.assert_not_called()

    @patch("gotbot.app.build_application")
    @patch("gotbot.app.load_settings")
    def test_webhook_startup_uses_secret_not_bot_token_in_path(self, load, build):
        load.return_value = Settings(
            "123456:test-token", "bucket", bot_mode="webhook",
            webhook_url="https://example.com", webhook_secret="webhook-secret", port=9000,
        )
        main()
        build.return_value.run_webhook.assert_called_once_with(
            listen="0.0.0.0", port=9000, url_path="telegram",
            webhook_url="https://example.com/telegram", secret_token="webhook-secret",
            allowed_updates=["message"], bootstrap_retries=0,
        )
        build.return_value.run_polling.assert_not_called()

    @patch("gotbot.app.build_application")
    @patch("gotbot.app.load_settings", side_effect=ConfigurationError("Missing settings"))
    def test_configuration_failure_exits_before_building(self, load, build):
        with self.assertRaises(SystemExit) as result:
            main()
        self.assertEqual(result.exception.code, 2)
        build.assert_not_called()

    @patch("gotbot.app.build_application", side_effect=InvalidToken("sensitive-token"))
    @patch("gotbot.app.load_settings")
    def test_startup_failure_does_not_log_token(self, load, build):
        load.return_value = Settings("123456:test-token", "bucket")
        with self.assertLogs("gotbot.app", level="ERROR") as logs, self.assertRaises(SystemExit) as result:
            main()
        self.assertEqual(result.exception.code, 2)
        self.assertNotIn("sensitive-token", " ".join(logs.output))


class DispatchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.calls = []

        async def fake_request(request, url, method, request_data=None, **kwargs):
            api_method = url.rsplit("/", 1)[-1]
            parameters = request_data.parameters if request_data else {}
            self.calls.append((api_method, parameters))
            if api_method == "getMe":
                result = {"id": 123456, "is_bot": True, "first_name": "GotBot", "username": "GotTestBot"}
            elif api_method in {"sendMessage", "sendPhoto"}:
                result = {
                    "message_id": 1, "date": 0,
                    "chat": {"id": int(parameters["chat_id"]), "type": "private"},
                }
            else:
                result = True
            return 200, json.dumps({"ok": True, "result": result}).encode()

        self.transport = patch.object(HTTPXRequest, "do_request", new=fake_request)
        self.transport.start()
        self.addCleanup(self.transport.stop)
        self.client = Mock()
        self.client.get_paginator.return_value.paginate.return_value = [
            {"Contents": [{"Key": "jon.jpg", "Size": 5}]},
        ]
        self.client.get_object.side_effect = lambda **kwargs: {"Body": BytesIO(b"photo")}
        with patch("gotbot.app.boto3.client", return_value=self.client):
            self.application = build_application(Settings("123456:test-token", "bucket", developer_chat_id=99))
        await self.application.initialize()
        self.application.add_error_handler(AsyncMock())

    async def asyncTearDown(self):
        await self.application.shutdown()
        await close_storage(self.application)
        self.client.close.assert_called_once()

    async def dispatch(self, text, group=False):
        command = text.split()[0]
        update = Update.de_json({
            "update_id": 1,
            "message": {
                "message_id": 1, "date": 0,
                "chat": {"id": -123 if group else 42, "type": "group" if group else "private"},
                "from": {"id": 42, "is_bot": False, "first_name": "Jon"},
                "text": text,
                "entities": [{"type": "bot_command", "offset": 0, "length": len(command)}],
            },
        }, self.application.bot)
        await self.application.process_update(update)

    async def test_legacy_mixed_case_command_and_group_mention(self):
        for command in ("/gotmeme", "/GoTMeme", "/GoTMeme@GotTestBot"):
            with self.subTest(command=command):
                await self.dispatch(command, group=True)
        photos = [params for method, params in self.calls if method == "sendPhoto"]
        self.assertEqual(len(photos), 3)
        self.assertTrue(all(params["chat_id"] == -123 for params in photos))

    async def test_legacy_comment_command_without_username(self):
        await self.dispatch("/Comment Excellent memes")
        messages = [params for method, params in self.calls if method == "sendMessage"]
        self.assertEqual([params["chat_id"] for params in messages], [99, 42])
        self.assertIn("Jon (ID 42)", messages[0]["text"])
        self.assertIn("Excellent memes", messages[0]["text"])

    async def test_start_help_and_unknown_are_dispatched(self):
        for command in ("/start", "/help", "/notacommand"):
            await self.dispatch(command)
        messages = [params["text"] for method, params in self.calls if method == "sendMessage"]
        self.assertEqual(len(messages), 3)
        self.assertIn("Winter", messages[0])
        self.assertIn("/gotmeme", messages[1])
        self.assertIn("Unknown command", messages[2])

    async def test_commands_addressed_to_other_bots_are_ignored(self):
        await self.dispatch("/gotmeme@SomeOtherBot", group=True)
        await self.dispatch("/unknown@SomeOtherBot", group=True)
        self.assertFalse(any(method in {"sendMessage", "sendPhoto"} for method, _ in self.calls))

    async def test_plain_text_is_ignored(self):
        update = Update.de_json({
            "update_id": 2,
            "message": {
                "message_id": 2, "date": 0,
                "chat": {"id": 42, "type": "private"}, "text": "Hello!",
            },
        }, self.application.bot)
        await self.application.process_update(update)
        self.assertFalse(any(method == "sendMessage" for method, _ in self.calls))

    async def test_local_webhook_rejects_invalid_secrets_and_accepts_valid_updates(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        updater = self.application.updater
        await updater.start_webhook(
            listen="127.0.0.1", port=port, url_path="telegram",
            webhook_url="https://example.com/telegram", secret_token="test-secret",
            allowed_updates=["message"], bootstrap_retries=0,
        )

        def post(secret):
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            try:
                headers = {"Content-Type": "application/json"}
                if secret is not None:
                    headers["X-Telegram-Bot-Api-Secret-Token"] = secret
                connection.request("POST", "/telegram", body=json.dumps({"update_id": 123}), headers=headers)
                response = connection.getresponse()
                response.read()
                return response.status
            finally:
                connection.close()

        try:
            for secret in (None, "wrong-secret"):
                self.assertEqual(await asyncio.to_thread(post, secret), 403)
                self.assertTrue(self.application.update_queue.empty())
            self.assertEqual(await asyncio.to_thread(post, "test-secret"), 200)
            update = self.application.update_queue.get_nowait()
            self.assertEqual(update.update_id, 123)
            self.application.update_queue.task_done()
        finally:
            await updater.stop()

    async def test_menu_is_registered(self):
        await register_commands(self.application)
        menus = [params for method, params in self.calls if method == "setMyCommands"]
        self.assertEqual(len(menus), 1)
        self.assertEqual([item["command"] for item in menus[0]["commands"]], ["start", "help", "gotmeme", "comment"])
