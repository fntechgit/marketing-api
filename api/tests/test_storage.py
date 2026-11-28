from unittest import skipUnless

from django.conf import settings
from django.core.files.base import ContentFile
from django.test import TestCase

from api.utils.storage import S3Storage, SwiftStorage

S3 = settings.STORAGES_CONFIG['S3']
SWIFT = settings.STORAGES_CONFIG['SWIFT']


# Integration tests: they write to a real bucket and a real container, so they run only where
# the credentials are set.
class StorageTests(TestCase):
    @skipUnless(S3['ACCESS_KEY_ID'] and S3['SECRET_ACCESS_KEY'] and S3['STORAGE_BUCKET_NAME'],
                'needs AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY and AWS_STORAGE_BUCKET_NAME')
    def test_s3_storage(self):
        storage = S3Storage()
        name = storage.save("test_file.txt", ContentFile(b"test"))
        self.addCleanup(storage.delete, name)
        self.assertTrue(storage.exists(name))

    @skipUnless(SWIFT['AUTH_URL'] and SWIFT['APP_CRED_ID'] and SWIFT['APP_CRED_SECRET'] and SWIFT['CONTAINER_NAME'],
                'needs SWIFT_AUTH_URL, SWIFT_APP_CRED_ID, SWIFT_APP_CRED_SECRET and SWIFT_CONTAINER_NAME')
    def test_swift_storage(self):
        storage = SwiftStorage()
        name = storage.save("test_file.txt", ContentFile(b"test"))
        self.addCleanup(storage.delete, name)
        self.assertTrue(storage.exists(name))
