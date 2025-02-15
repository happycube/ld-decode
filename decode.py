#!/usr/bin/env python3
import argparse
import sys
from importlib import import_module
from multiprocessing import freeze_support

# from vhsdecode.main import main


def print_options():
    print("Options are vhs, cvbs, ld, hifi")


def main(argv):
    if len(argv) < 1:
        print_options()
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
    else:
        print_options()
        print(f"Instead got: {to_run}")


if __name__ == "__main__":
    freeze_support()
    main(sys.argv[1:])
