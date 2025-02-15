from multiprocessing.shared_memory import SharedMemory
from numba import njit, prange
import numpy as np

import string
from random import SystemRandom

REAL_DTYPE = np.float32


class DecoderSharedMemory():
    def __init__(
            self,
            buffer_params
        ):

        name = buffer_params["name"]
        pre_audio_len = buffer_params["pre_audio_len"]
        pre_audio_trimmed = buffer_params["pre_audio_trimmed"]
        post_audio_len = buffer_params["post_audio_len"]
        post_audio_trimmed = buffer_params["post_audio_trimmed"]
        stereo_audio_len = buffer_params["stereo_audio_len"]
        stereo_audio_trimmed = buffer_params["stereo_audio_trimmed"]
        block_len = buffer_params["block_len"]
        block_resampled_len = buffer_params["block_resampled_len"]
        block_resampled_trimmed = buffer_params["block_resampled_trimmed"]
       
        block_dtype = buffer_params["block_dtype"]
        audio_dtype = buffer_params["audio_dtype"]

        self.shared_memory = SharedMemory(name=name)

        self.size = self.shared_memory.size
        self.buf = self.shared_memory.buf
        self.name = self.shared_memory.name
        self.close = self.shared_memory.close
        self.unlink = self.shared_memory.unlink

        self.block_dtype = block_dtype
        self.block_dtype_item_size = np.dtype(self.block_dtype).itemsize

        self.audio_dtype = audio_dtype
        self.audio_dtype_item_size = np.dtype(self.audio_dtype).itemsize

        self.block_resampled_trimmed = block_resampled_trimmed
        self.pre_audio_trimmed = pre_audio_trimmed
        self.post_audio_trimmed = post_audio_trimmed
        self.stereo_audio_trimmed = stereo_audio_trimmed

        ### Decoder Memory
        # |--pre_left--|--pre_right--|-------------------------------raw_data-------------------------------|
        # |--pre_left--|--pre_right--|----------------------------block_resampled---------------------------|

        # pre left
        self.l_pre_offset = 0
        self.l_pre_len = pre_audio_len
        self.l_pre_bytes = self.l_pre_len * self.audio_dtype_item_size
        # pre right
        self.r_pre_offset = self.l_pre_offset + self.l_pre_bytes
        self.r_pre_len = pre_audio_len
        self.r_pre_bytes = self.r_pre_len * self.audio_dtype_item_size

        # raw data in
        self.block_offset = self.r_pre_offset + self.r_pre_bytes
        self.block_len = block_len
        self.block_bytes = self.block_len * self.block_dtype_item_size

        # resampled raw data
        self.block_resampled_offset = self.r_pre_offset + self.r_pre_bytes
        self.block_resampled_len = block_resampled_len
        self.block_resampled_bytes = self.block_resampled_len * self.audio_dtype_item_size

        ### Post Processing Memory (reuses raw data area)
        # |--pre_left--|--pre_right--|--stereo--|--nr_left--|--nr_right--|

        ## stereo out
        self.stereo_offset = self.block_offset
        self.stereo_len = stereo_audio_len
        self.stereo_bytes = self.stereo_len * self.audio_dtype_item_size

        ## noise reduction out
        # left
        self.l_nr_offset = self.stereo_offset + self.stereo_bytes
        self.l_nr_len = post_audio_len
        self.l_nr_bytes = self.l_nr_len * self.audio_dtype_item_size
        # right
        self.r_nr_offset = self.l_nr_offset + self.l_nr_bytes
        self.r_nr_len = post_audio_len
        self.r_nr_bytes = self.r_nr_len * self.audio_dtype_item_size


    @staticmethod
    def get_shared_memory(block_len, block_resampled_len, pre_audio_len, name, block_dtype=np.int16, audio_dtype=REAL_DTYPE):
        max_audio_size = pre_audio_len * 6 * np.dtype(audio_dtype).itemsize
        block_size_with_audio = (
            block_len * np.dtype(block_dtype).itemsize + 
            pre_audio_len * 2 * np.dtype(audio_dtype).itemsize
        )
        resampled_size_with_audio = (
            block_resampled_len * np.dtype(audio_dtype).itemsize + 
            pre_audio_len * 2 * np.dtype(audio_dtype).itemsize
        )

        byte_size = max(max_audio_size, block_size_with_audio, resampled_size_with_audio)
        # allow more than one instance to run at a time
        system_random = SystemRandom()
        name += "_" + ''.join(system_random.choice(string.ascii_lowercase + string.digits) for _ in range(8))

        # this instance must be saved in a variable that persists on both processes
        # Windows will remove the shared memory if it garbage collects the handle in any of the processes it is open in
        # https://stackoverflow.com/a/63717188
        return SharedMemory(size=byte_size, name=name, create=True)
    
    ## Decoder methods
    def get_block(self):
        return np.ndarray(self.block_len, dtype=self.block_dtype, offset=self.block_offset, buffer=self.buf)
    
    def get_block_resampled(self):
        return np.ndarray(self.block_resampled_trimmed, dtype=self.audio_dtype, offset=self.block_resampled_offset, buffer=self.buf)
    
    def get_pre_left(self):
        return np.ndarray(self.pre_audio_trimmed, dtype=self.audio_dtype, offset=self.l_pre_offset, buffer=self.buf)
    
    def get_pre_right(self):
        return np.ndarray(self.pre_audio_trimmed, dtype=self.audio_dtype, offset=self.r_pre_offset, buffer=self.buf)
    
    ## Post Processor methods
    def get_nr_left(self):
        return np.ndarray(self.post_audio_trimmed, dtype=self.audio_dtype, offset=self.l_nr_offset, buffer=self.buf)
    
    def get_nr_right(self):
        return np.ndarray(self.post_audio_trimmed, dtype=self.audio_dtype, offset=self.r_nr_offset, buffer=self.buf)
    
    def get_stereo(self):
        return np.ndarray(self.stereo_audio_trimmed, dtype=self.audio_dtype, offset=self.stereo_offset, buffer=self.buf)

    @staticmethod
    @njit(cache=True, fastmath=True, nogil=False, parallel=True)
    def copy_data(src: np.array, dst: np.array, offset:int, length: int):
        for i in prange(length):
            dst[i+offset] = src[i]
