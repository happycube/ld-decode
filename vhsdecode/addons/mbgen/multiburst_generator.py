# multiburst test card generator for VTR bandwidth testing

from struct import pack
from math import sin, pi
from argparse import ArgumentParser
from fractions import Fraction
from sys import version_info


def burst_frequencies():
    burst_freqs = list()
    phase = pi
    # format frequency (Hz), phase (radians)
    burst_freqs.append((500e3, phase))
    burst_freqs.append((1e6, phase))
    burst_freqs.append((2e6, phase))
    burst_freqs.append((3e6, phase))
    burst_freqs.append((3.58e6, phase))
    burst_freqs.append((4.2e6, phase))
    return burst_freqs


def rgb_white():
    return int(235)


def rgb_black():
    return int(16)


def burst_time():
    return 3 / burst_frequencies()[0][0]


def pattern_mode_d():
    return 0  # 0 grayscale, 1 red, 2 blue


def test_device_d():
    return 0  # 0 VTR, 1 CRT


def output_filename_d():
    return None


def output_scale_factor_d():
    return 1


def lines_per_frame_d():
    return 525  # NTSC specs


def aspect_d():
    return 4 / 3


def white_clip_d():
    return 70


def Fh():
    return 15.734e3


def black_clip_d():
    return 10


class Parameters:
    def __init__(self):
        self.args = self.argparser()

    def argparser(self):
        parser = ArgumentParser(description='Generates multiburst testing charts for video bandwidth testing')
        parser.add_argument('-l', '--lines', nargs='?', default=lines_per_frame_d(), type=int,
                            help='lines per frame (default %d)' % lines_per_frame_d())
        parser.add_argument('-s', '--scale', nargs='?', default=output_scale_factor_d(), type=float,
                            help='scale of the output image (default %d)' % output_scale_factor_d())
        parser.add_argument('-d', '--device', nargs='?', default=test_device_d(), type=int,
                            help='target device -> 0: VTR, 1: CRT monitor (default %d)' % test_device_d())
        parser.add_argument('-c', '--color', nargs='?', default=pattern_mode_d(), type=int,
                            help='color pattern -> 0: grayscale, 1: red, 2: blue (default %d)' % pattern_mode_d())
        parser.add_argument('-a', '--aspect', nargs='?', default=aspect_d(), type=float,
                            help='aspect ratio (default %f [%d:%d])' %
                                 (aspect_d(), Fraction(aspect_d()).limit_denominator(100).numerator,
                                  Fraction(aspect_d()).limit_denominator(100).denominator)
                            )
        parser.add_argument('-w', '--white', nargs='?', default=white_clip_d(), type=int,
                            help='white clip level (default %d IRE)' % white_clip_d())
        parser.add_argument('-b', '--black', nargs='?', default=black_clip_d(), type=int,
                            help='black clip level (default %d IRE)' % black_clip_d())
        parser.add_argument('-o', '--output', nargs='?', default=output_filename_d(), type=str,
                            help='write to file (default, %s)' % output_filename_d())

        return parser.parse_args()

    def pattern_mode(self):
        if self.args.color is None:
            return pattern_mode_d()
        else:
            return self.args.color

    def test_device(self):
        if self.args.device is None:
            return test_device_d()
        else:
            return self.args.device

    def output_filename(self):
        if self.args.output is None:
            return output_filename_d()
        else:
            return self.args.output

    def output_scale_factor(self):
        if self.args.scale is None:
            return output_scale_factor_d()
        else:
            return self.args.scale

    def lines_per_frame(self):
        if self.args.lines is None:
            return lines_per_frame_d()
        else:
            return self.args.lines

    def aspect(self):
        if self.args.aspect is None:
            return aspect_d()
        else:
            return self.args.aspect

    def white_clip(self):
        if self.args.white is None:
            return white_clip_d()
        else:
            return self.args.white

    def black_clip(self):
        if self.args.black is None:
            return black_clip_d()
        else:
            return self.args.black


# bitmap helper handler class
class Bitmap:

    def __init__(s, width, height):
        s._bfType = 19778  # Bitmap signature
        s._bfReserved1 = 0
        s._bfReserved2 = 0
        s._bcPlanes = 1
        s._bcSize = 12
        s._bcBitCount = 24
        s._bfOffBits = 26
        s._bcWidth = width
        s._bcHeight = height
        s._bfSize = 26 + s._bcWidth * 3 * s._bcHeight
        s.clear()

    def clear(s):
        s._graphics = [(0, 0, 0)] * s._bcWidth * s._bcHeight

    def setPixel(s, x, y, color):
        if isinstance(color, tuple):
            if x < 0 or y < 0 or x > s._bcWidth - 1 or y > s._bcHeight - 1:
                raise ValueError('Coords out of range')
            if len(color) != 3:
                raise ValueError('Color must be a tuple of 3 elems')
            s._graphics[y * s._bcWidth + x] = (color[2], color[1], color[0])
        else:
            raise ValueError('Color must be a tuple of 3 elems')

    def write(s, file):
        with open(file, 'wb') as f:
            f.write(pack('<HLHHL',
                         s._bfType,
                         s._bfSize,
                         s._bfReserved1,
                         s._bfReserved2,
                         s._bfOffBits))  # Writing BITMAPFILEHEADER
            f.write(pack('<LHHHH',
                         s._bcSize,
                         s._bcWidth,
                         s._bcHeight,
                         s._bcPlanes,
                         s._bcBitCount))  # Writing BITMAPINFO
            for px in s._graphics:
                f.write(pack('<BBB', *px))
            for i in range((4 - ((s._bcWidth * 3) % 4)) % 4):
                f.write(pack('B', 0))


class MultiBurst:

    def __init__(self, parameters):
        self.p = parameters
        self.b = Bitmap(self.frame_width(self.p.aspect()),
                        self.frame_height())
        self.tests()

    def __del__(self):
        try:
            if self.p.output_filename() is not None:
                out_filename = self.p.output_filename()
            else:
                out_filename = self.auto_filename()
            self.b.write(out_filename)
            print('%s written' % out_filename)
        except AttributeError:
            print('No file written')
        except IOError as e:
            print('Error writing file %s', e)

    def frame_height(self):
        return round(self.p.lines_per_frame() * self.p.output_scale_factor())

    def frame_width(self, aspect_ratio):
        return round(self.frame_height() * aspect_ratio)

    def auto_filename(self):
        if self.p.test_device() is 0:
            if self.p.pattern_mode() is 0:
                fname = 'VTR_test_multiburst.bmp'
            elif self.p.pattern_mode() is 1:
                fname = 'VTR_test_multiburst_red.bmp'
            else:
                fname = 'VTR_test_multiburst_blue.bmp'
        else:
            if self.p.pattern_mode() is 0:
                fname = 'CRT_test_multiburst.bmp'
            elif self.p.pattern_mode() is 1:
                fname = 'CRT_test_multiburst_red.bmp'
            else:
                fname = 'CRT_test_multiburst_blue.bmp'
        return fname

    def rgb_to_ire(self, value):
        assert 0 <= value <= 255, 'RGB value out of range %d (0~255)' % value
        if rgb_black() < value < rgb_white():
            scale = self.p.white_clip() / 100
            rgb_amp = scale * (rgb_white() - rgb_black())
            value -= rgb_black()
            ire_amp = self.p.white_clip() - self.p.black_clip()
            ire = self.p.black_clip() + (ire_amp * value / rgb_amp)
        elif value >= rgb_white():
            ire = self.p.white_clip()
        else:
            ire = self.p.black_clip()
        return ire

    def ire_to_rgb(self, value):
        assert 0 <= value <= 100, 'IRE value out of range %d (0~100)' % value
        if self.p.black_clip() < value <= self.p.white_clip():
            value -= self.p.black_clip()
            amp = self.p.white_clip() - self.p.black_clip()
            scale = self.p.white_clip() / 100
            rgb_amp = scale * (rgb_white() - rgb_black())
            rgb = int(rgb_black() + (rgb_amp * value / amp))
        elif value <= self.p.black_clip():
            rgb = rgb_black()
        else:
            rgb = rgb_white()
        return int(rgb)

    def burst(self, x, f):
        w = 2 * pi * f[0]
        t = burst_time() * x / self.burst_len()
        amp = self.p.white_clip() - self.p.black_clip()
        v = 0.5 * amp * sin(f[1] + (w * t))
        assert 0 <= v + amp / 2 <= amp, 'sine got negative'
        return self.ire_to_rgb(v + (amp / 2) + self.p.black_clip())

    def set_black_level(self, j):
        black = self.ire_to_rgb(self.p.black_clip())
        w = self.frame_width(self.p.aspect())
        for x in range(0, w):
            if self.p.pattern_mode() is 0:
                self.b.setPixel(x, j, (black, black, black))
            elif self.p.pattern_mode() is 1:
                self.b.setPixel(x, j, (black, 0, 0))
            else:
                self.b.setPixel(x, j, (black, 0, 0))

    def mid(self):
        amp = self.p.white_clip() - self.p.black_clip()
        return self.ire_to_rgb(self.p.black_clip() + amp / 2)

    def burst_len(self):
        line_time = 1 / Fh()
        hsync_pulses_time = line_time * 31 / 128
        return round(self.frame_width(self.p.aspect()) * burst_time() / (line_time - hsync_pulses_time))

    def gap(self):
        count = len(burst_frequencies()) + 1
        filler = self.frame_width(self.p.aspect()) - count * self.burst_len()
        return int(filler / count)

    def calibration_band(self, j):
        white = self.ire_to_rgb(self.p.white_clip())
        black = self.ire_to_rgb(self.p.black_clip())

        for x in range(0, int((self.burst_len() - self.gap()) / 2)):
            if self.p.pattern_mode() is 0:
                self.b.setPixel(x + self.gap(), j, (white, white, white))
            elif self.p.pattern_mode() is 1:
                self.b.setPixel(x + self.gap(), j, (white, black, black))
            else:
                self.b.setPixel(x + self.gap(), j, (black, black, white))

    def white_balance_pulses(self, j):
        if self.p.test_device() is 0:
            white = rgb_white()
            w = self.frame_width(self.p.aspect())

            for x in range(0, int(self.gap() / 4)):
                self.b.setPixel(x, j, (white, white, white))
            for x in range(int(self.gap() / 2), self.gap() - int(self.gap() / 4)):
                self.b.setPixel(x, j, (white, white, white))

            for x in range(w - self.gap(), w):
                self.b.setPixel(x, j, (white, white, white))

    def write_burst(self, j):
        index = 1
        w = self.frame_width(self.p.aspect())
        for freq in burst_frequencies():
            g0 = self.gap() * index
            x0 = g0 + index * self.burst_len()
            x1 = g0 + (index + 1) * self.burst_len()
            for x in range(x0 - self.gap(), x0):
                if self.p.pattern_mode() is 0:
                    self.b.setPixel(x, j, (self.mid(), self.mid(), self.mid()))
                elif self.p.pattern_mode() is 1:
                    self.b.setPixel(x, j, (self.mid(), rgb_black(), rgb_black()))
                else:
                    self.b.setPixel(x, j, (rgb_black(), rgb_black(), self.mid()))

            for x in range(x0, x1):
                v = self.burst(x - x0, freq)
                if self.p.pattern_mode() is 0:
                    self.b.setPixel(x, j, (v, v, v))
                elif self.p.pattern_mode() is 1:
                    self.b.setPixel(x, j, (v, rgb_black(), rgb_black()))
                else:
                    self.b.setPixel(x, j, (rgb_black(), rgb_black(), v))
            index += 1

        for x in range(w - self.gap(), w - self.gap() + int(self.gap() / 4)):
            if self.p.pattern_mode() is 0:
                self.b.setPixel(x, j, (self.mid(), self.mid(), self.mid()))
            if self.p.pattern_mode() is 1:
                self.b.setPixel(x, j, (self.mid(), rgb_black(), rgb_black()))
            if self.p.pattern_mode() is 2:
                self.b.setPixel(x, j, (rgb_black(), rgb_black(), self.mid()))

    def multiburst(self):
        for j in range(0, self.frame_height()):
            # fills the screen at black level
            self.set_black_level(j)
            # first square wave for the left
            self.calibration_band(j)
            # white balance pulses like a PCM adaptor
            self.white_balance_pulses(j)
            # multiburst line
            self.write_burst(j)

    def tests(self):
        if version_info[0] < 3:
            raise Exception("Python 3.x required")

        assert int(self.rgb_to_ire(rgb_white())) is self.p.white_clip(), \
            'RGB white clip is not white_clip() IRE %f' % self.rgb_to_ire(rgb_white())
        assert int(self.rgb_to_ire(rgb_black())) is self.p.black_clip(), \
            'RGB black clip is not black_clip() IRE %f' % self.rgb_to_ire(rgb_black())
        assert int(self.rgb_to_ire(0)) is self.p.black_clip(), \
            'RGB super black is not black_clip() IRE %f' % self.rgb_to_ire(0)
        assert int(self.rgb_to_ire(255)) is self.p.white_clip(), \
            'RGB super white is not white_clip() IRE %f' % self.rgb_to_ire(255)
        assert self.ire_to_rgb(100) is rgb_white(), \
            '100 IRE is not rgb_white() %d != %d' % (self.ire_to_rgb(100), rgb_white())
        assert self.ire_to_rgb(0) is rgb_black(), \
            '0 IRE is not rgb_black() %d != %d' % (self.ire_to_rgb(0), rgb_black())

        for ire in range(self.p.black_clip() + 1, self.p.white_clip() - 1):
            assert abs(self.rgb_to_ire(self.ire_to_rgb(ire)) - ire) <= 1, \
                '%d IRE -> RGB (%d) RGB -> %d IRE is not idempotent' % \
                (ire, self.ire_to_rgb(ire), self.rgb_to_ire(self.ire_to_rgb(ire)))


def print_parameters(p):
    print('lines per frame: %d' % p.lines_per_frame())
    print('scale: %f' % p.output_scale_factor())


def main():
    params = Parameters()
    print('Generating test pattern ... ')
    print_parameters(params)

    mb = MultiBurst(params)
    mb.multiburst()


if __name__ == '__main__':
    main()
