from dataclasses import dataclass


@dataclass
class AFEParamsVHS:
    def __init__(self):
        self.VCODeviation = 150e3


@dataclass
class AFEParams8mm:
    def __init__(self):
        self.VCODeviation = 100e3
        self.LCarrierRef = 1.5e6
        self.RCarrierRef = 1.7e6


@dataclass
class AFEParamsPALVHS(AFEParamsVHS):
    def __init__(self):
        super().__init__()
        self.LCarrierRef = 1.4e6
        self.RCarrierRef = 1.8e6
        self.Hfreq = 15.625e3


@dataclass
class AFEParamsNTSCVHS(AFEParamsVHS):
    def __init__(self):
        super().__init__()
        self.LCarrierRef = 1.3e6
        self.RCarrierRef = 1.7e6
        self.Hfreq = 15.750e3


@dataclass
class AFEParamsNTSC8mm(AFEParams8mm):
    def __init__(self):
        super().__init__()
        self.Hfreq = 15.750e3


@dataclass
class AFEParamsPAL8mm(AFEParams8mm):
    def __init__(self):
        super().__init__()
        self.Hfreq = 15.625e3


def get_standard(format, system, afe_vco_deviation, afe_left_carrier, afe_right_carrier):
    if format == "vhs":
        if system == "p":
            field_rate = 50
            standard = AFEParamsPALVHS()
        elif system == "n":
            field_rate = 59.94
            standard = AFEParamsNTSCVHS()
    elif format == "8mm":
        if system == "p":
            field_rate = 50
            standard = AFEParamsPAL8mm()
        elif system == "n":
            field_rate = 59.94
            standard = AFEParamsNTSC8mm()

    if afe_vco_deviation != 0:
        standard.VCODeviation = afe_vco_deviation
    if afe_left_carrier != 0:
        standard.LCarrierRef = afe_left_carrier
    if afe_right_carrier != 0:
        standard.RCarrierRef = afe_right_carrier

    return standard, field_rate
