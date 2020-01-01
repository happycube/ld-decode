/************************************************************************

    testvbidecoder.cpp

    Unit tests for VbiDecoder
    Copyright (C) 2020 Adam Sampson

    This file is part of ld-decode-tools.

    ld-chroma-decoder is free software: you can redistribute it and/or
    modify it under the terms of the GNU General Public License as
    published by the Free Software Foundation, either version 3 of the
    License, or (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.

************************************************************************/

#include <cassert>
#include <iostream>

using std::cerr;

#include "vbidecoder.h"

// Check that two Vbi structs are field-by-field identical
void assertSame(const VbiDecoder::Vbi &actual, const VbiDecoder::Vbi &expected)
{
    assert(actual.type == expected.type);
    assert(actual.userCode == expected.userCode);
    assert(actual.picNo == expected.picNo);
    assert(actual.chNo == expected.chNo);
    assert(actual.clvHr == expected.clvHr);
    assert(actual.clvMin == expected.clvMin);
    assert(actual.clvSec == expected.clvSec);
    assert(actual.clvPicNo == expected.clvPicNo);
    assert(actual.soundMode == expected.soundMode);
    assert(actual.soundModeAm2 == expected.soundModeAm2);

    assert(actual.leadIn == expected.leadIn);
    assert(actual.leadOut == expected.leadOut);
    assert(actual.picStop == expected.picStop);
    assert(actual.cx == expected.cx);
    assert(actual.size == expected.size);
    assert(actual.side == expected.side);
    assert(actual.teletext == expected.teletext);
    assert(actual.dump == expected.dump);
    assert(actual.fm == expected.fm);
    assert(actual.digital == expected.digital);
    assert(actual.parity == expected.parity);
    assert(actual.copyAm2 == expected.copyAm2);
    assert(actual.standardAm2 == expected.standardAm2);
}

// Test VbiDecoder::decode
void testDecode()
{
    using Vbi = VbiDecoder::Vbi;
    using VbiDiscTypes = VbiDecoder::VbiDiscTypes;
    using VbiSoundModes = VbiDecoder::VbiSoundModes;

    VbiDecoder decoder;

    // We want to check that decoding a VBI value sets the correct values in
    // the Vbi structure, and doesn't change any of the other values. So for
    // each test, we construct an "expected" structure with only the relevant
    // fields changed, and check that the result of decoding is exactly the
    // same.
    //
    // We test for things that the standard says should work, for things that
    // the standard says shouldn't work (e.g. invalid BCD digits), and for
    // things that discs do anyway regardless of what the standard says :-)

    // FIXME - #if 0 blocks are tests that should pass but don't

    cerr << "Testing VbiDecoder::decode\n";
    cerr << "IEC 60857-1986 - 10.1.1 Lead-in\n";

    {
        Vbi expected;
        expected.leadIn = true;

        assertSame(decoder.decode(0, 0x88FFFF, 0), expected);
        assertSame(decoder.decode(0, 0, 0x88FFFF), expected);
    }

    cerr << "IEC 60857-1986 - 10.1.2 Lead-out\n";

    {
        Vbi expected;
        expected.leadOut = true;

        assertSame(decoder.decode(0, 0x80EEEE, 0), expected);
        assertSame(decoder.decode(0, 0, 0x80EEEE), expected);

#if 0
        // EE1015 - lead-out code in line 16
        assertSame(decoder.decode(0x80EEEE, 0x80EEEE, 0), expected);
#endif
    }

    cerr << "IEC 60857-1986 - 10.1.3 Picture numbers\n";

    {
        Vbi expected;
        expected.type = VbiDiscTypes::cav;
        expected.picNo = 12345;

        // Regular
        assertSame(decoder.decode(0, 0xF12345, 0), expected);
        assertSame(decoder.decode(0, 0, 0xF12345), expected);

        // Early stopcode signalling
        assertSame(decoder.decode(0, 0xF92345, 0), expected);
        assertSame(decoder.decode(0, 0, 0xF92345), expected);
    }

    {
        Vbi expected;

        // Ignore invalid digits
        assertSame(decoder.decode(0, 0xF1A345, 0), expected);
        assertSame(decoder.decode(0, 0xF12A45, 0), expected);
        assertSame(decoder.decode(0, 0xF123A5, 0), expected);
        assertSame(decoder.decode(0, 0xF1234A, 0), expected);
    }

    {
        // G138F0117 - corrupt picture number with valid picture number
        Vbi expected;
        expected.type = VbiDiscTypes::cav;
        expected.picNo = 14212;

        assertSame(decoder.decode(0, 0xF95FDF, 0xF94212), expected);
    }

    cerr << "IEC 60857-1986 - 10.1.4 Picture stop code\n";

    {
        Vbi expected;
        expected.type = VbiDiscTypes::cav;
        expected.picStop = true;

        assertSame(decoder.decode(0x82CFFF, 0, 0), expected);
        assertSame(decoder.decode(0, 0x82CFFF, 0), expected);
    }

    cerr << "IEC 60857-1986 - 10.1.5 Chapter numbers\n";

    {
        Vbi expected;
        expected.chNo = 42;

        // Stop bit 0
        assertSame(decoder.decode(0, 0x842DDD, 0), expected);
        assertSame(decoder.decode(0, 0, 0x842DDD), expected);

        // Stop bit 1
        assertSame(decoder.decode(0, 0x8C2DDD, 0), expected);
        assertSame(decoder.decode(0, 0, 0x8C2DDD), expected);
    }

    {
        Vbi expected;

#if 0
        // Ignore invalid second digit
        assertSame(decoder.decode(0, 0x84ADDD, 0), expected);
#endif
    }

    cerr << "IEC 60857-1986 - 10.1.6 Programme time code\n";

    {
        Vbi expected;
        expected.type = VbiDiscTypes::clv;
        expected.clvHr = 1;
        expected.clvMin = 23;

        assertSame(decoder.decode(0, 0xF1DD23, 0), expected);
        assertSame(decoder.decode(0, 0, 0xF1DD23), expected);
    }

    {
        Vbi expected;

#if 0
        // Ignore invalid digits
        assertSame(decoder.decode(0, 0xFADD23, 0), expected);
        assertSame(decoder.decode(0, 0xF1DDA3, 0), expected);
        assertSame(decoder.decode(0, 0xF1DD2A, 0), expected);
#endif
    }

    cerr << "IEC 60857-1986 - 10.1.7 Constant linear velocity code\n";

    {
        Vbi expected;
        expected.type = VbiDiscTypes::clv;

        assertSame(decoder.decode(0, 0x87FFFF, 0), expected);
    }

    cerr << "IEC 60857-1986 - 10.1.8 Programme status code (including Amendment 2)\n";

    // The examples here are from real discs.

    {
        // EE 1015 side 1 - PAL with digital audio
        Vbi expected;
        expected.cx = false;
        expected.soundMode = VbiSoundModes::futureUse;
        expected.soundModeAm2 = VbiSoundModes::futureUse;
        expected.size = true;
        expected.side = true;
        expected.teletext = false;
        expected.fm = false;
        expected.parity = true;
        assertSame(decoder.decode(0x8BA027, 0, 0), expected);

        // EE 1015 side 2
        expected.side = false;
        assertSame(decoder.decode(0x8BA427, 0, 0), expected);

        // Any bit flips in X4 should be detected as invalid parity
        assert(!decoder.decode(0x8BA417, 0, 0).parity);
#if 0
        assert(!decoder.decode(0x8BA407, 0, 0).parity);
#endif
        assert(!decoder.decode(0x8BA447, 0, 0).parity);
        assert(!decoder.decode(0x8BA487, 0, 0).parity);
    }

    {
        // NJL-11762 side 1 - NTSC
        Vbi expected;
        expected.soundMode = VbiSoundModes::stereo;
        expected.soundModeAm2 = VbiSoundModes::stereo;
        expected.cx = true;
        expected.size = true;
        expected.side = true;
        expected.standardAm2 = true;
        expected.parity = true;
        assertSame(decoder.decode(0x8DC000, 0, 0), expected);

        // NJL-11762 side 2
        expected.side = false;
        assertSame(decoder.decode(0x8DC400, 0, 0), expected);

        // Any bit flips in X4 should be detected as invalid parity
        assert(!decoder.decode(0x8DC410, 0, 0).parity);
        assert(!decoder.decode(0x8DC420, 0, 0).parity);
        assert(!decoder.decode(0x8DC440, 0, 0).parity);
        assert(!decoder.decode(0x8DC480, 0, 0).parity);
    }

    {
        // GGV1069, last chapter - NTSC, 8 inch, bilingual
        Vbi expected;
        expected.soundMode = VbiSoundModes::bilingual;
        expected.soundModeAm2 = VbiSoundModes::bilingual;
        expected.cx = false;
        expected.size = false;
        expected.side = true;
        expected.standardAm2 = true;
        expected.parity = true;

#if 0
        assertSame(decoder.decode(0x8BA839, 0, 0), expected);
#endif

        // Any bit flips in X4 should be detected as invalid parity
        assert(!decoder.decode(0x8BA829, 0, 0).parity);
        assert(!decoder.decode(0x8BA819, 0, 0).parity);
        assert(!decoder.decode(0x8BA879, 0, 0).parity);
        assert(!decoder.decode(0x8BA8B9, 0, 0).parity);
    }

    cerr << "IEC 60857-1986 - 10.1.9 Users code\n";

    {
        Vbi expected;
        expected.userCode = "5AFE";

        assertSame(decoder.decode(0x85DAFE, 0, 0), expected);
    }

    {
        Vbi expected;

#if 0
        // Ignore X1 not in range 0-7
        assertSame(decoder.decode(0x88DAFE, 0, 0), expected);
#endif
    }

    cerr << "IEC 60857-1986 - 10.1.10 CLV picture number\n";

    {
        Vbi expected;
        expected.type = VbiDiscTypes::clv;
        expected.clvSec = 42;
        expected.clvPicNo = 23;

        assertSame(decoder.decode(0x8EE223, 0, 0), expected);
    }

    {
        Vbi expected;

#if 0
        // Ignore invalid digits
        assertSame(decoder.decode(0x84E223, 0, 0), expected);
        assertSame(decoder.decode(0x8EEA23, 0, 0), expected);
        assertSame(decoder.decode(0x8EE2A3, 0, 0), expected);
        assertSame(decoder.decode(0x8EE22A, 0, 0), expected);
#endif
    }
}

int main()
{
    testDecode();

    return 0;
}
