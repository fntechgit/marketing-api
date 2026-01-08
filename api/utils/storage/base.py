from abc import ABC, abstractmethod
from django.core.files.storage import Storage
from django.utils.deconstruct import deconstructible


class BaseCloudFile(ABC):

    def __init__(self, name, storage):
        self.name = name
        self._storage = storage
        self._file = None

    @abstractmethod
    def _get_file(self):
        pass

    def _set_file(self, value):
        self._file = value

    file = property(_get_file, _set_file)


@deconstructible
class BaseCloudStorage(Storage, ABC):

    def __init__(self, **settings):
        for name, value in settings.items():
            if hasattr(self, name):
                setattr(self, name, value)

    @abstractmethod
    def _get_client(self):
        pass

    @abstractmethod
    def _save(self, name, content, headers=None):
        pass

    @abstractmethod
    def _open(self, name, mode='rb'):
        pass

    @abstractmethod
    def delete(self, name):
        pass

    @abstractmethod
    def exists(self, name):
        pass

    @abstractmethod
    def size(self, name):
        pass

    @abstractmethod
    def url(self, name):
        pass
