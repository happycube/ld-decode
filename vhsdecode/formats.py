from lddecode.core import (
    FilterParams_PAL,
    FilterParams_NTSC,
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
EQ_PULSE_TOLERANCE = 0.9
MAX_WOW = 1.06

SysParams_NTSC["analog_audio"] = False
SysParams_PAL["analog_audio"] = False

def is_color_under(tape_format: str):
    return tape_format not in ["TYPEC", "TYPEB"]


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
                FilterParams_PAL
            )
        if tape_format == "UMATIC_HI":
            from vhsdecode.format_defs.umatic import (
                get_rfparams_pal_umatic_hi,
                get_sysparams_pal_umatic_hi,
            )

            return get_sysparams_pal_umatic_hi(
                SysParams_PAL
            ), get_rfparams_pal_umatic_hi(FilterParams_PAL)
        elif tape_format == "BETAMAX":
            from vhsdecode.format_defs.betamax import (
                get_rfparams_pal_betamax,
                get_sysparams_pal_betamax,
            )

            return get_sysparams_pal_betamax(SysParams_PAL), get_rfparams_pal_betamax(
                FilterParams_PAL
            )
        elif tape_format == "VHSHQ":
            from vhsdecode.format_defs.vhs import (
                get_rfparams_pal_vhs,
                get_sysparams_pal_vhshq,
            )

            return get_sysparams_pal_vhshq(SysParams_PAL), get_rfparams_pal_vhs(
                FilterParams_PAL
            )
        elif tape_format == "SVHS":
            from vhsdecode.format_defs.vhs import (
                get_rfparams_pal_svhs,
                get_sysparams_pal_svhs,
            )

            return get_sysparams_pal_svhs(SysParams_PAL), get_rfparams_pal_svhs(
                FilterParams_PAL
            )
        elif tape_format == "VIDEO8":
            from vhsdecode.format_defs.video8 import (
                get_rfparams_pal_video8,
                get_sysparams_pal_video8,
            )

            return get_sysparams_pal_video8(SysParams_PAL), get_rfparams_pal_video8(
                FilterParams_PAL
            )
        elif tape_format == "HI8":
            from vhsdecode.format_defs.video8 import (
                get_rfparams_pal_hi8,
                get_sysparams_pal_hi8,
            )

            return get_sysparams_pal_hi8(SysParams_PAL), get_rfparams_pal_hi8(
                FilterParams_PAL
            )
        elif tape_format == "EIAJ":
            from vhsdecode.format_defs.eiaj import (
                get_rfparams_pal_eiaj,
                get_sysparams_pal_eiaj,
            )

            return get_sysparams_pal_eiaj(SysParams_PAL), get_rfparams_pal_eiaj(
                FilterParams_PAL
            )
        elif tape_format == "TYPEB":
            from vhsdecode.format_defs.typec import (
                get_rfparams_pal_typeb,
                get_sysparams_pal_typeb,
            )

            return get_sysparams_pal_typeb(SysParams_PAL), get_rfparams_pal_typeb(
                FilterParams_PAL
            )
        elif tape_format == "TYPEC":
            from vhsdecode.format_defs.typec import (
                get_rfparams_pal_typec,
                get_sysparams_pal_typec,
            )

            return get_sysparams_pal_typec(SysParams_PAL), get_rfparams_pal_typec(
                FilterParams_PAL
            )
        elif tape_format == "VCR":
            from vhsdecode.format_defs.vcr import (
                get_rfparams_pal_vcr,
                get_sysparams_pal_vcr,
            )

            return get_sysparams_pal_vcr(SysParams_PAL), get_rfparams_pal_vcr(
                FilterParams_PAL
            )
        elif tape_format == "VCR_LP":
            from vhsdecode.format_defs.vcr import (
                get_rfparams_pal_vcr_lp,
                get_sysparams_pal_vcr_lp,
            )

            return get_sysparams_pal_vcr_lp(SysParams_PAL), get_rfparams_pal_vcr_lp(
                FilterParams_PAL
            )
        else:
            if tape_format != "VHS":
                logger.warning(
                    'Tape format "%s" not supported for PAL yet', tape_format
                )
            from vhsdecode.format_defs.vhs import (
                get_rfparams_pal_vhs,
                get_sysparams_pal_vhs,
            )

            return get_sysparams_pal_vhs(SysParams_PAL), get_rfparams_pal_vhs(
                FilterParams_PAL
            )
    elif system == "NTSC":
        if tape_format == "UMATIC":
            from vhsdecode.format_defs.umatic import (
                get_rfparams_ntsc_umatic,
                get_sysparams_ntsc_umatic,
            )

            return get_sysparams_ntsc_umatic(SysParams_NTSC), get_rfparams_ntsc_umatic(
                FilterParams_NTSC
            )
        elif tape_format == "VHSHQ":
            from vhsdecode.format_defs.vhs import (
                get_rfparams_ntsc_vhs,
                get_sysparams_ntsc_vhshq,
            )

            return get_sysparams_ntsc_vhshq(SysParams_NTSC), get_rfparams_ntsc_vhs(
                FilterParams_NTSC
            )
        elif tape_format == "SVHS":
            from vhsdecode.format_defs.vhs import (
                get_rfparams_ntsc_svhs,
                get_sysparams_ntsc_svhs,
            )

            return get_sysparams_ntsc_svhs(SysParams_NTSC), get_rfparams_ntsc_svhs(
                FilterParams_NTSC
            )
        elif tape_format == "BETAMAX":
            from vhsdecode.format_defs.betamax import (
                get_rfparams_ntsc_betamax,
                get_sysparams_ntsc_betamax,
            )

            return get_sysparams_ntsc_betamax(
                SysParams_NTSC
            ), get_rfparams_ntsc_betamax(FilterParams_NTSC)
        elif tape_format == "BETAMAX_HIFI":
            from vhsdecode.format_defs.betamax import (
                get_rfparams_ntsc_betamax_hifi,
                get_sysparams_ntsc_betamax_hifi,
            )

            return get_sysparams_ntsc_betamax_hifi(
                SysParams_NTSC
            ), get_rfparams_ntsc_betamax_hifi(FilterParams_NTSC)
        elif tape_format == "VIDEO8":
            from vhsdecode.format_defs.video8 import (
                get_rfparams_ntsc_video8,
                get_sysparams_ntsc_video8,
            )

            return get_sysparams_ntsc_video8(SysParams_NTSC), get_rfparams_ntsc_video8(
                FilterParams_NTSC
            )
        elif tape_format == "HI8":
            from vhsdecode.format_defs.video8 import (
                get_rfparams_ntsc_hi8,
                get_sysparams_ntsc_hi8,
            )

            return get_sysparams_ntsc_hi8(SysParams_NTSC), get_rfparams_ntsc_hi8(
                FilterParams_NTSC
            )
        elif tape_format == "TYPEB":
            from vhsdecode.format_defs.typec import (
                get_rfparams_ntsc_typeb,
                get_sysparams_ntsc_typeb,
            )

            return get_sysparams_ntsc_typeb(SysParams_NTSC), get_rfparams_ntsc_typeb(
                FilterParams_NTSC
            )
        elif tape_format == "TYPEC":
            from vhsdecode.format_defs.typec import (
                get_rfparams_ntsc_typec,
                get_sysparams_ntsc_typec,
            )

            return get_sysparams_ntsc_typec(SysParams_NTSC), get_rfparams_ntsc_typec(
                FilterParams_NTSC
            )
        else:
            if tape_format != "VHS":
                logger.warning(
                    'Tape format "%s" not supported for NTSC yet', tape_format
                )
            from vhsdecode.format_defs.vhs import (
                get_rfparams_ntsc_vhs,
                get_sysparams_ntsc_vhs,
            )

            return get_sysparams_ntsc_vhs(SysParams_NTSC), get_rfparams_ntsc_vhs(
                FilterParams_NTSC
            )
    elif system == "MPAL":
        if tape_format != "VHS":
            logger.warning('Tape format "%s" not supported for MPAL yet', tape_format)
        from vhsdecode.format_defs.vhs import (
            get_rfparams_mpal_vhs,
            get_sysparams_mpal_vhs,
        )

        return get_sysparams_mpal_vhs(SysParams_NTSC), get_rfparams_mpal_vhs(
            FilterParams_NTSC
        )
    elif system == "MESECAM":
        if tape_format != "VHS":
            logger.warning(
                'Tape format "%s" not supported for MESECAM yet', tape_format
            )
        from vhsdecode.format_defs.vhs import (
            get_rfparams_mesecam_vhs,
            get_sysparams_mesecam_vhs,
        )

        return get_sysparams_mesecam_vhs(SysParams_PAL), get_rfparams_mesecam_vhs(
            FilterParams_PAL
        )
    else:
        raise Exception("Unknown video system! ", system)
