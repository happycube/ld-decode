import unittest

import numpy as np

import vhsdecode.process as process
import vhsdecode.utils as utils


class DemodTest(unittest.TestCase):
    def test_ire(self):
        """Check that the IRE of the output corresponds to the correct frequencies."""
        samplerate_mhz = 40
        decoder = process.VHSRFDecode(inputfreq=samplerate_mhz, system="PAL")
        max_hz = 4800000
        max_mhz = max_hz / 1000000
        min_hz = 3800000
        min_mhz = min_hz / 1000000
        wavemax = utils.gen_wave_at_frequency(
            max_mhz, samplerate_mhz, decoder.blocklen / 2
        )
        wavemin = utils.gen_wave_at_frequency(
            min_mhz, samplerate_mhz, decoder.blocklen / 2
        )
        wave = np.concatenate((wavemax, wavemin))
        demod = decoder.demodblock(data=wave)["video"]["demod"]

        # Reference white
        max_ire_abs = decoder.iretohz(100)
        sync_ire_abs = decoder.iretohz(decoder.SysParams["vsync_ire"])
        print("max: ", max_ire_abs)
        print("min_ire: ", decoder.SysParams["vsync_ire"])
        print("min: ", sync_ire_abs)

        max_demod = demod[1000 : (decoder.blocklen // 2) - 1000]
        np.testing.assert_allclose(max_demod, np.full(len(max_demod), max_hz), rtol=1.5e-04, atol=20)
        min_demod = demod[(decoder.blocklen // 2) + 1000 : decoder.blocklen - 1000]
        # Demodulated signal fluctuates more at the sync end than at the top end,
        # so allowing a little more tolerance here.
        np.testing.assert_allclose(min_demod, np.full(len(min_demod), min_hz), rtol=3e-04, atol=20)

    def test_ire_ntsc(self):
        """Check that the IRE of the output corresponds to the correct frequencies."""
        samplerate_mhz = 40
        decoder = process.VHSRFDecode(inputfreq=samplerate_mhz, system="NTSC")
        max_hz = 4400000
        max_mhz = max_hz / 1000000
        min_hz = 3400000
        min_mhz = min_hz / 1000000
        wavemax = utils.gen_wave_at_frequency(
            max_mhz, samplerate_mhz, decoder.blocklen // 2
        )
        wavemin = utils.gen_wave_at_frequency(
            min_mhz, samplerate_mhz, decoder.blocklen // 2
        )
        wave = np.concatenate((wavemax, wavemin))
        demod = decoder.demodblock(data=wave)["video"]["demod"]

        max_ire_abs = decoder.iretohz(100)
        sync_ire_abs = decoder.iretohz(decoder.SysParams["vsync_ire"])
        print("max: ", max_ire_abs)
        print("min_ire: ", decoder.SysParams["vsync_ire"])
        print("min: ", sync_ire_abs)

        max_demod = demod[1000 : (decoder.blocklen // 2) - 1000]
        np.testing.assert_allclose(max_demod, np.full(len(max_demod), max_hz), rtol=1e-04, atol=20)
        min_demod = demod[(decoder.blocklen // 2) + 1000 : decoder.blocklen - 1000]
        # Demodulated signal fluctuates more at the sync end than at the top end,
        # so allowing a little more tolerance here.
        np.testing.assert_allclose(min_demod, np.full(len(min_demod), min_hz), rtol=1e-04, atol=50)


class SyncTest(unittest.TestCase):
    def test_sync(self):
        import lddecode.core as ldd
        import logging

        samplerate_mhz = 40

        ldd.logger = logging.getLogger("test")#LogStub()
        ldd.logger.info("test")

        ### process.VHSDecode("infile", "outfile", ,inputfreq=samplerate_mhz, system="PAL", tape_format="VHS")
        rfdecoder = process.VHSRFDecode(inputfreq=samplerate_mhz, system="PAL", tape_format="VHS")

        demod_05_data = np.loadtxt("PAL_GOOD.txt.gz")

        data_stub = {}
        data_stub["input"] = np.zeros(5)
        data_stub["video"] = {}
        data_stub["video"]["demod"] = np.zeros_like(demod_05_data)
        data_stub["video"]["demod_05"] = demod_05_data

        field = process.FieldPALVHS(rfdecoder, data_stub)

        pulses = rfdecoder.resync.getpulses_override(field)

        assert(len(pulses) == 458)

        return False


if __name__ == "__main__":
    unittest.main()
