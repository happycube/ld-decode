"""Unit tests for init_logging being safe to call more than once.

Every call added another stderr handler (and another log file handler,
leaving the previous file open) to the shared "lddecode" logger, so a
second call made every message print twice.  A later call now replaces
what an earlier one installed, and leaves other handlers alone.
"""

import logging

import pytest

from lddecode.utils_logging import init_logging

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
