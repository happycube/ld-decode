import logging
import sys
import os

# Package-wide logger.  Assigned by LDdecode.__init__ (lddecode/decoder.py);
# read at call time by other modules via:
#     from . import utils_logging as logs
#     logs.logger.warning(...)
logger = None


def console_safe(text, stream):
    """``text`` as ``stream`` can write it.

    A Windows console writes in its code page (cp1252 and the like), which
    has no arrow, no Greek letter and no box-drawing character: a message
    holding one raised UnicodeEncodeError in the logging module, which
    printed a traceback in place of the message.  What the stream's encoding
    cannot hold is written as a backslash escape instead (``\u2192`` for an
    arrow); the rest is unchanged.  A stream without an encoding (a test's
    StringIO) gets the text as it is.
    """
    encoding = getattr(stream, "encoding", None)
    if not encoding:
        return text
    try:
        text.encode(encoding)
        return text
    except UnicodeEncodeError:
        return text.encode(encoding, errors="backslashreplace").decode(encoding)
    except LookupError:
        return text


def init_logging(outfile_name, columns=80):
    """ Sets up a logger with a logfile, status line, and stderr output

    Calling it again replaces what an earlier call set up, closing its log
    file, rather than adding a second set of handlers beside it.
    """

    statusWritten = False

    logger = logging.getLogger("lddecode")
    logger.setLevel(logging.DEBUG)

    for handler in list(logger.handlers):
        if getattr(handler, "_from_init_logging", False):
            logger.removeHandler(handler)
            handler.close()

    class StreamHandlerR(logging.StreamHandler):
        def __init__(self):
            super().__init__()

        def format(self, record):
            # Written in what the console can show (see console_safe).
            return console_safe(super().format(record), self.stream)

        def emit(self, record):
            nonlocal statusWritten

            if statusWritten:
                print()
                super().emit(record)
                sys.stdout.flush()
                statusWritten = False
            else:
                super().emit(record)

    logger_stderr = StreamHandlerR()
    logger_stderr.setLevel(logging.INFO)
    logger_stderr._from_init_logging = True

    logger.addHandler(logger_stderr)

    if outfile_name is not None:
        # Delete old logfile if it exists
        try:
            os.unlink(outfile_name)
        except (OSError, FileNotFoundError):
            pass

        # UTF-8 whatever the platform: the log file holds every message as
        # written, where the locale's code page (cp1252 on Windows) could not.
        logger_file = logging.FileHandler(outfile_name, encoding="utf-8")
        logger_file.setLevel(logging.DEBUG)

        logger_fileformatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        logger_file.setFormatter(logger_fileformatter)
        logger_file._from_init_logging = True

        logger.addHandler(logger_file)

    def status(line):
        nonlocal statusWritten

        print(console_safe(line + " " * (columns - len(line)), sys.stdout), end="\r")
        logger.debug(line)
        statusWritten = True

    logger.status = status

    return logger


def logging_test():
    import os
    import time
    import tempfile

    fname = os.path.join(tempfile.gettempdir(), "logtest.log")
    print("Writing to " + fname, file=sys.stderr)

    print("Logging test beginning:")
    logger = init_logging(fname)

    logger.debug("logger.debug")
    logger.status("Status line 1 - a bit longer than 2")
    time.sleep(1)
    logger.status("Status line 2")
    logger.info("logger.info")
    logger.status("Status line 3")
    logger.info("end info")

    print("Logfile output:")
    with open(fname, "r", encoding="utf-8") as fp:
        for line in fp.readlines():
            print(line, end="")


if __name__ == "__main__":
    # execute only if run as a script, for testing
    logging_test()
