from multiprocessing.shared_memory import SharedMemory
from numba import njit, prange
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

NumbaAudioArray = numba.types.Array(numba.types.float32, 1, "C")
NumbaBlockArray = numba.types.Array(numba.types.int16, 1, "C")

@dataclass
class DecoderState:
    def __init__(self, decoder, buffer_name, block_len, block_num, is_last_block):
        block_sizes = decoder.set_block_sizes(block_len, is_last_block)

        self.name = buffer_name
        self.block_num = block_num
        self.is_last_block = is_last_block
        self.pre_audio_len = block_sizes["block_audio_len"]
        self.pre_audio_trimmed = block_sizes["block_audio_len"]
        self.post_audio_len = block_sizes["block_audio_final_len"]
        self.post_audio_trimmed = block_sizes["block_audio_final_len"]
        self.stereo_audio_len = block_sizes["block_audio_final_len"] * 2
        self.stereo_audio_trimmed = block_sizes["block_audio_final_len"] * 2
        self.block_len = block_sizes["block_len"]
        self.block_overlap = block_sizes["block_overlap"]
        self.block_resampled_len = block_sizes["block_resampled_len"]
        self.block_resampled_trimmed = block_sizes["block_resampled_len"]
        self.block_audio_final_overlap = block_sizes["block_audio_final_overlap"]
        self.block_dtype = np.int16
        self.audio_dtype = REAL_DTYPE

    name: str
    block_num: int
    is_last_block: bool
    pre_audio_len: int
    pre_audio_trimmed: int
    post_audio_len: int
    post_audio_trimmed: int
    stereo_audio_len: int
    stereo_audio_trimmed: int
    block_len: int
    block_overlap: int
    block_resampled_len: int
    block_resampled_trimmed: int
    block_audio_final_overlap: int
    block_dtype: np.dtype
    audio_dtype: np.dtype

def to_aligned_offset(size):
    alignment = ALIGNMENT
    offset = size % alignment
    aligned_size = 0 if offset == 0 else alignment - offset
    return size + aligned_size

def get_aligned_address(variable):
    address = id(variable)
    aligned_address = to_aligned_offset(address)
    return address, aligned_address
    
class PostProcessorSharedMemory():
    def __init__(
            self,
            decoder_state: DecoderState
        ):
        self.shared_memory = SharedMemory(name=decoder_state.name)

        self.size = self.shared_memory.size
        self.buf = self.shared_memory.buf
        self.name = self.shared_memory.name
        self.close = self.shared_memory.close
        self.unlink = self.shared_memory.unlink

        self.audio_dtype = decoder_state.audio_dtype
        self.channel_len = decoder_state.post_audio_len
        self.audio_dtype_item_size = np.dtype(self.audio_dtype).itemsize

        ### Post Processing Memory
        # |--pre_left--|--pre_right--|--nr_left--|--nr_right--|
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
        self.l_nr_offset = to_aligned_offset(max(self.stereo_offset + self.stereo_bytes, self.r_pre_offset + self.r_pre_bytes))
        self.l_nr_len = self.channel_len
        self.l_nr_bytes = self.l_nr_len * self.audio_dtype_item_size
        # right
        self.r_nr_offset = to_aligned_offset(self.l_nr_offset + self.l_nr_bytes)
        self.r_nr_len = self.channel_len
        self.r_nr_bytes = self.r_nr_len * self.audio_dtype_item_size

            
    @staticmethod
    def get_shared_memory(channel_len, name, audio_dtype=REAL_DTYPE):
        byte_size = to_aligned_offset(channel_len * np.dtype(audio_dtype).itemsize * 4) + ALIGNMENT * 16

        # allow more than one instance to run at a time
        system_random = SystemRandom()
        name += "_" + ''.join(system_random.choice(string.ascii_lowercase + string.digits) for _ in range(8))

        # this instance must be saved in a variable that persists on both processes
        # Windows will remove the shared memory if it garbage collects the handle in any of the processes it is open in
        # https://stackoverflow.com/a/63717188
        return SharedMemory(size=byte_size, name=name, create=True)

    def get_pre_left(self) -> np.array:
        return np.ndarray(self.l_pre_len, dtype=self.audio_dtype, offset=self.l_pre_offset, buffer=self.buf)
    
    def get_pre_right(self) -> np.array:
        return np.ndarray(self.r_pre_len, dtype=self.audio_dtype, offset=self.r_pre_offset, buffer=self.buf)

    # overlaps with the pre audio
    def get_stereo(self) -> np.array:
        return np.ndarray(self.stereo_len, dtype=self.audio_dtype, offset=self.stereo_offset, buffer=self.buf)
    
    def get_nr_left(self) -> np.array:
        return np.ndarray(self.l_nr_len, dtype=self.audio_dtype, offset=self.l_nr_offset, buffer=self.buf)
    
    def get_nr_right(self) -> np.array:
        return np.ndarray(self.r_nr_len, dtype=self.audio_dtype, offset=self.r_nr_offset, buffer=self.buf)
    
    
    
class DecoderSharedMemory():
    def __init__(
            self,
            decoder_state: DecoderState
        ):
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

        self.block_resampled_trimmed = decoder_state.block_resampled_trimmed
        self.pre_audio_trimmed = decoder_state.pre_audio_trimmed
        self.post_audio_trimmed = decoder_state.post_audio_trimmed
        self.stereo_audio_trimmed = decoder_state.stereo_audio_trimmed

        ### Decoder Memory
        # |--pre_left--|--pre_right--|-------------------------------raw_data-------------------------------|
        # |--pre_left--|--pre_right--|----------------------------block_resampled---------------------------|

        # pre left
        self.l_pre_offset = 0
        self.l_pre_len = decoder_state.pre_audio_len
        self.l_pre_bytes = self.l_pre_len * self.audio_dtype_item_size
        # pre right
        self.r_pre_offset = to_aligned_offset(self.l_pre_offset + self.l_pre_bytes)
        self.r_pre_len = decoder_state.pre_audio_len
        self.r_pre_bytes = self.r_pre_len * self.audio_dtype_item_size

        ## raw data in
        # first overlap
        self.block_start_overlap_offset = to_aligned_offset(self.r_pre_offset + self.r_pre_bytes)
        self.block_start_overlap_len = decoder_state.block_overlap
        self.block_start_overlap_bytes = self.block_start_overlap_len * self.block_dtype_item_size
        # block data
        self.block_offset = self.block_start_overlap_offset + self.block_start_overlap_bytes
        self.block_len = decoder_state.block_len - decoder_state.block_overlap
        self.block_bytes = self.block_len * self.block_dtype_item_size
        # second overlap
        self.block_end_overlap_offset = self.block_offset + self.block_bytes
        self.block_end_overlap_len = decoder_state.block_overlap
        self.block_end_overlap_bytes = self.block_end_overlap_len * self.block_dtype_item_size

    @staticmethod
    def get_shared_memory(block_len, block_overlap, block_resampled_len, pre_audio_len, name, block_dtype=np.int16, audio_dtype=REAL_DTYPE):
        max_audio_size = (pre_audio_len * np.dtype(audio_dtype).itemsize) * 6
        block_size_with_audio = (
            to_aligned_offset(block_len * np.dtype(block_dtype).itemsize) + 
            to_aligned_offset(block_overlap * np.dtype(block_dtype).itemsize) * 2 + 
            to_aligned_offset(pre_audio_len * np.dtype(audio_dtype).itemsize) * 2
        )
        resampled_size_with_audio = (
            to_aligned_offset(block_resampled_len * np.dtype(audio_dtype).itemsize) + 
            to_aligned_offset(pre_audio_len * np.dtype(audio_dtype).itemsize) * 2
        )

        byte_size = max(max_audio_size, block_size_with_audio, resampled_size_with_audio) + ALIGNMENT * 16

        # allow more than one instance to run at a time
        system_random = SystemRandom()
        name += "_" + ''.join(system_random.choice(string.ascii_lowercase + string.digits) for _ in range(8))

        # this instance must be saved in a variable that persists on both processes
        # Windows will remove the shared memory if it garbage collects the handle in any of the processes it is open in
        # https://stackoverflow.com/a/63717188
        return SharedMemory(size=byte_size, name=name, create=True)
    

    # |00|000000000000000|00|                  |11|222222222222222222|22|                  |33|4444444444444444444|44|
    #                    |00|111111111111111111|11|                  |22|333333333333333333|33|
    # S                     1                     2                     3                     4                      E

    ## Decoder methods
    
    # block data with start and end overlap included
    def get_block(self) -> np.array:
        return np.ndarray(self.block_start_overlap_len + self.block_len + self.block_end_overlap_len, dtype=self.block_dtype, offset=self.block_start_overlap_offset, buffer=self.buf)
    
    # first block includes start since there is no overlap
    def get_first_block_in(self) -> np.array:
        return self.get_block()

    # block starts after first overlap, goes until after the last overlap
    # first part of the block is copied from the previous read
    def get_block_in(self) -> np.array:
        return np.ndarray(self.block_len + self.block_end_overlap_len, dtype=self.block_dtype, offset=self.block_offset, buffer=self.buf)
    
    # end overlap is copied into the start overlap
    def get_block_in_start_overlap(self) -> np.array:
        return np.ndarray(self.block_start_overlap_len, dtype=self.block_dtype, offset=self.block_start_overlap_offset, buffer=self.buf)
    
    # end overlap is copied and appended to the beginning of the next block
    def get_block_in_end_overlap(self) -> np.array:
        return np.ndarray(self.block_end_overlap_len, dtype=self.block_dtype, offset=self.block_end_overlap_offset, buffer=self.buf)
    
    def get_pre_left(self) -> np.array:
        return np.ndarray(self.pre_audio_trimmed, dtype=self.audio_dtype, offset=self.l_pre_offset, buffer=self.buf)
    
    def get_pre_right(self) -> np.array:
        return np.ndarray(self.pre_audio_trimmed, dtype=self.audio_dtype, offset=self.r_pre_offset, buffer=self.buf)
    
    @staticmethod
    @njit(numba.types.void(NumbaAudioArray, NumbaAudioArray, numba.types.int64), cache=True, fastmath=True, nogil=True)
    def copy_data_float32(src: np.array, dst: np.array, length: int):
        for i in range(length):
            dst[i] = src[i]

    @staticmethod
    @njit(numba.types.void(numba.types.Array(numba.int16, 1, "C"), numba.types.Array(numba.int16, 1, "C"), numba.types.int64), cache=True, fastmath=True, nogil=True)
    def copy_data_int16(src: np.array, dst: np.array, length: int):
        for i in range(length):
            dst[i] = src[i]

    @staticmethod
    @njit(numba.types.void(NumbaAudioArray, NumbaAudioArray, numba.types.int64, numba.types.int64), cache=True, fastmath=True, nogil=True)
    def copy_data_src_offset_float32(src: np.array, dst: np.array, src_offset: int, length: int):
        for i in range(length):
            dst[i] = src[i+src_offset]


def profile(function) -> int:
    def run_profiler(*args, **kwarg):
        with Profile() as profiler:
            return_code = function(*args, **kwarg)
            (
                Stats(profiler)
                .strip_dirs()
                .sort_stats(SortKey.CUMULATIVE)
                .print_stats()
            )
        return return_code
    return run_profiler