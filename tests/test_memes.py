from io import BytesIO
import unittest
from unittest.mock import Mock, patch

from botocore.exceptions import ClientError, NoCredentialsError
from botocore.response import StreamingBody

from gotbot.memes import EmptyMemeLibrary, MAX_PHOTO_BYTES, MemeStorageError, S3MemeRepository


class MemeRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.pages = self.client.get_paginator.return_value.paginate
        self.pages.return_value = [{"Contents": [{"Key": "got/jon.jpg", "Size": 5}]}]
        self.client.get_object.side_effect = lambda **kwargs: {"Body": BytesIO(b"photo")}
        self.repository = S3MemeRepository(self.client, "bucket", prefix="got/", cache_ttl=60)

    def test_pagination_filtering_and_private_download(self):
        self.pages.return_value = [
            {"Contents": [
                {"Key": "got/", "Size": 0}, {"Key": "got/note.txt", "Size": 10},
                {"Key": "got/empty.jpg", "Size": 0},
                {"Key": "got/huge.png", "Size": MAX_PHOTO_BYTES + 1},
            ]},
            {},
            {"Contents": [{"Key": "got/Jon Snow + throne.PNG", "Size": 5}]},
        ]
        meme = self.repository.random_meme()
        self.assertEqual(meme.filename, "Jon Snow + throne.PNG")
        self.assertEqual(meme.content, b"photo")
        self.client.get_paginator.assert_called_once_with("list_objects_v2")
        self.pages.assert_called_once_with(Bucket="bucket", Prefix="got/")
        self.client.get_object.assert_called_once_with(Bucket="bucket", Key="got/Jon Snow + throne.PNG")

    @patch("gotbot.memes.time.monotonic")
    def test_cache_and_expiry(self, clock):
        clock.return_value = 100
        self.repository.random_meme()
        clock.return_value = 159
        self.repository.random_meme()
        self.assertEqual(self.pages.call_count, 1)
        clock.return_value = 160
        self.repository.random_meme()
        self.assertEqual(self.pages.call_count, 2)

    @patch("gotbot.memes.time.monotonic")
    def test_empty_library_is_cached_and_later_refreshed(self, clock):
        clock.return_value = 100
        self.pages.return_value = [{}]
        for _ in range(2):
            with self.assertRaises(EmptyMemeLibrary):
                self.repository.random_meme()
        self.assertEqual(self.pages.call_count, 1)
        self.client.get_object.assert_not_called()
        self.pages.return_value = [{"Contents": [{"Key": "new.jpeg", "Size": 5}]}]
        clock.return_value = 160
        self.assertEqual(self.repository.random_meme().filename, "new.jpeg")

    def test_aws_listing_failures_are_wrapped_and_retried(self):
        self.pages.side_effect = NoCredentialsError()
        with self.assertRaises(MemeStorageError):
            self.repository.random_meme()
        self.pages.side_effect = None
        self.assertEqual(self.repository.random_meme().content, b"photo")
        self.assertEqual(self.pages.call_count, 2)

    def test_failed_pagination_does_not_cache_partial_results(self):
        def broken_pages(**kwargs):
            yield {"Contents": [{"Key": "partial.jpg", "Size": 5}]}
            raise ClientError({"Error": {"Code": "AccessDenied"}}, "ListObjectsV2")

        self.pages.side_effect = broken_pages
        with self.assertRaises(MemeStorageError):
            self.repository.random_meme()
        self.client.get_object.assert_not_called()
        self.pages.side_effect = None
        self.assertEqual(self.repository.random_meme().filename, "jon.jpg")

    def test_missing_object_invalidates_catalogue(self):
        self.client.get_object.side_effect = ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        with self.assertRaises(MemeStorageError):
            self.repository.random_meme()
        self.pages.return_value = [{"Contents": [{"Key": "replacement.jpg", "Size": 5}]}]
        self.client.get_object.side_effect = lambda **kwargs: {"Body": BytesIO(b"photo")}
        self.assertEqual(self.repository.random_meme().filename, "replacement.jpg")
        self.assertEqual(self.pages.call_count, 2)

    def test_download_body_is_closed(self):
        body = BytesIO(b"photo")
        self.client.get_object.side_effect = None
        self.client.get_object.return_value = {"Body": body}
        self.repository.random_meme()
        self.assertTrue(body.closed)

    def test_failed_read_is_wrapped_and_body_is_closed(self):
        body = Mock()
        body.read.side_effect = OSError("read failed")
        self.client.get_object.side_effect = None
        self.client.get_object.return_value = {"Body": body}
        with self.assertRaises(MemeStorageError):
            self.repository.random_meme()
        body.close.assert_called_once()

    def test_real_streaming_body_is_supported(self):
        stream = BytesIO(b"photo")
        self.client.get_object.side_effect = None
        self.client.get_object.return_value = {"Body": StreamingBody(stream, 5)}
        self.assertEqual(self.repository.random_meme().content, b"photo")
        self.assertTrue(stream.closed)

    def test_download_size_is_bounded_even_when_object_changes(self):
        for content in (b"", b"x" * (MAX_PHOTO_BYTES + 1)):
            body = Mock()
            body.read.return_value = content
            self.client.get_object.side_effect = None
            self.client.get_object.return_value = {"Body": body}
            with self.subTest(size=len(content)), self.assertRaises(MemeStorageError):
                self.repository.random_meme()
            body.read.assert_called_once_with(MAX_PHOTO_BYTES + 1)
            body.close.assert_called_once()
