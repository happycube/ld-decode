"""Delay calibration under --rf_echo_cancel.

computedelays() measures the filter delays on a synthetic, echo-free
signal.  Passing it through the echo inverse added the anti-echo the
inverse is built to cancel - shifting the sync and white delays by most
of a sample for a strong manual echo - and in auto mode fed the synthetic
block into the echo estimate as if it had come off the disc.
"""

import pytest

from lddecode.rfdecode import RFDecode

pytestmark = [pytest.mark.unit, pytest.mark.dsp]


@pytest.mark.parametrize("system", ["NTSC", "PAL"])
def test_a_manual_echo_leaves_the_delays_alone(system):
    plain = RFDecode(inputfreq=40, system=system)
    echo = RFDecode(inputfreq=40, system=system,
                    extra_options={"rf_echo_cancel": [(40, 0.3)]})

    assert echo._echo_inv is not None
    assert echo.delays == plain.delays


@pytest.mark.parametrize("system", ["NTSC", "PAL"])
def test_the_calibration_block_is_not_an_echo_observation(system):
    rf = RFDecode(inputfreq=40, system=system,
                  extra_options={"rf_echo_cancel": True})

    assert rf._echo_n == 0
    assert rf._echo_magacc is None
