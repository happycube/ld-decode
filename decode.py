#!/usr/bin/env python3
import sys
from multiprocessing import freeze_support

# from vhsdecode.main import main


def print_options():
    print("Options are vhs, cvbs, ld, hifi, filter-tune, decode-launcher")

def _launch_decode_launcher(argv):
    from vhsdecode.windows_bootstrap import prepare_frozen_windows_gui_launch

    prepare_frozen_windows_gui_launch()

    from vhsdecode.decode_launcher import main as decodelaunchermain

    decodelaunchermain(argv)


def main(argv):
    if len(argv) < 1:
        _launch_decode_launcher(argv)
        return

    # This seems a bit hacky but it works
    # use pop so the arg gets removed from the list
    # this means the command line parser
    # that is ran later won't see this argument.
    to_run = sys.argv.pop(1).lower()

    if to_run == "vhs":
        from vhsdecode.main import main as vhsmain

        vhsmain()
    elif to_run == "cvbs":
        from cvbsdecode.main import main as cvbsmain

        cvbsmain()
    elif to_run == "ld":
        from lddecode.main import main as ldmain

        ldmain(sys.argv[1:])
    elif to_run == "hifi":
        from vhsdecode.hifi.main import main as hifimain

        hifimain()
    elif to_run == "filter-tune" or to_run == "filter_tune" or to_run == "filtertune":
        from filter_tune.filter_tune import main as filtertunemain

        filtertunemain()
    elif to_run in {"decode-launcher", "decode_launcher", "launcher"}:
        _launch_decode_launcher(sys.argv[1:])
    else:
        print_options()
        print(f"Instead got: {to_run}")


if __name__ == "__main__":
    freeze_support()
    main(sys.argv[1:])
