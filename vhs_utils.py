import numpy as np

def gen_wave_at_frequency(frequency, sample_frequency, num_samples):
    """Generate a sine wave with the specified parameters."""
    samples = np.arange(num_samples)
    wave_scale = frequency / sample_frequency
    return np.sin(2 * np.pi * wave_scale * samples)
