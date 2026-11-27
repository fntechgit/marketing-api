import logging

from base_api_utils.utils import RedactingHandlerMixin


# The local sinks write each record redacted, as the OTLP handler exports it: urllib3 logs the
# introspection request line at DEBUG, and base_api_utils sends the token in its query string.


class RedactingStreamHandler(RedactingHandlerMixin, logging.StreamHandler):
    """The console sink."""


class RedactingFileHandler(RedactingHandlerMixin, logging.FileHandler):
    """The file sink."""
