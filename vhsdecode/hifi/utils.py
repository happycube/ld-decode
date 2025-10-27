from multiprocessing.shared_memory import SharedMemory
from numba import njit
import numba
import numpy as np
from dataclasses import dataclass

import string
from random import SystemRandom

from cProfile import Profile
from pstats import SortKey, Stats

BLOCK_DTYPE = np.int16
REAL_DTYPE = np.float32
ALIGNMENT = 64

NumbaAudioArray = numba.types.Array(numba.types.float32, 1, "C", aligned=True)
NumbaBlockArray = numba.types.Array(numba.types.int16, 1, "C", aligned=True)


@dataclass
class DecoderState:
    def __init__(self, decoder, buffer_name, block_frames_read, block_size, block_num, is_last_block):
        block_sizes = decoder.set_block_sizes(block_size)
        block_overlap = decoder.get_block_overlap()

        self.name = buffer_name
        self.block_num = block_num
        self.is_last_block = is_last_block

        # block data for input rf
        self.block_frames_read = block_frames_read
        self.block_dtype = np.int16
        self.block_size = block_sizes["block_size"]
        self.block_overlap = block_overlap["block_overlap"]
        self.block_read_overlap = block_overlap["block_read_overlap"]

        # block data for demodulated audio @ 192000Hz
        self.audio_dtype = REAL_DTYPE
        self.block_audio_size = block_sizes["block_audio_size"]

        # block data for resampled audio @ user set audio rate
        self.block_audio_final_size = block_sizes["block_audio_final_size"]
        self.block_audio_final_overlap = block_overlap["block_audio_final_overlap"]

    name: str
    block_num: int
    is_last_block: bool

    block_frames_read: int
    block_dtype: np.dtype
    block_size: int
    block_overlap: int
    block_read_overlap: int

    audio_dtype: np.dtype
    block_audio_size: int

    block_audio_final_size: int
    block_audio_final_overlap: int
        
    @property
    def block_audio_final_len(self):
        if self.is_last_block:
            # shrink the final stereo output to only include the actual frames read, and the overlap that would have been used for the next block
            rf_rate_to_final_rate_ratio = self.block_size / self.block_audio_final_size
            audio_size = round(self.block_frames_read / rf_rate_to_final_rate_ratio)
            return max(50, audio_size + self.block_audio_final_overlap)
        else:
            # don't allow 0 or negative length audio, even if there's more overlap than actual audio
            return max(50, self.block_audio_final_size - self.block_audio_final_overlap * 2)


def to_aligned_offset(size):
    alignment = ALIGNMENT
    offset = size % alignment
    aligned_size = 0 if offset == 0 else alignment - offset
    return size + aligned_size


class PostProcessorSharedMemory:
    def __init__(self, decoder_state: DecoderState):
        self.shared_memory = SharedMemory(name=decoder_state.name)

        self.size = self.shared_memory.size
        self.buf = self.shared_memory.buf
        self.name = self.shared_memory.name
        self.close = self.shared_memory.close
        self.unlink = self.shared_memory.unlink

        self.audio_dtype = decoder_state.audio_dtype
        self.channel_len = decoder_state.block_audio_final_len
        self.audio_dtype_item_size = np.dtype(self.audio_dtype).itemsize

        ### Post Processing Memory
        # |--pre_left--|--pre_right--|--post_left--|--post_right--|
        # |-----------stereo---------|

        # pre left
        self.l_pre_offset = 0
        self.l_pre_len = self.channel_len
        self.l_pre_bytes = self.l_pre_len * self.audio_dtype_item_size
        # pre right
        self.r_pre_offset = to_aligned_offset(self.l_pre_offset + self.l_pre_bytes)
        self.r_pre_len = self.channel_len
        self.r_pre_bytes = self.r_pre_len * self.audio_dtype_item_size

        # overlaps with pre
        ## stereo out
        self.stereo_offset = 0
        self.stereo_len = self.channel_len * 2
        self.stereo_bytes = self.stereo_len * self.audio_dtype_item_size

        ## noise reduction out
        # left
        self.l_post_offset = to_aligned_offset(
            max(
                self.stereo_offset + self.stereo_bytes,
                self.r_pre_offset + self.r_pre_bytes,
            )
        )
        self.l_post_len = self.channel_len
        self.l_post_bytes = self.l_post_len * self.audio_dtype_item_size
        # right
        self.r_post_offset = to_aligned_offset(self.l_post_offset + self.l_post_bytes)
        self.r_post_len = self.channel_len
        self.r_post_bytes = self.r_post_len * self.audio_dtype_item_size

    @staticmethod
    def get_shared_memory(channel_size, name, audio_dtype=REAL_DTYPE):
        byte_size = (
            to_aligned_offset(channel_size * np.dtype(audio_dtype).itemsize * 4)
            + ALIGNMENT * 16
        )

        # allow more than one instance to run at a time
        system_random = SystemRandom()
        name += "_" + "".join(
            system_random.choice(string.ascii_lowercase + string.digits)
            for _ in range(8)
        )

        # this instance must be saved in a variable that persists on both processes
        # Windows will remove the shared memory if it garbage collects the handle in any of the processes it is open in
        # https://stackoverflow.com/a/63717188
        return SharedMemory(size=byte_size, name=name, create=True)

    def get_pre_left(self) -> np.array:
        return np.ndarray(
            self.l_pre_len,
            dtype=self.audio_dtype,
            offset=self.l_pre_offset,
            buffer=self.buf,
        )

    def get_pre_right(self) -> np.array:
        return np.ndarray(
            self.r_pre_len,
            dtype=self.audio_dtype,
            offset=self.r_pre_offset,
            buffer=self.buf,
        )

    # overlaps with the pre audio
    def get_stereo(self) -> np.array:
        return np.ndarray(
            self.stereo_len,
            dtype=self.audio_dtype,
            offset=self.stereo_offset,
            buffer=self.buf,
        )

    def get_post_left(self) -> np.array:
        return np.ndarray(
            self.l_post_len,
            dtype=self.audio_dtype,
            offset=self.l_post_offset,
            buffer=self.buf,
        )

    def get_post_right(self) -> np.array:
        return np.ndarray(
            self.r_post_len,
            dtype=self.audio_dtype,
            offset=self.r_post_offset,
            buffer=self.buf,
        )


class DecoderSharedMemory:
    def __init__(self, decoder_state: DecoderState):
        self.shared_memory = SharedMemory(name=decoder_state.name)

        self.size = self.shared_memory.size
        self.buf = self.shared_memory.buf
        self.name = self.shared_memory.name
        self.close = self.shared_memory.close
        self.unlink = self.shared_memory.unlink

        self.block_dtype = decoder_state.block_dtype
        self.block_dtype_item_size = np.dtype(self.block_dtype).itemsize

        self.audio_dtype = decoder_state.audio_dtype
        self.audio_dtype_item_size = np.dtype(self.audio_dtype).itemsize

        self.block_audio_final_len = decoder_state.block_audio_final_len

        ### Decoder Memory
        # -------------------------------raw_data-------------------------------|
        # RF data is demodulated and raw data can be discarded
        # Output audio data overwrites where the raw data was
        # |--pre_left--|--pre_right--|-------------------empty------------------|
        # |--pre_left--|--pre_right--|-------------------empty------------------|

        ## raw data in
        # first overlap
        self.block_start_overlap_offset = 0
        self.block_start_overlap_len = decoder_state.block_read_overlap
        self.block_start_overlap_bytes = (
            self.block_start_overlap_len * self.block_dtype_item_size
        )
        # block data
        self.block_frames_read = decoder_state.block_frames_read
        self.block_offset = (
            self.block_start_overlap_offset + self.block_start_overlap_bytes
        )
        self.block_len = decoder_state.block_size - (
            decoder_state.block_read_overlap * 2
        )
        self.block_bytes = self.block_len * self.block_dtype_item_size
        # second overlap
        self.block_end_overlap_offset = self.block_offset + self.block_bytes
        self.block_end_overlap_len = decoder_state.block_read_overlap
        self.block_end_overlap_bytes = (
            self.block_end_overlap_len * self.block_dtype_item_size
        )

        # pre left
        self.l_pre_offset = 0
        self.l_pre_len = self.block_audio_final_len
        self.l_pre_bytes = self.l_pre_len * self.audio_dtype_item_size
        # pre right
        self.r_pre_offset = to_aligned_offset(self.l_pre_offset + self.l_pre_bytes)
        self.r_pre_len = self.block_audio_final_len
        self.r_pre_bytes = self.r_pre_len * self.audio_dtype_item_size

    @staticmethod
    def get_shared_memory(
        block_size,
        block_overlap,
        block_audio_final_size,
        name,
        block_dtype=np.int16,
        audio_dtype=REAL_DTYPE,
    ):
        max_audio_size = (
            block_audio_final_size + to_aligned_offset(block_audio_final_size)
        ) * np.dtype(audio_dtype).itemsize
        block_size = (block_size + block_overlap * 2) * np.dtype(block_dtype).itemsize

        byte_size = max(max_audio_size, block_size)

        # allow more than one instance to run at a time
        system_random = SystemRandom()
        name += "_" + "".join(
            system_random.choice(string.ascii_lowercase + string.digits)
            for _ in range(8)
        )

        # this instance must be saved in a variable that persists on both processes
        # Windows will remove the shared memory if it garbage collects the handle in any of the processes it is open in
        # https://stackoverflow.com/a/63717188
        return SharedMemory(size=byte_size, name=name, create=True)

    ## Decoder methods

    # block data with start and end overlap included
    def get_block(self) -> np.array:
        return np.ndarray(
            self.block_start_overlap_len + self.block_len + self.block_end_overlap_len,
            dtype=self.block_dtype,
            offset=self.block_start_overlap_offset,
            buffer=self.buf,
        )
    
    # block data only including the data that was read
    def get_last_block(self) -> np.array:
        return np.ndarray(
            self.block_start_overlap_len + self.block_frames_read,
            dtype=self.block_dtype,
            offset=self.block_start_overlap_offset,
            buffer=self.buf,
        )

    # block starts after first overlap, goes until the end of the last overlap
    # first part of the block is copied from the previous read
    def get_block_in(self) -> np.array:
        return np.ndarray(
            self.block_len + self.block_end_overlap_len,
            dtype=self.block_dtype,
            offset=self.block_offset,
            buffer=self.buf,
        )

    # end overlap is copied into the start overlap
    def get_block_in_start_overlap(self) -> np.array:
        return np.ndarray(
            self.block_start_overlap_len,
            dtype=self.block_dtype,
            offset=self.block_start_overlap_offset,
            buffer=self.buf,
        )

    # end overlap is copied and appended to the beginning of the next block
    def get_block_in_end_overlap(self) -> np.array:
        return np.ndarray(
            self.block_end_overlap_len,
            dtype=self.block_dtype,
            offset=self.block_end_overlap_offset,
            buffer=self.buf,
        )

    def get_pre_left(self) -> np.array:
        return np.ndarray(
            self.block_audio_final_len,
            dtype=self.audio_dtype,
            offset=self.l_pre_offset,
            buffer=self.buf,
        )

    def get_pre_right(self) -> np.array:
        return np.ndarray(
            self.block_audio_final_len,
            dtype=self.audio_dtype,
            offset=self.r_pre_offset,
            buffer=self.buf,
        )

    @staticmethod
    @njit(
        numba.types.void(NumbaAudioArray, NumbaAudioArray, numba.types.int64),
        cache=True,
        fastmath=True,
        nogil=True,
    )
    def copy_data_float32(src: np.array, dst: np.array, length: int):
        # ctypes.memmove(dst.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), src.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), length)
        for i in range(length):
            dst[i] = src[i]

    @staticmethod
    @njit(
        numba.types.void(
            numba.types.Array(numba.int16, 1, "C"),
            numba.types.Array(numba.int16, 1, "C"),
            numba.types.int64,
        ),
        cache=True,
        fastmath=True,
        nogil=True,
    )
    def copy_data_int16(src: np.array, dst: np.array, length: int):
        for i in range(length):
            dst[i] = src[i]

    @staticmethod
    @njit(
        numba.types.void(
            numba.types.Array(numba.int16, 1, "C"),
            numba.types.Array(numba.int16, 1, "C"),
            numba.types.int64,
            numba.types.int64,
        ),
        cache=True,
        fastmath=True,
        nogil=True,
    )
    def copy_data_dst_offset_int16(
        src: np.array, dst: np.array, dst_offset: int, length: int
    ):
        for i in range(length):
            dst[i + dst_offset] = src[i]

    @staticmethod
    @njit(
        numba.types.void(
            NumbaAudioArray,
            NumbaAudioArray,
            numba.types.int64,
            numba.types.int64,
        ),
        cache=True,
        fastmath=True,
        nogil=True,
    )
    def copy_data_dst_offset_float32(
        src: np.array, dst: np.array, dst_offset: int, length: int
    ):
        for i in range(length):
            dst[i + dst_offset] = src[i]

    @staticmethod
    @njit(
        numba.types.void(
            NumbaAudioArray, NumbaAudioArray, numba.types.int64, numba.types.int64
        ),
        cache=True,
        fastmath=True,
        nogil=True,
    )
    def copy_data_src_offset_float32(
        src: np.array, dst: np.array, src_offset: int, length: int
    ):
        for i in range(length):
            dst[i] = src[i + src_offset]


def profile(function) -> int:
    def run_profiler(*args, **kwarg):
        with Profile() as profiler:
            return_code = function(*args, **kwarg)
            (Stats(profiler).strip_dirs().sort_stats(SortKey.CUMULATIVE).print_stats())
        return return_code

    return run_profiler
