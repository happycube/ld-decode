"""Unit tests for Field.build_errlist, which groups a field's flagged
samples into dropout runs.

Each run is widened by a margin: 8 samples before its first flag and 4
after its padded end.  The run that closes the field used to be appended
without them, so a dropout came out shorter whenever no later flag in the
field followed it - which on PAL was decided by whether the pilot happened
to trip the sync-region test somewhere after it.
"""

from types import SimpleNamespace

import numpy as np
import pytest

from lddecode.field import Field

pytestmark = [pytest.mark.unit, pytest.mark.decode]


def errlist(errmap):
    field = SimpleNamespace(linelocs=np.array([0.0, 100.0]), lineoffset=0,
                            rf=SimpleNamespace(freq=40))
    return Field.build_errlist(field, np.asarray(errmap))


def test_a_run_takes_the_same_margins_whether_or_not_it_is_the_last():
    run = list(range(500, 510))
    alone = errlist(run)
    followed = errlist(run + [5000])
    assert alone[0] == followed[0]
    assert len(alone) == 1 and len(followed) == 2


def test_the_margins():
    # 500..509: the padded end is 500 + 9 * 1.7, then 8 before and 4 after
    (start, end), = errlist(range(500, 510))
    assert start == 492
    assert end == pytest.approx(500 + 9 * 1.7 + 4)


def test_flags_within_20_samples_of_a_run_join_it():
    runs = errlist([500, 501, 515, 900])
    assert len(runs) == 2
    assert runs[0][0] == 492 and runs[1][0] == 892
