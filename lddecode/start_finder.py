"""Find the clean pre-roll before programme playback in an LD RF capture.

The normal decoder's ``--start`` argument is a capture-relative file-frame
number. This module finds that number without writing any decode output. It
uses the existing field and Philips-code decoders, so it deliberately avoids
trying to infer programme material from RF amplitude alone.
"""

from __future__ import print_function

import argparse
import sys
import warnings
from collections import namedtuple

from lddecode.core import LDdecode
from lddecode.utils import make_loader, parse_frequency

RF_SAMPLE_RATE = 40000000
DEFAULT_MAX_SEARCH_SECONDS = 300.0
DEFAULT_FALLBACK_SECONDS = 10.0
DEFAULT_PRE_ROLL_SEARCH_SECONDS = 5.0
# A five-frame run can occur while a player is still settling or seeking. One
# second of clean, normal-speed addresses is long enough to reject that case.
REQUIRED_VBI_FRAMES = 30

FrameObservation = namedtuple(
    "FrameObservation", "file_frame readloc address disk_type"
)
"""A complete decoded video frame and its capture-relative location."""


StartResult = namedtuple(
    "StartResult",
    "file_frame readloc confidence disk_type addresses searched_seconds",
)
"""Result from :func:`find_start`; confidence is ``vbi`` or ``fallback``."""


def file_frame_from_readloc(readloc, bytes_per_field):
    """Convert a field read location to the number consumed by ``--start``."""

    if bytes_per_field <= 0:
        raise ValueError("bytes_per_field must be positive")
    return int(readloc) // (int(bytes_per_field) * 2)


class VbiRunDetector:
    """Recognise contiguous, normal-speed CAV or CLV address runs."""

    def __init__(self, required_frames=REQUIRED_VBI_FRAMES):
        if required_frames < 1:
            raise ValueError("required_frames must be positive")
        self.required_frames = required_frames
        self.run = []

    def reset(self):
        self.run = []

    def observe(self, observation):
        """Add an observation and return the first run member when qualified."""

        if observation is None or observation.address is None:
            self.reset()
            return None

        if self.run:
            previous = self.run[-1]
            contiguous = (
                observation.disk_type == previous.disk_type
                and observation.address == previous.address + 1
            )
            if not contiguous:
                self.reset()

        self.run.append(observation)
        if len(self.run) >= self.required_frames:
            return self.run[0]
        return None


class _StableVideoTracker:
    """Track a continuous valid-field run for guarded VBI-less fallback."""

    def __init__(self):
        self.start_readloc = None
        self.last_readloc = None

    def reset(self):
        self.start_readloc = None
        self.last_readloc = None

    def observe(self, field, bytes_per_field):
        readloc = int(field.readloc)
        discontinuity = (
            self.last_readloc is None
            or readloc <= self.last_readloc
            or readloc - self.last_readloc > int(bytes_per_field) * 2
        )
        if discontinuity:
            self.start_readloc = readloc
        self.last_readloc = readloc
        return self.start_readloc


class _PreRollTracker:
    """Find the earliest clean field sequence immediately before content."""

    def __init__(self, bytes_per_field, field_phases):
        self.bytes_per_field = int(bytes_per_field)
        self.field_phases = int(field_phases)
        self.start_field = None
        self.previous_field = None

    def reset(self):
        self.start_field = None
        self.previous_field = None

    def _is_continuous(self, field):
        previous = self.previous_field
        if previous is None:
            return False

        distance = int(field.readloc) - int(previous.readloc)
        if distance < (self.bytes_per_field // 2):
            return False
        if distance > (self.bytes_per_field + (self.bytes_per_field // 2)):
            return False

        previous_phase = getattr(previous, "fieldPhaseID", None)
        current_phase = getattr(field, "fieldPhaseID", None)
        if previous_phase is None or current_phase is None:
            return bool(previous.isFirstField) != bool(field.isFirstField)

        expected_phase = 1 if previous_phase == self.field_phases else previous_phase + 1
        return current_phase == expected_phase

    def observe(self, field):
        if not self._is_continuous(field):
            self.start_field = field if field.isFirstField else None
        elif self.start_field is None and field.isFirstField:
            self.start_field = field
        self.previous_field = field


class _FinderLogger:
    """Suppress expected bad-RF diagnostics unless verbose output is wanted."""

    def __init__(self, report, verbose):
        self.report = report
        self.verbose = verbose

    def _log(self, message, *args):
        if not self.verbose or self.report is None:
            return
        if args:
            message = message % args
        self.report("decoder: " + str(message))

    debug = _log
    info = _log
    warning = _log
    error = _log

    def status(self, message):
        self._log(message)


def _make_decoder(filename, system, inputfreq, report, verbose):
    loader = make_loader(filename, inputfreq)
    return LDdecode(
        filename,
        None,
        loader,
        _FinderLogger(report, verbose),
        analog_audio=0,
        digital_audio=False,
        system=system,
        doDOD=False,
        threads=0,
    )


class StartFinder:
    """Run the lightweight field/VBI scan used by the command-line tool."""

    def __init__(
        self,
        decoder_factory,
        max_search_seconds=DEFAULT_MAX_SEARCH_SECONDS,
        fallback_seconds=DEFAULT_FALLBACK_SECONDS,
        required_frames=REQUIRED_VBI_FRAMES,
        sample_rate=RF_SAMPLE_RATE,
        pre_roll_search_seconds=DEFAULT_PRE_ROLL_SEARCH_SECONDS,
        report=None,
    ):
        if max_search_seconds < 0:
            raise ValueError("max_search_seconds must not be negative")
        if fallback_seconds < 0:
            raise ValueError("fallback_seconds must not be negative")
        if pre_roll_search_seconds < 0:
            raise ValueError("pre_roll_search_seconds must not be negative")
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")

        self.decoder_factory = decoder_factory
        self.max_search_seconds = max_search_seconds
        self.fallback_seconds = fallback_seconds
        self.sample_rate = sample_rate
        self.pre_roll_search_seconds = pre_roll_search_seconds
        self.report = report
        self.detector = VbiRunDetector(required_frames)

    def _report_progress(self, position, last_bucket):
        seconds = int(position // self.sample_rate)
        bucket = seconds // 10
        if self.report is not None and seconds and bucket > last_bucket:
            self.report("scanned {0:02d}:{1:02d}".format(seconds // 60, seconds % 60))
        return bucket

    def _find_pre_roll_start(self, stable_observation, bytes_per_field, field_phases):
        """Replay the preceding clean field run and return its first frame."""

        if not self.pre_roll_search_seconds:
            return stable_observation

        lookback_samples = int(self.pre_roll_search_seconds * self.sample_rate)
        position = max(0, stable_observation.readloc - lookback_samples)
        tracker = _PreRollTracker(bytes_per_field, field_phases)
        previous_field = None
        decoder = None

        try:
            decoder = self.decoder_factory()
            while position <= stable_observation.readloc:
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", RuntimeWarning)
                        field, offset = decoder.decodefield(position, 0, previous_field)
                except (KeyboardInterrupt, SystemExit):
                    raise
                except Exception as error:
                    if self.report is not None:
                        self.report(
                            "pre-roll decode failure at sample {0}: {1}; "
                            "skipping one second".format(position, error)
                        )
                    decoder.close()
                    decoder = self.decoder_factory()
                    tracker.reset()
                    previous_field = None
                    position += self.sample_rate
                    continue

                if field is None or offset is None:
                    break

                try:
                    offset = int(offset)
                except (TypeError, ValueError):
                    offset = 0
                if offset <= 0:
                    offset = self.sample_rate

                if not field.valid:
                    tracker.reset()
                    previous_field = None
                elif int(field.readloc) <= stable_observation.readloc:
                    tracker.observe(field)
                    previous_field = field

                if int(getattr(field, "readloc", position)) >= stable_observation.readloc:
                    break
                position += offset
        finally:
            if decoder is not None:
                decoder.close()

        if tracker.start_field is None:
            return stable_observation

        return FrameObservation(
            file_frame_from_readloc(tracker.start_field.readloc, bytes_per_field),
            int(tracker.start_field.readloc),
            stable_observation.address,
            stable_observation.disk_type,
        )

    def search(self):
        """Return a :class:`StartResult`, or ``None`` when no start is found."""

        max_samples = None
        if self.max_search_seconds:
            max_samples = int(self.max_search_seconds * self.sample_rate)
        fallback_samples = int(self.fallback_seconds * self.sample_rate)

        decoder = None
        position = 0
        previous_field = None
        first_field = None
        stable_video = _StableVideoTracker()
        last_progress_bucket = -1

        try:
            decoder = self.decoder_factory()
            while max_samples is None or position <= max_samples:
                last_progress_bucket = self._report_progress(
                    position, last_progress_bucket
                )
                try:
                    # Bad tracking windows can make the RF calculations emit NumPy
                    # RuntimeWarnings. They are expected probe failures, not a
                    # diagnostic for the caller.
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", RuntimeWarning)
                        field, offset = decoder.decodefield(
                            position, 0, previous_field
                        )
                except (KeyboardInterrupt, SystemExit):
                    raise
                except Exception as error:
                    if self.report is not None:
                        self.report(
                            "decode failure at sample {0}: {1}; skipping one second".format(
                                position, error
                            )
                        )
                    decoder.close()
                    decoder = None
                    decoder = self.decoder_factory()
                    position += self.sample_rate
                    previous_field = None
                    first_field = None
                    stable_video.reset()
                    self.detector.reset()
                    continue

                if field is None or offset is None:
                    return None

                try:
                    offset = int(offset)
                except (TypeError, ValueError):
                    offset = 0
                if offset <= 0:
                    offset = self.sample_rate
                next_position = position + offset

                if not field.valid:
                    previous_field = None
                    first_field = None
                    stable_video.reset()
                    self.detector.reset()
                    # Before content locks, testing every nominal field makes a
                    # tracking-back capture unnecessarily slow. A one-second
                    # stride still exercises a different field phase on each
                    # probe and is the same recovery interval used for errors.
                    position += self.sample_rate
                    continue

                stable_start = stable_video.observe(field, decoder.bytes_per_field)

                if field.isFirstField:
                    if first_field is not None:
                        self.detector.reset()
                    first_field = field
                elif first_field is None:
                    self.detector.reset()
                else:
                    address = decoder.decodeFrameNumber(first_field, field)
                    disk_type = "CLV" if decoder.isCLV else "CAV"
                    observation = FrameObservation(
                        file_frame_from_readloc(
                            first_field.readloc, decoder.bytes_per_field
                        ),
                        int(first_field.readloc),
                        None if address is None else int(address),
                        disk_type,
                    )
                    qualified = self.detector.observe(observation)
                    first_field = None
                    if qualified is not None:
                        pre_roll = self._find_pre_roll_start(
                            qualified,
                            decoder.bytes_per_field,
                            decoder.rf.SysParams["fieldPhases"],
                        )
                        return StartResult(
                            pre_roll.file_frame,
                            pre_roll.readloc,
                            "vbi",
                            qualified.disk_type,
                            tuple(item.address for item in self.detector.run),
                            float(position) / self.sample_rate,
                        )

                if (
                    fallback_samples
                    and int(field.readloc) - stable_start >= fallback_samples
                ):
                    return StartResult(
                        file_frame_from_readloc(
                            stable_start, decoder.bytes_per_field
                        ),
                        stable_start,
                        "fallback",
                        None,
                        tuple(),
                        float(position) / self.sample_rate,
                    )

                previous_field = field
                position = next_position
        finally:
            if decoder is not None:
                decoder.close()

        return None


def find_start(
    filename,
    system="NTSC",
    inputfreq=None,
    max_search_seconds=DEFAULT_MAX_SEARCH_SECONDS,
    fallback_seconds=DEFAULT_FALLBACK_SECONDS,
    required_frames=REQUIRED_VBI_FRAMES,
    pre_roll_search_seconds=DEFAULT_PRE_ROLL_SEARCH_SECONDS,
    report=None,
    verbose=False,
):
    """Find clean pre-roll before programme playback without writing output."""

    def decoder_factory():
        return _make_decoder(filename, system, inputfreq, report, verbose)

    finder = StartFinder(
        decoder_factory,
        max_search_seconds=max_search_seconds,
        fallback_seconds=fallback_seconds,
        required_frames=required_frames,
        pre_roll_search_seconds=pre_roll_search_seconds,
        report=report,
    )
    return finder.search()


def _nonnegative_float(value):
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return parsed


def _build_parser():
    from lddecode import __version__

    parser = argparse.ArgumentParser(
        description=(
            "Find clean pre-roll before programme playback in a LaserDisc RF capture. "
            "A confirmed result is written as an ld-decode --start argument."
        )
    )
    parser.add_argument("infile", metavar="infile", help="source RF capture")
    parser.add_argument(
        "--max-search",
        metavar="seconds",
        type=_nonnegative_float,
        default=DEFAULT_MAX_SEARCH_SECONDS,
        help="maximum source seconds to search; 0 searches to EOF (default: 300)",
    )
    parser.add_argument(
        "--pre-roll-search",
        metavar="seconds",
        type=_nonnegative_float,
        default=DEFAULT_PRE_ROLL_SEARCH_SECONDS,
        help="seconds to replay before content to retain clean pre-roll (default: 5)",
    )
    parser.add_argument(
        "--PAL", "-p", "--pal", dest="pal", action="store_true", help="source is PAL"
    )
    parser.add_argument(
        "--NTSC", "-n", "--ntsc", dest="ntsc", action="store_true", help="source is NTSC"
    )
    parser.add_argument(
        "--NTSCJ", "-j", dest="ntscj", action="store_true", help="source is NTSC-J"
    )
    parser.add_argument(
        "-f",
        "--frequency",
        dest="inputfreq",
        metavar="FREQ",
        type=parse_frequency,
        default=None,
        help="RF sampling frequency in the source (default: 40MHz)",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="include decoder diagnostics on stderr"
    )
    parser.add_argument("--version", action="version", version=__version__)
    return parser


def main(args=None):
    """Command-line entry point. Return a shell-friendly result status."""

    parser = _build_parser()
    parsed = parser.parse_args(args)
    if parsed.pal and (parsed.ntsc or parsed.ntscj):
        parser.error("can only be PAL or NTSC")
    if parsed.ntsc and parsed.ntscj:
        parser.error("can only be NTSC or NTSC-J")

    system = "PAL" if parsed.pal else "NTSC"

    def report(message):
        print("ld-find-start: {0}".format(message), file=sys.stderr)

    try:
        result = find_start(
            parsed.infile,
            system=system,
            inputfreq=parsed.inputfreq,
            max_search_seconds=parsed.max_search,
            pre_roll_search_seconds=parsed.pre_roll_search,
            report=report,
            verbose=parsed.verbose,
        )
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as error:
        print("ld-find-start: ERROR: {0}".format(error), file=sys.stderr)
        return 1

    if result is None:
        print(
            "ld-find-start: no qualifying programme start found within the search limit",
            file=sys.stderr,
        )
        return 1

    argument = "--start {0}".format(result.file_frame)
    if result.confidence == "vbi":
        print(argument)
        print(
            "ld-find-start: found {0} run at file frame {1} "
            "(sample {2}, searched {3:.2f}s)".format(
                result.disk_type,
                result.file_frame,
                result.readloc,
                result.searched_seconds,
            ),
            file=sys.stderr,
        )
        return 0

    print(
        "ld-find-start: WARNING: no advancing CAV/CLV VBI run; "
        "guarded stable-video candidate is {0} (sample {1})".format(
            argument, result.readloc
        ),
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
