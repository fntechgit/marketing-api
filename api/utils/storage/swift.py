from io import BytesIO, UnsupportedOperation
from shutil import copyfileobj
import gzip
from tempfile import SpooledTemporaryFile
import swiftclient
from keystoneauth1 import session
from keystoneauth1.identity import v3
from django.core.exceptions import ImproperlyConfigured
import magic
from datetime import datetime
from api.utils import config
from api.utils.storage.base import BaseCloudStorage, BaseCloudFile


class SwiftFile(BaseCloudFile):

   def _get_file(self):
        if self._file is None:
            self._file = SpooledTemporaryFile()
            headers, content = self._storage.download(self.name)
            with BytesIO(content) as file_content:
                copyfileobj(file_content, self._file)
            self._file.seek(0)
        return self._file


class SwiftStorage(BaseCloudStorage):
    _swift_conn = None
    _base_url =  config('STORAGES_CONFIG.SWIFT.BASE_URL', None)
    _auth_url = config('STORAGES_CONFIG.SWIFT.AUTH_URL', None)
    _application_credential_id = config('STORAGES_CONFIG.SWIFT.APP_CRED_ID')
    _application_credential_secret = config('STORAGES_CONFIG.SWIFT.APP_CRED_SECRET')
    _user_domain_name = config('STORAGES_CONFIG.SWIFT.USER_DOMAIN_NAME', 'Default')
    _project_domain_name = config('STORAGES_CONFIG.SWIFT.PROJECT_DOMAIN_NAME', 'Default')
    _project_id = config('STORAGES_CONFIG.SWIFT.PROJECT_ID', None)
    _project_name = config('STORAGES_CONFIG.SWIFT.PROJECT_NAME', None)
    _region_name = config('STORAGES_CONFIG.SWIFT.REGION_NAME', None)
    _container_name = config('STORAGES_CONFIG.SWIFT.CONTAINER_NAME', None)
    _os_options = {}
    _gzip_content_types = config('STORAGES_CONFIG.SWIFT.GZIP_CONTENT_TYPES', [])

    def __init__(self, **settings):
        super().__init__(**settings)
        _ = self.swift_conn

    @property
    def swift_conn(self):
        return self._get_client()

    def _get_client(self):
        """Get swift connection wrapper"""
        if not self._swift_conn:
            ac = v3.ApplicationCredential(
                self._auth_url,
                application_credential_id=self._application_credential_id,
                application_credential_secret=self._application_credential_secret
            )

            keystone_session = session.Session(auth=ac)
            _auth_version = '3'

            self._swift_conn = swiftclient.Connection(
                os_options=self._os_options,
                session=keystone_session,
                auth_version=_auth_version
            )

            self._check_container()

        return self._swift_conn

    def _check_container(self):
        """
        Check that container exists; raises exception if not.
        """
        try:
            self.swift_conn.head_container(self._container_name)
        except swiftclient.ClientException:
            headers = {}
            if self.auto_create_container:
                if self.auto_create_container_public:
                    headers['X-Container-Read'] = '.r:*'
                if self.auto_create_container_allow_orgin:
                    headers['X-Container-Meta-Access-Control-Allow-Origin'] = \
                        self.auto_create_container_allow_orgin
                self.swift_conn.put_container(self.container_name,
                                              headers=headers)
            else:
                raise ImproperlyConfigured(
                    "Container %s does not exist." % self.container_name)

    def _open(self, name, mode='rb'):
        return SwiftFile(name, self)

    def _save(self, name, content, headers=None):
        # Django rewinds file position to the beginning before saving,
        # so should we.
        # See django.core.files.storage.FileSystemStorage#_save
        # and django.core.files.base.File#chunks
        try:
            content.seek(0)
        except (AttributeError, UnsupportedOperation):  # pragma: no cover
            pass

        content_type = magic.from_buffer(content.read(1024), mime=True)
        # Go back to the beginning of the file
        content.seek(0)

        content_length = content.size

        if content_type in self._gzip_content_types or (
                content_type is None and self.gzip_unknown_content_type):
            gz_data = BytesIO()
            gzf = gzip.GzipFile(filename=name,
                                fileobj=gz_data,
                                mode='wb',
                                compresslevel=self.gzip_compression_level)
            gzf.write(content.file.read())
            gzf.close()
            content = gz_data.getvalue()
            content_length = None

            if not headers:
                headers = {}
            headers['Content-Encoding'] = 'gzip'

        self._swift_conn.put_object(self._container_name,
                                    name,
                                    content,
                                    content_length=content_length,
                                    content_type=content_type,
                                    headers=headers)
        return name

    def download(self, name):
        headers, content = self._swift_conn.get_object(self._container_name, name)
        return headers, content

    def get_headers(self, name):
        self.last_headers_value = self._swift_conn.head_object(self._container_name, name)
        self.last_headers_name = name
        return self.last_headers_value

    def path(self, name):
        return self.url(name)

    def delete(self, name):
        try:
            self._swift_conn.delete_object(self._container_name, name)
        except swiftclient.ClientException:
            pass

    def exists(self, name):
        try:
            self.get_headers(name)
        except swiftclient.ClientException:
            return False
        return True

    def listdir(self, path):
        container = self._swift_conn.get_container(
            self._container_name, prefix=path, full_listing=self.full_listing)
        files = []
        dirs = []
        for obj in container[1]:
            remaining_path = obj['name'][len(path):].split('/')
            key = remaining_path[0] if remaining_path[0] else remaining_path[1]

            if not self.isdir(key):
                files.append(key)
            elif key not in dirs:
                dirs.append(key)

        return dirs, files

    def size(self, name):
        return int(self.get_headers(name)['content-length'])

    def url(self, name):
        res = "/"
        return res.join([self._base_url, self._container_name, name])

    def get_accessed_time(self, name):
        pass

    def get_created_time(self, name):
        pass

    def get_modified_time(self, name):
        return datetime.fromtimestamp(
            float(self.get_headers(name)['x-timestamp']))