from django.core.files.base import ContentFile
from django.test import TestCase

from api.utils.storage import S3Storage, SwiftStorage


class StorageTests(TestCase):
    def test_s3_storage(self):
        storage = S3Storage()
        name = storage.save("test_file.txt", ContentFile(b"test"))
        self.assertTrue(storage.exists(name))

    def test_swift_storage(self):
        storage = SwiftStorage()
        name = storage.save("test_file.txt", ContentFile(b"test"))
        self.assertTrue(storage.exists(name))
