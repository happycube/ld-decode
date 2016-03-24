/* LD decoder prototype, Copyright (C) 2013 Chad Page.  License: LGPL2 */

#include <complex>
#include "ld-decoder.h"
#include "deemp.h"
	
double clamp(double v, double low, double high)
{
        if (v < low) return low;
        else if (v > high) return high;
        else return v;
}

void aclamp(double *v, int len, double low, double high)
{
	for (int i = 0; i < len; i++) {
	        if (v[i] < low) v[i] = low;
		else if (v[i] > high) v[i] = high;
	}
}

// NTSC properties
#ifdef FSC10
const double FSC = 10.0;	// in FSC.  Must be an even number!
#elif defined(FSC4)
const double FSC = 4.0;	// in FSC.  Must be an even number!
#else
const double FSC = 8.0;	// in FSC.  Must be an even number!
#endif

#define OUT_FREQ 4
const double out_freq = OUT_FREQ;	// in FSC.  Must be an even number!

struct VFormat {
	double cycles_line;
	double blanklen_ms;
	double a;	
};

//const double ntsc_uline = 63.5; // usec_
const int ntsc_iplinei = 227.5 * FSC; // pixels per line
//const double ntsc_ipline = 227.5 * FSC; // pixels per line
//const double ntsc_opline = 227.5 * out_freq; // pixels per line

//const double ntsc_blanklen = 9.2; // usec

double p_rotdetect = 40;

bool f_highburst = (FSC == 4);
bool f_flip = false;
int writeonfield = 1;

bool audio_only = false;

double inscale = 327.68;
double inbase = (inscale * 20);	// IRE == -40

long long a_read = 0, v_read = 0;
int va_ratio = 80;

const int vblen = (ntsc_iplinei * 1100);	// should be divisible evenly by 16
const int ablen = (ntsc_iplinei * 1100) / 40;

const int absize = ablen * 8;
const int vbsize = vblen * 2;
	
float abuf[ablen * 2];
unsigned short inbuf[vblen];

inline double in_to_ire(uint16_t level)
{
	if (level == 0) return -100;
	
	return -40 + ((double)(level - inbase) / inscale); 
} 

inline uint16_t ire_to_in(double ire)
{
	if (ire <= -60) return 0;
	
	return clamp(((ire + 40) * inscale) + inbase, 1, 65535);
} 

inline uint16_t ire_to_out(double ire)
{
	if (ire <= -60) return 0;
	
	return clamp(((ire + 60) * 327.68) + 1, 1, 65535);
}

double out_to_ire(uint16_t in)
{
	return (in / 327.68) - 60;
}

inline double peakdetect_quad(double *y) 
{
	return (2 * (y[2] - y[0]) / (2 * (2 * y[1] - y[0] - y[2])));
}
	
// taken from http://www.paulinternet.nl/?page=bicubic
inline double CubicInterpolate(uint16_t *y, double x)
{
	double p[4];
	p[0] = y[0]; p[1] = y[1]; p[2] = y[2]; p[3] = y[3];

	return p[1] + 0.5 * x*(p[2] - p[0] + x*(2.0*p[0] - 5.0*p[1] + 4.0*p[2] - p[3] + x*(3.0*(p[1] - p[2]) + p[3] - p[0])));
}

inline void Scale(uint16_t *buf, double *outbuf, double start, double end, double outlen, int from = 0, int to = -1)
{
	double inlen = end - start;
	double perpel = inlen / outlen; 

	if (to == -1) to = (int)outlen; 

	double p1 = start;
	for (int i = from; i < to; i++) {
		int index = (int)p1;
		if (index < 1) index = 1;

		outbuf[i] = clamp(CubicInterpolate(&buf[index - 1], p1 - index), 0, 65535);

		p1 += perpel;
	}
}
                
bool InRange(double v, double l, double h) {
	return ((v > l) && (v < h));
}

bool InRangeCF(double v, double l, double h) {
	l *= FSC;
	h *= FSC;
	return ((v > l) && (v < h));
}

// tunables
bool freeze_frame = false;
bool despackle = true;
int afd = -1, fd = 0;

double black_ire = 7.5;

int write_locs = -1;

uint16_t frame[505][(int)(OUT_FREQ * 211)];
uint16_t frame_orig[505][(int)(OUT_FREQ * 211)];
double Δframe[505][(int)(OUT_FREQ * 211)];
double Δframe_filt[505][(int)(OUT_FREQ * 211)];

#ifdef FSC10
Filter f_longsync(f_dsync10);
Filter f_syncid(f_syncid10);
Filter f_endsync(f_esync10);
int syncid_offset = syncid10_offset;
#elif defined(FSC4)
Filter f_longsync(f_dsync4);
Filter f_syncid(f_syncid4);
Filter f_endsync(f_esync4);
int syncid_offset = syncid4_offset; 
#else
Filter f_longsync(f_dsync);
Filter f_syncid(f_syncid8);
Filter f_endsync(f_esync8);
int syncid_offset = syncid8_offset;
#endif

bool BurstDetect(double *line, int freq, double _loc, bool tgt, double &plevel, double &pphase) 
{
	int len = (9 * freq);
	int loc = _loc * freq;
	int count = 0, cmin = 0;
	double ptot = 0, tpeak = 0, tmin = 0;
	double start = 0;

	double phase = 0;

//	cerr << ire_to_in(7) << ' ' << ire_to_in(16) << endl;
	double highmin = ire_to_in(f_highburst ? 11 : 11);
	double highmax = ire_to_in(f_highburst ? 23 : 22);
	double lowmin = ire_to_in(f_highburst ? -11 : -11);
	double lowmax = ire_to_in(f_highburst ? -23 : -22);
//	cerr << lowmin << ' ' << lowmax << endl;

	if (f_highburst) {
		start = 20;
		len = (start + 6) * freq;
	}

	for (int i = loc + (start * freq); i < loc + len; i++) {
		if ((line[i] > highmin) && (line[i] < highmax) && (line[i] > line[i - 1]) && (line[i] > line[i + 1])) {
			double c = round(((i + peakdetect_quad(&line[i - 1])) / freq) + (tgt ? 0.5 : 0)) * freq;

//			cerr << "B " << i + peakdetect_quad(&line[i - 1]) << ' ' << c << endl;

			if (tgt) c -= (freq / 2);
			phase = (i + peakdetect_quad(&line[i - 1])) - c;

			ptot += phase;

			tpeak += line[i];

			count++;
		//	cerr << "BDN " << i << ' ' << in_to_ire(line[i]) << ' ' << line[i - 1] << ' ' << line[i] << ' ' << line[i + 1] << ' ' << phase << ' ' << (i + peakdetect_quad(&line[i - 1])) << ' ' << c << ' ' << ptot << endl; 
		} 
		else if ((line[i] < lowmin) && (line[i] > lowmax) && (line[i] < line[i - 1]) && (line[i] < line[i + 1])) {
			cmin++;
			tmin += line[i];
		}
	}

	plevel = ((tpeak / count) - (tmin / cmin)) / 4.2;
	pphase = (ptot / count) * 1;

//	cerr << "BDN end " << plevel << ' ' << pphase << ' ' << count << endl;
	
	return (count >= 3);
}

double pleft = 0, pright = 0;
Filter f_fml(f_fmdeemp), f_fmr(f_fmdeemp);

uint16_t aout[512];
int aout_i = 0;
void ProcessAudioSample(float left, float right, double vel)
{
	left = f_fml.feed(left * (65535.0 / 300000.0));
	left += 32768;
	
	right = f_fmr.feed(right * (65535.0 / 300000.0));
	right += 32768;

	aout[aout_i * 2] = clamp(left, 0, 65535);
	aout[(aout_i * 2) + 1] = clamp(right, 0, 65535);
	
	aout_i++;
	if (aout_i == 256) {
		int rv = write(audio_only ? 1 : 3, aout, sizeof(aout));

		rv = aout_i = 0;
	}
}

double afreq = 48000;

double prev_time = -1;
double next_audsample = 0;
size_t prev_loc = -1;

long long prev_index = 0, prev_i = 0;
void ProcessAudio(double frame, long long loc, float *abuf)
{
	double time = frame / (30000.0 / 1001.0);

	cerr << "PA " << frame << ' ' << loc << endl;
	if (afd < 0) return;

	if (prev_time >= 0) {
		while (next_audsample < time) {
			double i1 = (next_audsample - prev_time) / (time - prev_time); 
			long long i = (i1 * (loc - prev_loc)) + prev_loc;

			if (i < v_read) {
				ProcessAudioSample(f_fml.val(), f_fmr.val(), 1.0);  
			} else {
				long long index = (i / va_ratio) - a_read;
				if (index >= ablen) {
					cerr << "audio error " << frame << " " << time << " " << i1 << " " << i << " " << index << " " << ablen << endl;
					index = ablen - 1;
//					exit(0);
				} 
				float left = abuf[index * 2], right = abuf[(index * 2) + 1];
				cerr << "A " << frame << ' ' << loc << ' ' << i1 << ' ' << i << ' ' << i - prev_i << ' ' << index << ' ' << index - prev_index << ' ' << left << ' ' << right << endl;
				prev_index = index;
				prev_i = i;
				ProcessAudioSample(left, right, 1.0);
			} 

			next_audsample += 1.0 / afreq;
		}
	}

	prev_time = time; prev_loc = loc;
}

double tline = 0, line = -2;
int phase = -1;

bool first = true;

int iline = 0;
int frameno = -1;

//uint16_t synclevel = 12000;
uint16_t synclevel = inbase + (inscale * 15);

bool IsPeak(double *p, int i)
{
	return (fabs(p[i]) >= fabs(p[i - 1])) && (fabs(p[i]) >= fabs(p[i + 1]));
}

// Essential VBI/Phillips code reference: http://www.daphne-emu.com/mediawiki/index.php/VBIInfo

// (LD-V6000A info page is cryptic but very essential!)

double dots_usec = 4.0 * 315.0 / 88.0;
uint32_t ReadPhillipsCode(uint16_t *line) {
	int first_bit = -1; // 108 - dots_usec;
	uint32_t out = 0;

	double Δline[844];

	for (int i = 1; i < 843; i++) {
		Δline[i] = line[i] - line[i - 1]; 
	}

	// find first positive transition (exactly halfway into bit 0 which is *always* 1) 
	for (int i = 70; (first_bit == -1) && (i < 140); i++) {
//		cerr << i << ' ' << out_to_ire(line[i]) << ' ' << Δline[i] << endl;
		if (IsPeak(Δline, i) && (Δline[i] > 10 * 327.68)) {
			first_bit = i; 
		}
	}
	if (first_bit < 0) return 0;

	for (int i = 0; i < 24; i++) {
		int rloc = -1, loc = (first_bit + (i * 2 * dots_usec));
		double rpeak = -1;

		for (int h = loc - 8; (h < loc + 8); h++) {
			if (IsPeak(Δline, h)) {
				if (fabs(Δline[h]) > rpeak) {
					rpeak = fabs(Δline[h]);
					rloc = h;
				}
			}
		}

		if (rloc == -1) rloc = loc;

		out |= (Δline[rloc] > 0) ? (1 << (23 - i)) : 0;
		cerr << i << ' ' << loc << ' ' << Δline[loc] << ' ' << rloc << ' ' << Δline[rloc] << ' ' << Δline[rloc] / inscale << ' ' << out << endl; 

		if (!i) first_bit = rloc;
	}
	cerr << "P " << hex << out << dec << endl;			

	return out;
}

const int out_x = 844;
const int out_y = 505;

inline double max(double a, double b)
{
	return (a > b) ? a : b;
}

void Despackle()
{
	memcpy(frame_orig, frame, sizeof(frame));

	for (int y = 22; y < out_y; y++) {
		double rotdetect = p_rotdetect * inscale;

		for (int x = 60; x < out_x - 16; x++) {

			double comp = 0;
	
			for (int cy = y - 1; (cy < (y + 2)) && (cy < out_y); cy++) { 
				for (int cx = x - 3; (cx < x + 3) && (cx < (out_x - 12)); cx++) {
					comp = max(comp, Δframe_filt[cy][cx]);
//					cerr << "RD " << cy << ' ' << cx << ' ' << comp << ' ' << Δframe_filt[cy][cx] << endl; 
				}
			}

//			if ((Δframe[y][x] > rotdetect)) {
			if ((out_to_ire(frame[y][x]) < -20) || (out_to_ire(frame[y][x]) > 140) || ((Δframe[y][x] > rotdetect) && ((Δframe[y][x] - comp) > rotdetect))) {
//			if (((Δframe[y][x] > rotdetect) && ((Δframe[y][x] - comp) > rotdetect))) {
				cerr << "R " << y << ' ' << x << ' ' << rotdetect << ' ' << Δframe[y][x] << ' ' << comp << ' ' << Δframe_filt[y][x] << endl;
				for (int m = x - 4; (m < (x + 14)) && (m < out_x); m++) {
					double tmp = (((double)frame_orig[y - 2][m - 2]) + ((double)frame_orig[y - 2][m + 2])) / 2;

					if (y < (out_y - 3)) {
						tmp /= 2;
						tmp += ((((double)frame_orig[y + 2][m - 2]) + ((double)frame_orig[y + 2][m + 2])) / 4);
					}

//					cerr << "Z " << y << ' ' << x << ' ' << m << endl;
					frame[y][m] = clamp(tmp, 0, 65535);
				}
				x = x + 14;
			}
		} 
	}
}

bool CheckWhiteFlag(int l)
{
	int wc = 0;

	for (int i = 100; i < 800; i++) {
		if (out_to_ire(frame[l][i]) > 80) wc++;
		if (wc >= 200) return true;
 	}

	return false;
}

void DecodeVBI()
{
	uint32_t code[6];

	uint32_t clv_time = 0;
	uint32_t chap = 0;
	uint32_t flags = 0;

	bool odd = false; // CAV framecode on odd scanline
	bool even = false; // on even scanline (need to report both, since some frames have none!)
	bool clv = false;
	bool cx  = false;
	int fnum = 0;

	memset(code, 0, sizeof(code));
	for (int i = 14; i < 20; i++) {
		code[i - 14] = ReadPhillipsCode(frame[i]);
	}
	cerr << "Phillips codes " << hex << code[0] << ' ' << code[1] << ' ' << code[2] << ' ' << code[3] << ' ' << code[4] << ' ' << code[5] << dec << endl;

	for (int i = 0; i < 6; i++) {
		frame[0][i * 2] = code[i] >> 16;
		frame[0][(i * 2) + 1] = code[i] & 0xffff;
		
		if ((code[i] & 0xf00fff) == 0x800fff) {
			chap =  ((code[i] & 0x00f000) >> 12);
			chap += (((code[i] & 0x0f0000) >> 16) - 8) * 10;
		}

		if ((code[i] & 0xfff000) == 0x8dc000) {
			cx = true;
		}

		if (0x87ffff == code[i]) {
			clv = true;
		}
	}

	if (clv == true) {
		uint16_t hours = 0;
		uint16_t minutes = 0;
		uint16_t seconds = 0;
		uint16_t framenum = 0;
		// Find CLV frame # data
		for (int i = 0; i < 6; i++) {
			// CLV Picture #
			if (((code[i] & 0xf0f000) == 0x80e000) && ((code[i] & 0x0f0000) >= 0x0a0000)) {
				seconds = (((code[i] & 0x0f0000) - 0x0a0000) >> 16) * 10; 
				seconds += (code[i] & 0x000f00) >> 8; 
				framenum = code[i] & 0x0f;
				framenum += ((code[i] & 0x000f0) >> 4) * 10;
			} 
			if ((code[i] & 0xf0ff00) == 0xf0dd00) {
				hours = ((code[i] & 0x0f0000) >> 16);
				minutes = code[i] & 0x0f;
				minutes += ((code[i] & 0x000f0) >> 4) * 10;
			} 
		}
		fnum = (((hours * 3600) + (minutes * 60) + seconds) * 30) + framenum; 
		clv_time = (hours << 24) | (minutes << 16) || (seconds << 8) || framenum;
		cerr << "CLV " << hours << ':' << minutes << ':' << seconds << '.' << framenum << endl;
	} else {
		for (int i = 0; i < 6; i++) {
			// CAV frame:  f80000 + frame
			if ((code[i] >= 0xf80000) && (code[i] <= 0xffffff)) {
				// Convert from BCD to binary
				fnum = code[i] & 0x0f;
				fnum += ((code[i] & 0x000f0) >> 4) * 10;
				fnum += ((code[i] & 0x00f00) >> 8) * 100;
				fnum += ((code[i] & 0x0f000) >> 12) * 1000;
				fnum += ((code[i] & 0xf0000) >> 16) * 10000;
				if (fnum >= 80000) fnum -= 80000;
				cerr << i << " CAV frame " << fnum << endl;
				if (i % 2) odd = true;
				if (!(i % 2)) even = true;
			} 
		}	
	}	
	cerr << " fnum " << fnum << endl;

	flags = (clv ? FRAME_INFO_CLV : 0) | (even ? FRAME_INFO_CAV_EVEN : 0) | (odd ? FRAME_INFO_CAV_ODD : 0) | (cx ? FRAME_INFO_CX : 0); 
	flags |= CheckWhiteFlag(4) ? FRAME_INFO_WHITE_EVEN : 0; 
	flags |= CheckWhiteFlag(5) ? FRAME_INFO_WHITE_ODD  : 0; 

	cerr << "Status " << hex << flags << dec << " chapter " << chap << endl;

	frame[0][12] = chap;
	frame[0][13] = flags;
	frame[0][14] = fnum >> 16;
	frame[0][15] = fnum & 0xffff;
	frame[0][16] = clv_time >> 16;
	frame[0][17] = clv_time & 0xffff;
//	exit(0);
}

// XXX new test code starts here

int find_sync(uint16_t *buf, int len, int tgt = 50, bool debug = false)
{
	const int pad = 96;
	int rv = -1;

//	uint16_t from_min = ire_to_in(-5), from_max = ire_to_in(12.5);
	const uint16_t to_min = ire_to_in(-45), to_max = ire_to_in(-35);
	const uint16_t err_min = ire_to_in(-55), err_max = ire_to_in(30);

//	len -= pad;

	uint16_t clen = tgt * 3;
	uint16_t *circbuf = new uint16_t[clen];
	uint16_t *circbuf_err = new uint16_t[clen];

	memset(circbuf, 0, clen * 2);
	memset(circbuf_err, 0, clen * 2);

	int count = 0, errcount = 0, peak = 0, peakloc = 0;

	for (int i = 0; (rv == -1) && (i < len); i++) {
		int nv = (buf[i] >= to_min) && (buf[i] < to_max);
		int err = (buf[i] <= err_min) || (buf[i] >= err_max);

		count = count - circbuf[i % clen] + nv;
		circbuf[i % clen] = nv;	
		
		errcount = errcount - circbuf_err[i % clen] + err;
		circbuf_err[i % clen] = err;	

		if (count > peak) {
			peak = count;
			peakloc = i;
		} else if ((count > tgt) && ((i - peakloc) > pad)) {
			rv = peakloc;
			
			if (errcount > 1) rv = -rv;
		}

		if (debug) {
			cerr << i << ' ' << buf[i] << ' ' << peak << ' ' << peakloc << ' ' << i - peakloc << endl;
		}
	}

	if (rv == -1) 
		cerr << "not found " << peak << ' ' << peakloc << endl;

	return rv;
}

// This could probably be used for more than just field det, but eh
int count_slevel(uint16_t *buf, int begin, int end)
{
	const uint16_t to_min = ire_to_in(-45), to_max = ire_to_in(-35);
	int count = 0;

	for (int i = begin; i < end; i++) {
		count += (buf[i] >= to_min) && (buf[i] < to_max);
	}

	return count;
}

// returns index of end of VSYNC - negative if _ field 
int find_vsync(uint16_t *buf, int len, int offset = 0)
{
	const uint16_t field_len = FSC * 227.5 * 280;

	if (len < field_len) return -1;

	int pulse_ends[6];
	int slen = len;

	int loc = offset;

	for (int i = 0; i < 6; i++) {
		// 32xFSC is *much* shorter, but it shouldn't get confused for an hsync -
		// and on rotted disks and ones with burst in vsync, this helps
		int syncend = abs(find_sync(&buf[loc], slen, 32 * FSC));

		pulse_ends[i] = syncend + loc;
		cerr << pulse_ends[i] << endl;

		loc += syncend;
		slen = 3840; 
	}

	int rv = pulse_ends[5];

	// determine line type
	int before_end = pulse_ends[0] - (127.5 * FSC);
	int before_start = before_end - (227.5 * 4.5 * FSC);

	int pc_before = count_slevel(buf, before_start, before_end);
	
	int after_start = pulse_ends[5]; 
	int after_end = after_start + (227.5 * 4.5 * FSC);
	int pc_after = count_slevel(buf, after_start, after_end); 

	cerr << "beforeafter: " << pulse_ends[0] + offset << ' ' << pulse_ends[5] + offset << ' ' << pc_before << ' ' << pc_after << endl;

	if (pc_before < pc_after) rv = -rv;	

	return rv;
}

// returns end of each line, -end if error detected in this phase 
// (caller responsible for freeing array)
double * find_hsyncs(uint16_t *buf, int len, int offset, int nlines = 253)
{
	// sanity check (XXX: assert!)
	if (len < (nlines * FSC * 227.5))
		return NULL;

	double *rv = new double[nlines];

	int loc = offset;

	for (int line = 0; line < nlines; line++) {
		int syncend = find_sync(&buf[loc], 227.5 * 3 * FSC, 8 * FSC);

		int err_offset = 0;
		while (syncend < -1) {
//			cerr << "error found " << syncend << ' ';
			err_offset += (227.5 * FSC);
			syncend = find_sync(&buf[loc] + err_offset, 227.5 * 3 * FSC, 8 * FSC);
//			cerr << syncend << endl;
		}

		// If it skips a scan line, fake it
		while ((line > 0) && (line < nlines) && (syncend > (218 * FSC))) {
			cerr << 'X' << line << ' ' << loc << ' ' << syncend << endl;
			rv[line] = -(rv[line - 1] + (227.5 * FSC)); 
			syncend -= (227.5 * FSC);	
			loc += (227.5 * FSC);
			line++;  // hackish but should work
		}

		rv[line] = loc + syncend;
		if (err_offset) rv[line] = -rv[line];

		//cerr << line << ' ' << loc << ' ' << syncend << endl;
		loc += syncend + (200 * FSC);
	}

	return rv;
}
		

// correct damaged hsyncs by interpolating neighboring lines
void CorrectDamagedHSyncs(double *hsyncs, bool *err) 
{
	for (int line = 0; line < 252; line++) {
		if (err[line] == false) continue;

		int lprev, lnext;

		for (lprev = line - 1; (err[lprev] == true) && (lprev >= 0); lprev--);
		for (lnext = line + 1; (err[lnext] == true) && (lnext < 252); lnext++);

		// This shouldn't happen...
		if ((lprev < 0) || (lprev == 252)) continue;

		cerr << "FIX " << line << ' ' << hsyncs[line] << ' ' << lprev << ' ' << lnext << ' ' ;

		double lavg = (hsyncs[lnext] - hsyncs[lprev]) / (lnext - lprev); 
		hsyncs[line] = hsyncs[lprev] + (lavg * (line - lprev));
		cerr << hsyncs[line] << endl;
	}
}

double psync[ntsc_iplinei*1200];
int Process(uint16_t *buf, int len, float *abuf, int alen)
{
	double linebuf[1820];
	int field = -1; 
	int offset = 500;

	memset(frame, 0, sizeof(frame));

	while (field < 1) {
		//find_vsync(&buf[firstsync - 1920], len - (firstsync - 1920));
		int vs = find_vsync(buf, len, offset);

		bool oddeven = vs > 0;
		vs = abs(vs);
		cerr << "findvsync " << oddeven << ' ' << vs << endl;

		if ((oddeven == false) && (field == -1))
			return vs + (FSC * 227.5 * 240);

		field++;

		// zoom ahead to close to the first full proper sync
		if (oddeven) {
			vs = abs(vs) + (750 * FSC);
		} else {
			vs = abs(vs) + (871 * FSC);
		}

		double *hsyncs = find_hsyncs(buf, len, vs);
		bool err[252];	

		// find hsyncs (rough alignment)
		for (int line = 0; line < 252; line++) {
			err[line] = hsyncs[line] < 0;
			hsyncs[line] = abs(hsyncs[line]);
		}
	
		// Determine vsync->0/7.5IRE transition point (TODO: break into function)
		for (int line = 0; line < 252; line++) {
			if (err[line] == true) continue;

			double prev = 0, begsync = -1, endsync = -1;
			const uint16_t tpoint = ire_to_in(-20); 
			
			// find beginning of hsync
			f_endsync.clear();
			prev = 0;
			for (int i = hsyncs[line] - (20 * FSC); i < hsyncs[line] - (8 * FSC); i++) {
				double cur = f_endsync.feed(buf[i]);

				if ((prev > tpoint) && (cur < tpoint)) {
//					cerr << 'B' << ' ' << i << ' ' << line << ' ' << hsyncs[line] << ' ';
					double diff = cur - prev;
					begsync = ((i - 8) + (tpoint - prev) / diff);
	
//					cerr << prev << ' ' << tpoint << ' ' << cur << ' ' << hsyncs[line] << endl;
					break;
				}
				prev = cur;
			}

			// find end of hsync
			f_endsync.clear();
			prev = 0;
			for (int i = hsyncs[line] - (2 * FSC); i < hsyncs[line] + (2 * FSC); i++) {
				double cur = f_endsync.feed(buf[i]);

				if ((prev < tpoint) && (cur > tpoint)) {
//					cerr << 'E' << ' ' << line << ' ' << hsyncs[line] << ' ';
					double diff = cur - prev;
					endsync = ((i - 8) + (tpoint - prev) / diff);
	
//					cerr << prev << ' ' << tpoint << ' ' << cur << ' ' << hsyncs[line] << endl;
					break;
				}
				prev = cur;
			}

			cerr << line << ' ' << begsync << ' ' << endsync << ' ' << endsync - begsync << endl;

			if ((!InRangeCF(endsync - begsync, 15.75, 16.5)) || (begsync == -1) || (endsync == -1)) {
				err[line] = true;
			} else {
				hsyncs[line] = endsync;
			}
		}
	
		// We need semi-correct lines for the next phases	
		CorrectDamagedHSyncs(hsyncs, err); 

		double blevel[252], phase[252];
		double tpodd = 0, tpeven = 0;
		int nodd = 0, neven = 0; // need to track these to exclude bad lines
		double bphase = 0;
		// detect alignment (undamaged lines only) 
		for (int line = 0; line < 64; line++) {
			double line1 = hsyncs[line], line2 = hsyncs[line + 1];

			if (err[line] == true) continue;

			// burst detection/correction

			Scale(buf, linebuf, line1, line2, 1820);
			BurstDetect(linebuf, FSC, 4, false, blevel[line], bphase); 
			phase[line] = bphase;	
	
			if (line % 2) {
				tpodd += phase[line];
				nodd++;
			} else {
				tpeven += phase[line];
				neven++;
			}
	
//			cerr << line << ' ' << line1 << ' ' << line2 << ' ' << blevel << ' ' << bphase << endl;
		}

		bool fieldphase = fabs(tpeven / neven) < fabs(tpodd / nodd);
		cerr << "PHASES: " << tpeven / neven << ' ' << tpodd / nodd << ' ' << fieldphase << endl; 

		for (int pass = 0; pass < 2; pass++) {
		   for (int line = 0; line < 252; line++) {
			bool lphase = ((line % 2) == 0); 
			if (fieldphase) lphase = !lphase;

			double line1c = hsyncs[line] + ((hsyncs[line + 1] - hsyncs[line]) * 14.0 / 227.5);

			Scale(buf, linebuf, hsyncs[line], line1c, 14 * FSC);
			BurstDetect(linebuf, FSC, 4, lphase, blevel[line], bphase); 
//			cerr << line << ' ' << line1 << ' ' << line2 << ' ' << blevel << ' ' << bphase << endl;
		
			bphase /= (pass + 1);

			if ((bphase >= -FSC) and (bphase <= FSC)) {// Block NaN	
				hsyncs[line] += bphase;
			} else {
				err[line] = true;
			}

			Scale(buf, linebuf, hsyncs[line], line1c + bphase, 14 * FSC);
			BurstDetect(linebuf, FSC, 4, lphase, blevel[line], bphase); 

//			cerr << line << ' ' << line1a << ' ' << line2a << ' ' << blevel << ' ' << bphase << endl;
		   }
		}

		CorrectDamagedHSyncs(hsyncs, err); 

		// final output
		for (int line = 0; line < 252; line++) {
			double line1 = hsyncs[line], line2 = hsyncs[line + 1];
			int oline = 4 + (line * 2) + (oddeven ? 0 : 1);

			int pt = 3 - 16;	
//			cerr << "S " << line1 << ' ' << line2 << endl;
			Scale(buf, linebuf, line1 + pt, line2 + pt, 910);

		//	if (err[line]) continue;
			ProcessAudio((line / 525.0) + frameno + (field * .5), v_read + hsyncs[line], abuf); 
	
			bool lphase = ((line % 2) == 0); 
			if (fieldphase) lphase = !lphase;
			frame[oline][0] = (lphase == 0) ? 32768 : 16384; 
			frame[oline][1] = blevel[line];

			if (err[line]) {
               			frame[oline][3] = frame[oline][5] = 65000;
			        frame[oline][4] = frame[oline][6] = 0;
			}

			for (int t = 4; t < 844; t++) {
				double o = linebuf[t];

				if (o > 65535) o = 65535;
				if (o < 1) o = 1;

				frame[oline][t] = o;
			}
		}

		offset = abs(hsyncs[250]);

		cerr << "new offset " << offset << endl;

		free(hsyncs);
	}

	if (despackle) Despackle();

	// Decode VBI data
	DecodeVBI();

	frameno++;
	cerr << "WRITING\n";
	write(1, frame, sizeof(frame));
	memset(frame, 0, sizeof(frame));

	return offset;
}

bool seven_five = (FSC == 4);
double low = 65535, high = 0;

double f[vblen];

void autoset(uint16_t *buf, int len, bool fullagc = true)
{
	int lowloc = -1;
	int checklen = (int)(FSC * 4);

	if (!fullagc) {
		low = 65535;
		high = 0;
	}

	cerr << "old base:scale = " << inbase << ':' << inscale << endl;
	
//	f_longsync.clear(0);

	// phase 1:  get low (-40ire) and high (??ire)
	for (int i = 0; i < len; i++) {
		f[i] = f_longsync.feed(buf[i]);

		if ((i > (FSC * 256)) && (f[i] < low) && (f[i - checklen] < low)) {
			if (f[i - checklen] > f[i]) 
				low = f[i - checklen];
			else 
				low = f[i];

			lowloc = i;
		}
		
		if ((i > (FSC * 256)) && (f[i] > high) && (f[i - checklen] > high)) {
			if (f[i - checklen] < f[i]) 
				high = f[i - checklen];
			else 
				high = f[i];
		}

//		cerr << i << ' ' << buf[i] << ' ' << f[i] << ' ' << low << ':' << high << endl;
	}

//	cerr << lowloc << ' ' << low << ':' << high << endl;

	// phase 2: attempt to figure out the 0IRE porch near the sync

	if (!fullagc) {
		int gap = high - low;
		int nloc;

		for (nloc = lowloc; (nloc > lowloc - (FSC * 320)) && (f[nloc] < (low + (gap / 8))); nloc--);

		cerr << nloc << ' ' << (lowloc - nloc) / FSC << ' ' << f[nloc] << endl;

		nloc -= (FSC * 4);
		cerr << nloc << ' ' << (lowloc - nloc) / FSC << ' ' << f[nloc] << endl;
	
		cerr << "old base:scale = " << inbase << ':' << inscale << endl;

		inscale = (f[nloc] - low) / ((seven_five) ? 47.5 : 40.0);
		inbase = low - (20 * inscale);	// -40IRE to -60IRE
		if (inbase < 1) inbase = 1;
		cerr << "new base:scale = " << inbase << ':' << inscale << endl;
	} else {
		inscale = (high - low) / 140.0;
	}

	inbase = low;	// -40IRE to -60IRE
	if (inbase < 1) inbase = 1;

	cerr << "new base:scale = " << inbase << ':' << inscale << " low: " << low << ' ' << high << endl;

	synclevel = inbase + (inscale * 20);
}

int main(int argc, char *argv[])
{
	int rv = 0, arv = 0;
	bool do_autoset = (FSC == 4);
	long long dlen = -1;
	unsigned char *cinbuf = (unsigned char *)inbuf;
	unsigned char *cabuf = (unsigned char *)abuf;

	int c;

	cerr << std::setprecision(10);

	opterr = 0;
	
	while ((c = getopt(argc, argv, "dHmhgs:n:i:a:AfFt:r:")) != -1) {
		switch (c) {
			case 'm':	// "magnetic video" mode - bottom field first
				writeonfield = 2;
				break;
			case 'F':	// flip fields 
				f_flip = true;
				break;
			case 'i':
				fd = open(optarg, O_RDONLY);
				break;
			case 'a':
				afd = open(optarg, O_RDONLY);
				break;
			case 'A':
				audio_only = true;
				break;
			case 'g':
				do_autoset = !do_autoset;
				break;
			case 'n':
				despackle = false;
				break;
			case 'f':
				freeze_frame = true;
				break;
			case 'h':
				seven_five = true;
				break;
			case 'H':
				f_highburst = !f_highburst;
				break;
			case 'r':
				sscanf(optarg, "%lf", &p_rotdetect);		
				break;
			default:
				return -1;
		} 
	} 

	cerr << "freq = " << FSC << endl;

	rv = read(fd, inbuf, vbsize);
	while ((rv > 0) && (rv < vbsize)) {
		int rv2 = read(fd, &cinbuf[rv], vbsize - rv);
		if (rv2 <= 0) exit(0);
		rv += rv2;
	}

	cerr << "B" << absize << ' ' << ablen * 2 * sizeof(float) << endl ;

	if (afd != -1) {	
		arv = read(afd, abuf, absize);
		while ((arv > 0) && (arv < absize)) {
			int arv2 = read(afd, &cabuf[arv], absize - arv);
			if (arv2 <= 0) exit(0);
			arv += arv2;
		}
	}
							
	memset(frame, 0, sizeof(frame));

	size_t aplen = 0;
	while (rv == vbsize && ((v_read < dlen) || (dlen < 0))) {
		if (do_autoset) {
			autoset(inbuf, vbsize / 2);
		}

		int plen;

		plen = Process(inbuf, rv / 2, abuf, arv / 8);
	
		if (plen < 0) {
			cerr << "skipping ahead" << endl;
			plen = vblen / 2;
		}

		v_read += plen;
		aplen = (v_read / va_ratio) - a_read;

		a_read += aplen;

//		cerr << "move " << plen << ' ' << (vblen - plen) * 2; 
		memmove(inbuf, &inbuf[plen], (vblen - plen) * 2);
	
                rv = read(fd, &inbuf[(vblen - plen)], plen * 2) + ((vblen - plen) * 2);
		while ((rv > 0) && (rv < vbsize)) {
			int rv2 = read(fd, &cinbuf[rv], vbsize - rv);
			if (rv2 <= 0) exit(0);
			rv += rv2;
		}	
		
		if (afd != -1) {	
			cerr << "AA " << plen << ' ' << aplen << ' ' << v_read << ' ' << a_read << ' ' << (double)v_read / (double)a_read << endl;
			memmove(abuf, &abuf[aplen * 2], absize - (aplen * 8));
			cerr << abuf[0] << endl;

			arv = (absize - (aplen * 8));
			while (arv < absize) {
				int arv2 = read(afd, &cabuf[arv], absize - arv);
				if (arv2 <= 0) exit(0);
				arv += arv2;
			}

			if (arv == 0) exit(0);
		}
	}

	return 0;
}
