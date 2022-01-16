from lddecode.core import (
    RFParams_PAL,
    RFParams_NTSC,
    SysParams_PAL,
    SysParams_NTSC,
)

# Default thresholds for rf dropout detection.
DEFAULT_THRESHOLD_P_DDD = 0.18
DEFAULT_THRESHOLD_P_CXADC = 0.35
DEFAULT_HYSTERESIS = 1.25
# Merge dropouts if they there is less than this number of samples between them.
DOD_MERGE_THRESHOLD = 30
DOD_MIN_LENGTH = 10
DEFAULT_SHARPNESS = 0
BLANK_LENGTH_THRESHOLD = 9
# lddecode uses 0.5 - upping helps decode some tapes with bad vsync.
EQ_PULSE_TOLERANCE = 0.7
MAX_WOW = 1.06

SysParams_NTSC["analog_audio"] = False
SysParams_PAL["analog_audio"] = False


def get_format_params(system: str, tape_format: str, logger):
    """Get format parameters based on video system and tape format.
    Will raise an exception if the system is not one of PAL, NTSC and MPAL
    """
    # We base the parameters off the original laserdisc ones and override the ones
    # we need.
    if system == "PAL":
        if tape_format == "UMATIC":
            from vhsdecode.format_defs.umatic import (
                get_rfparams_pal_umatic,
                get_sysparams_pal_umatic,
            )

            return get_sysparams_pal_umatic(SysParams_PAL), get_rfparams_pal_umatic(
                RFParams_PAL
            )
        elif tape_format == "SVHS":
            from vhsdecode.format_defs.vhs import (
                get_rfparams_pal_svhs,
                get_sysparams_pal_svhs,
            )

            return get_sysparams_pal_svhs(SysParams_PAL), get_rfparams_pal_svhs(
                RFParams_PAL
            )
        else:
            from vhsdecode.format_defs.vhs import (
                get_rfparams_pal_vhs,
                get_sysparams_pal_vhs,
            )

            return get_sysparams_pal_vhs(SysParams_PAL), get_rfparams_pal_vhs(
                RFParams_PAL
            )
    elif system == "NTSC":
        if tape_format == "UMATIC":
            from vhsdecode.format_defs.umatic import (
                get_rfparams_ntsc_umatic,
                get_sysparams_ntsc_umatic,
            )

            return get_sysparams_ntsc_umatic(SysParams_NTSC), get_rfparams_ntsc_umatic(
                RFParams_NTSC
            )

        elif tape_format == "SVHS":
            from vhsdecode.format_defs.vhs import (
                get_rfparams_ntsc_svhs,
                get_sysparams_ntsc_svhs,
            )

            return get_sysparams_ntsc_svhs(SysParams_NTSC), get_rfparams_ntsc_svhs(
                RFParams_NTSC
            )
        else:
            from vhsdecode.format_defs.vhs import (
                get_rfparams_ntsc_vhs,
                get_sysparams_ntsc_vhs,
            )

            return get_sysparams_ntsc_vhs(SysParams_NTSC), get_rfparams_ntsc_vhs(
                RFParams_NTSC
            )
    elif system == "MPAL":
        if tape_format != "VHS":
            logger.warning('Tape format "%s" not supported for MPAL yet', tape_format)
        from vhsdecode.format_defs.vhs import (
            get_rfparams_mpal_vhs,
            get_sysparams_mpal_vhs,
        )

        return get_sysparams_mpal_vhs(SysParams_NTSC), get_rfparams_mpal_vhs(
            RFParams_NTSC
        )
    else:
        raise Exception("Unknown video system! ", system)
