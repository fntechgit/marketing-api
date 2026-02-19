from io import BytesIO
from tempfile import SpooledTemporaryFile
from django.core.exceptions import ImproperlyConfigured
import boto3
from botocore.exceptions import ClientError
import magic
import gzip
from api.utils import config
from .base import BaseCloudFile, BaseCloudStorage


class S3File(BaseCloudFile):

    def _get_file(self):
        if self._file is None:
            self._file = SpooledTemporaryFile()
            self._storage.download_to_file(self.name, self._file)
            self._file.seek(0)
        return self._file


class S3Storage(BaseCloudStorage):
    _s3_client = None
    _s3_resource = None
    _access_key = config("STORAGES_CONFIG.S3.ACCESS_KEY_ID", None)
    _secret_key = config('STORAGES_CONFIG.S3.SECRET_ACCESS_KEY', None)
    _region_name = config('STORAGES_CONFIG.S3.REGION_NAME', 'sfo2')
    _bucket_name = config('STORAGES_CONFIG.S3.STORAGE_BUCKET_NAME', None)
    _custom_domain = config('STORAGES_CONFIG.S3.CUSTOM_DOMAIN', None)
    _use_ssl = config('STORAGES_CONFIG.S3.USE_SSL', True)
    _endpoint_url = config('STORAGES_CONFIG.S3.ENDPOINT_URL', None)
    _gzip_content_types = config('STORAGES_CONFIG.S3.GZIP_CONTENT_TYPES', [])
    _default_acl = config('STORAGES_CONFIG.S3.DEFAULT_ACL', 'public-read')

    def _get_client(self):
        if not self._s3_client:
            session = boto3.session.Session(
                aws_access_key_id=self._access_key,
                aws_secret_access_key=self._secret_key,
                region_name=self._region_name
            )

            self._s3_client = session.client(
                's3',
                endpoint_url=self._endpoint_url,
                use_ssl=self._use_ssl
            )

            self._s3_resource = session.resource(
                's3',
                endpoint_url=self._endpoint_url,
                use_ssl=self._use_ssl
            )

            self._check_bucket()

        return self._s3_client

    @property
    def client(self):
        return self._get_client()

    @property
    def resource(self):
        if not self._s3_resource:
            self._get_client()
        return self._s3_resource

    def _check_bucket(self):
        try:
            self.client.head_bucket(Bucket=self._bucket_name)
        except ClientError:
            raise ImproperlyConfigured(
                f"Bucket {self._bucket_name} does not exist or is not accessible."
            )

    def _open(self, name, mode='rb'):
        return S3File(name, self)

    def _save(self, name, content, headers=None):
        try:
            content.seek(0)
        except (AttributeError, Exception):
            pass

        content_type = magic.from_buffer(content.read(1024), mime=True)
        content.seek(0)

        extra_args = {
            'ContentType': content_type or 'application/octet-stream',
            'ACL': self._default_acl
        }

        if headers:
            extra_args.update(headers)

        # gzip compression if apply
        if content_type in self._gzip_content_types:
            gz_buffer = BytesIO()
            with gzip.GzipFile(fileobj=gz_buffer, mode='wb') as gzf:
                gzf.write(content.read())
            gz_buffer.seek(0)
            content = gz_buffer
            extra_args['ContentEncoding'] = 'gzip'

        self.client.upload_fileobj(
            content,
            self._bucket_name,
            name,
            ExtraArgs=extra_args
        )

        return name

    def download_to_file(self, name, file_obj):
        """Downloads S3 object to file object"""
        self.client.download_fileobj(self._bucket_name, name, file_obj)

    def delete(self, name):
        try:
            self.client.delete_object(Bucket=self._bucket_name, Key=name)
        except ClientError:
            pass

    def exists(self, name):
        try:
            self.client.head_object(Bucket=self._bucket_name, Key=name)
            return True
        except ClientError:
            return False

    def size(self, name):
        response = self.client.head_object(Bucket=self._bucket_name, Key=name)
        return response['ContentLength']

    def url(self, name):
        if self._custom_domain:
            return f"https://{self._custom_domain}/{name}"

        # S3 standard URL
        return f"{self._endpoint_url}/{self._bucket_name}/{name}"

    def get_modified_time(self, name):
        response = self.client.head_object(Bucket=self._bucket_name, Key=name)
        return response['LastModified']