import numpy as np


def gen_wave_at_frequency(frequency, sample_frequency, num_samples, gen_func=np.sin):
    """Generate a sine wave with the specified parameters."""
    samples = np.arange(num_samples)
    wave_scale = frequency / sample_frequency
    return gen_func(2 * np.pi * wave_scale * samples)


def gen_compl_wave_at_frequency(frequency, sample_frequency, num_samples):
    """Generate a sine wave with the specified parameters."""
    samples = np.arange(num_samples)
    wave_scale = frequency / sample_frequency
    return np.exp(-2 * np.pi * wave_scale * samples * 1j)
