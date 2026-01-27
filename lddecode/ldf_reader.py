"""
ld-ldf-reader-py - LDF reader tool for ld-decode (Python implementation)

SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileCopyrightText: 2019-2021 Chad Page
SPDX-FileCopyrightText: 2020-2022 Adam Sampson
SPDX-FileCopyrightText: 2025 Simon Inns
SPDX-FileCopyrightText: 2026 Python implementation

This is a Python reimplementation of the C++ ld-ldf-reader tool.
It uses FFmpeg's Python bindings (av library) to decode audio from LDF files.

This file is part of ld-decode-tools.
"""

import sys
import os
import argparse
from pathlib import Path

try:
    import av
except ImportError:
    print("Error: PyAV library not found. Install with: pip install av", file=sys.stderr)
    sys.exit(1)


class LdfReader:
    """LDF reader that decodes audio from LDF files using FFmpeg"""

    def __init__(self, input_filename, start_offset=0, debug=True):
        """
        Initialize the LDF reader.
        
        Args:
            input_filename: Path to input LDF file
            start_offset: Start offset in samples (default: 0)
            debug: Enable debug output (default: True)
        """
        self.input_filename = input_filename
        self.start_offset = start_offset
        self.debug = debug
        self.container = None
        self.audio_stream = None

    def process(self):
        """
        Process the LDF file and write decoded audio to stdout.
        
        Returns:
            bool: True if successful, False otherwise
        """
        if self.debug:
            print(f"Processing LDF file: {self.input_filename}", file=sys.stderr)
            if self.start_offset > 0:
                print(f"Start offset: {self.start_offset} samples", file=sys.stderr)

        # Check if input file exists
        if not Path(self.input_filename).exists():
            print(f"Input file does not exist: {self.input_filename}", file=sys.stderr)
            return False

        # Set stdout to binary mode on Windows
        if sys.platform == 'win32':
            import msvcrt
            msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)

        try:
            # Open input file
            if not self._open_file():
                return False

            # Find and open audio codec
            if not self._open_codec_context():
                return False

            # Display stream information
            if self.debug:
                print(f"Sample rate: {self.audio_stream.sample_rate} Hz", file=sys.stderr)
                if self.container.duration is not None:
                    print(f"Duration: {self.container.duration} μs", file=sys.stderr)

            # Seek to start position if specified
            if self.start_offset > 0:
                try:
                    seek_seconds = self.start_offset / self.audio_stream.sample_rate
                    # Seek to slightly before the target to ensure we get the right position
                    seek_time = int((seek_seconds - 1) * av.time_base)
                    if seek_time < 0:
                        seek_time = 0
                    self.container.seek(seek_time, any_frame=True)
                except Exception as e:
                    if self.debug:
                        print(f"Seek failed, starting from beginning: {e}", file=sys.stderr)
                    self.start_offset = 0

            # Decode and write frames
            if not self._decode_packets():
                return False

            # Flush stdout
            sys.stdout.flush()

            if self.debug:
                print("LDF reading completed successfully", file=sys.stderr)
            return True

        except Exception as e:
            print(f"Error during processing: {e}", file=sys.stderr)
            return False
        finally:
            self._cleanup()

    def _open_file(self):
        """
        Open input file and allocate format context.
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            self.container = av.open(self.input_filename)
            return True
        except Exception as e:
            print(f"Could not open source file: {self.input_filename} Error: {e}", file=sys.stderr)
            return False

    def _open_codec_context(self):
        """
        Find and open the best audio stream.
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Find the best audio stream
            audio_streams = [s for s in self.container.streams if s.type == 'audio']
            if not audio_streams:
                print(f"Could not find audio stream in input file: {self.input_filename}", file=sys.stderr)
                return False

            self.audio_stream = audio_streams[0]
            return True
        except Exception as e:
            print(f"Failed to open audio codec: {e}", file=sys.stderr)
            return False

    def _decode_packets(self):
        """
        Decode packets and write audio data to stdout.
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            samples_written = 0
            resampler = av.audio.resampler.AudioResampler(format='s16', layout='mono')
            
            # Demux and decode frames
            for frame in self.container.decode(audio=0):
                if frame is None:
                    continue

                # Calculate the current sample position (PTS in samples)
                # frame.pts is in stream time_base units
                if frame.pts is not None:
                    current_pts = int(frame.pts * self.audio_stream.time_base * self.audio_stream.sample_rate)
                else:
                    current_pts = samples_written

                # If we haven't reached the start position, skip this frame
                if current_pts + frame.samples <= self.start_offset:
                    continue

                # Calculate offset within the frame if we're starting mid-frame
                offset_samples = max(0, self.start_offset - current_pts)
                
                # Convert frame to bytes (signed 16-bit little-endian format - s16le)
                # Use resampler to convert to s16 mono format
                frame_resampled = resampler.resample(frame)
                
                for resampled_frame in frame_resampled:
                    # Get the raw audio data from the first plane
                    audio_data = bytes(resampled_frame.planes[0])
                    
                    # Calculate byte offset (2 bytes per sample for s16)
                    byte_offset = offset_samples * 2
                    
                    # Write to stdout
                    if byte_offset < len(audio_data):
                        data_to_write = audio_data[byte_offset:]
                        written = sys.stdout.buffer.write(data_to_write)
                        if written != len(data_to_write):
                            print(f"Write error at offset: {byte_offset}", file=sys.stderr)
                            return False
                        samples_written += (written // 2)
                    
                    # Reset offset after first frame
                    offset_samples = 0

            return True
        except Exception as e:
            print(f"Error during decoding: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc(file=sys.stderr)
            return False

    def _cleanup(self):
        """Clean up resources"""
        if self.container is not None:
            self.container.close()
            self.container = None
        self.audio_stream = None


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='ld-ldf-reader-py - LDF reader tool for ld-decode (Python implementation)\n\n'
                    '(c)2019-2021 Chad Page\n'
                    '(c)2020-2022 Adam Sampson\n'
                    '(c)2025 Simon Inns\n'
                    '(c)2026 Python implementation\n'
                    'GPLv3 Open-Source - github: https://github.com/happycube/ld-decode',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        '-s', '--start-offset',
        type=int,
        default=0,
        metavar='samples',
        help='Start offset in samples (default: 0)'
    )
    
    parser.add_argument(
        '-q', '--quiet',
        action='store_true',
        help='Suppress debug output'
    )
    
    parser.add_argument(
        'input',
        help='Input LDF file'
    )
    
    args = parser.parse_args()
    
    # Validate start offset
    if args.start_offset < 0:
        print("Start offset must be a non-negative integer", file=sys.stderr)
        return 1
    
    # Create reader and process
    reader = LdfReader(
        args.input,
        start_offset=args.start_offset,
        debug=not args.quiet
    )
    
    if not reader.process():
        return 1
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
