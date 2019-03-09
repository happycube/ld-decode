import numpy as np
import pandas as pd
import scipy as sp
import scipy.signal as sps
import scipy.fftpack as fftpack

import matplotlib.pyplot as plt

import lddecode_core as ldd
import lddutils as lddu

import vhs_formats


class VHSDecode(ldd.LDdecode):
        def __init__(self, fname_in, fname_out, freader, system = 'NTSC', doDOD = False,
                     inputfreq = 40):
                super(VHSDecode, self).__init__(fname_in, fname_out, freader, analog_audio = False,
                                                system = system, doDOD = doDOD)
                self.rf = VHSRFDecode(system = system, inputfreq = inputfreq)


class VHSRFDecode(ldd.RFDecode):
        def __init__(self, inputfreq = 40, system = 'NTSC'):
                super(VHSRFDecode, self).__init__(inputfreq, system, decode_analog_audio = False,
                                                  have_analog_audio = False)

        def computefilters(self):
                super(VHSRFDecode, self).computefilters()
