import numpy as np
import pandas as pd
import scipy as sp
import scipy.signal as sps
import scipy.fftpack as fftpack
import copy

import matplotlib.pyplot as plt

import lddecode_core as ldd
import lddutils as lddu

import vhs_formats

# Superclass to override laserdisc-specific parts of ld-decode with stuff that works for VHS
#
# We do this simply by using inheritance and overriding functions. This results in some redundant
# work that is later overridden, but avoids altering any ld-decode code to ease merging back in
# later as the ld-decode is in flux at the moment.
class VHSDecode(ldd.LDdecode):
        def __init__(self, fname_in, fname_out, freader, system = 'NTSC', doDOD = False,
                     inputfreq = 40):
                super(VHSDecode, self).__init__(fname_in, fname_out, freader, analog_audio = False,
                                                system = system, doDOD = doDOD)
                # Overwrite the rf decoder with the VHS-altered one
                self.rf = VHSRFDecode(system = system, inputfreq = inputfreq)


class VHSRFDecode(ldd.RFDecode):
        def __init__(self, inputfreq = 40, system = 'NTSC'):
                # First init the rf decoder normally.
                super(VHSRFDecode, self).__init__(inputfreq, system, decode_analog_audio = False,
                                                  have_analog_audio = False)

                # Then we override the laserdisc parameters with VHS ones.
                if system == 'PAL':
                        # Give the decoder it's separate own full copy to be on the safe side.
                        self.SysParams = copy.deepcopy(vhs_formats.SysParams_PAL_VHS)
                        self.DecoderParams = copy.deepcopy(vhs_formats.RFParams_PAL_VHS)
                else:
                        print("Non-PAL Not implemented yet!")
                        exit(1)

                # Lastly we re-create the filters with the new parameters.
                self.computevideofilters()


        # Override computedelays
        # It's normally used for dropout compensation, but the dropout compensation implementation
        # in ld-decode assumes composite color. This function is called even if it's disabled, and
        # seems to break with the VHS setup, so we disable it by overriding it for now.
        def computedelays(self, mtf_level = 0):
                pass
