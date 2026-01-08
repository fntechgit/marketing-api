from django.conf import settings


def config(name: str, default=None):
    """
    Helper function to get a Django setting by name. If setting doesn't exists
    it will return a default.
    :param name: Name of setting
    :type name: str
    :param default: Value if setting is unfound
    :returns: Setting's value
    """
    vars = name.split('.')
    entry = None
    for v in vars:
        entry = getattr(settings, v, default) if entry is None else (entry[v] if v in entry else None)

    entry = default if entry is None else entry

    return entry