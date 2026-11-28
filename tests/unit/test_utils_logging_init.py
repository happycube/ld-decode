"""Unit tests for init_logging being safe to call more than once.

Every call added another stderr handler (and another log file handler,
leaving the previous file open) to the shared "lddecode" logger, so a
second call made every message print twice.  A later call now replaces
what an earlier one installed, and leaves other handlers alone.
"""

import logging
import sys

import pytest

from lddecode.utils_logging import console_safe, init_logging

pytestmark = [pytest.mark.unit]


@pytest.fixture
def clean_logger():
    logger = logging.getLogger("lddecode")
    before = list(logger.handlers)
    yield logger
    for handler in list(logger.handlers):
        if handler not in before:
            logger.removeHandler(handler)
            handler.close()


def ours(logger):
    return [h for h in logger.handlers if getattr(h, "_from_init_logging", False)]


def test_a_second_call_replaces_the_first_calls_handlers(clean_logger):
    init_logging(None)
    first = ours(clean_logger)
    init_logging(None)

    assert len(ours(clean_logger)) == 1
    assert ours(clean_logger) != first


def test_handlers_it_did_not_install_are_kept(clean_logger):
    other = logging.NullHandler()
    clean_logger.addHandler(other)
    try:
        init_logging(None)
        init_logging(None)
        assert other in clean_logger.handlers
    finally:
        clean_logger.removeHandler(other)


#: One backslash, spelt out so no tool on the way turns an escape into its character.
BACKSLASH = chr(92)


def _cp1252_console():
    """A console as Windows opens one: text in its code page."""
    import io

    return io.TextIOWrapper(io.BytesIO(), encoding="cp1252", newline="\n")


def test_a_message_the_console_cannot_encode_is_escaped_not_raised(clean_logger, monkeypatch):
    """An arrow in a message raised UnicodeEncodeError on a cp1252 console
    and printed a traceback in place of the message."""
    console = _cp1252_console()
    monkeypatch.setattr(sys, "stderr", console)
    errors = []
    monkeypatch.setattr(logging.Handler, "handleError", lambda self, record: errors.append(record))
    init_logging(None)

    clean_logger.info("MTF level 1.000 \N{RIGHTWARDS ARROW} 0.861")

    console.flush()
    assert not errors
    written = console.buffer.getvalue().decode("cp1252")
    assert written == "MTF level 1.000 " + BACKSLASH + "u2192 0.861\n"


def test_what_the_console_can_encode_is_left_as_it_is():
    """An accented letter is in cp1252 and stays; the arrow is escaped."""
    console = _cp1252_console()
    e_acute = "\N{LATIN SMALL LETTER E WITH ACUTE}"
    got = console_safe("caf" + e_acute + " \N{RIGHTWARDS ARROW} ok", console)
    assert got == "caf" + e_acute + " " + BACKSLASH + "u2192 ok"
    assert console_safe("plain ascii", console) == "plain ascii"


def test_a_stream_without_an_encoding_gets_the_text_unchanged():
    import io

    arrow = "\N{RIGHTWARDS ARROW}"
    assert console_safe(arrow, io.StringIO()) == arrow
