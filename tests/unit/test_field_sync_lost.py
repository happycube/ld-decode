"""Unit tests for a field whose sync stops partway through.

Field.compute_linelocs needs sync pulses through the vertical sync after
the field.  When the last pulse in the read window comes sooner, it asks
for the field to be read again from 20 lines before line 0, so a window
that was cut short gets the whole field.  At the end of a disc the signal
itself can stop partway through the last field: a wide re-acquisition
read already starts about 20 lines before line 0, so it was asked to read
from almost the same place again, found the same field cut short in the
same place, and the decode spun on it forever without logging anything.
A window that already runs far past where the field needs pulses now
drops the field and moves past it instead.
"""

import logging
from types import SimpleNamespace

import numpy as np
import pytest

from lddecode import utils_logging as logs
from lddecode.field import Field

pytestmark = [pytest.mark.unit, pytest.mark.decode]

LINELEN = 2560.0
LINE0 = 20.25 * LINELEN
PROCLINES = 313 + 10 + 3               # PAL: outlinecount + 10 + 3


@pytest.fixture(autouse=True)
def quiet_logger(monkeypatch):
    """A dropped field logs; no decode has set the logger up here."""
    monkeypatch.setattr(logs, "logger", logging.getLogger("test-sync-lost"))


def field(window_lines, sync_lines):
    """A PAL field with line 0 20.25 lines into a window of window_lines,
    with half-line sync pulses for its first sync_lines lines only."""
    pulses = [SimpleNamespace(start=LINE0 + i * LINELEN / 2)
              for i in range(2 * sync_lines)]
    f = SimpleNamespace(
        rf=SimpleNamespace(system="PAL", SysParams={"field_lines": (312, 313)}),
        data={"video": {"demod": np.zeros(int(window_lines * LINELEN))}},
        outlinecount=313, lineoffset=0, inlinelen=LINELEN,
        initphase=False, fields_written=1,
        SYNC_LOST_LINES=Field.SYNC_LOST_LINES,
        getpulses=lambda: pulses,
        refinepulses=lambda: pulses,
        computeLineLen=lambda validpulses: LINELEN,
        getLine0=lambda validpulses, meanlinelen: (LINE0, None, True),
    )
    return f


def test_a_short_window_is_read_again_from_before_line_0():
    # the narrow window: ~371 lines, too few to tell a cut-off window
    # from a cut-off signal
    linelocs, _, offset = Field.compute_linelocs(field(371, 270))

    assert linelocs is None
    assert offset == pytest.approx(LINE0 - 20 * LINELEN)


def test_a_field_whose_sync_stops_in_a_wide_window_is_skipped_past(caplog):
    # the wide window: ~643 lines, sync lost at line 270
    linelocs, _, offset = Field.compute_linelocs(field(643, 270))

    assert linelocs is None
    assert offset > LINE0 + 100 * LINELEN
    assert "Sync lost at line 269" in caplog.text


def test_a_window_reaching_just_past_the_field_still_reads_again():
    # A pulse missed at the window's edge must not drop a field: only a
    # window SYNC_LOST_LINES past where the field needs pulses does.
    lines = 20.25 + PROCLINES + Field.SYNC_LOST_LINES - 1
    _, _, offset = Field.compute_linelocs(field(lines, 270))

    assert offset == pytest.approx(LINE0 - 20 * LINELEN)
