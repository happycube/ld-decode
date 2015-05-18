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
const double in_freq = 10.0;	// in FSC.  Must be an even number!
#elif defined(FSC4)
const double in_freq = 4.0;	// in FSC.  Must be an even number!
#else
const double in_freq = 8.0;	// in FSC.  Must be an even number!
#endif

#define OUT_FREQ 4
const double out_freq = OUT_FREQ;	// in FSC.  Must be an even number!

struct VFormat {
	double cycles_line;
	double blanklen_ms;
	double a;	
};

double burstfreq = 4.43361875;

//const double pal_uline = 64; // usec_
const int pal_iplinei = 229 * in_freq; // pixels per line
const double pal_ipline = 229 * in_freq; // pixels per line
const double pal_opline = 1052; // pixels per line
//const int pal_oplinei = 229 * out_freq; // pixels per line

const double pixels_per_usec = 1000000.0 / (in_freq * (1000000.0 * 315.0 / 88.0)); 

// include everything from first sync to end of second sync, plus padding
// 1 (padding) + 64 (line) + 4.7 (sync) + 1 padding = 72.35 
const double pal_blanklen = 6.7;
const double scale_linelen = (70.7 / 64); 

const double pal_ihsynctoline = pal_ipline * (pal_blanklen / 64);
const double iscale15_len = pal_ipline + pal_ihsynctoline;

const double pal_hsynctoline = pal_opline * (pal_blanklen / 64);

// contains padding
double scale15_len = 15000000.0 * (70.7 / 1000000.0);
// endsync to next endsync
double scale4fsc_len = 4 * 4433618 * (70.7 / 1000000.0);

double p_rotdetect = 80;

double hfreq = 625.0 * (30000.0 / 1001.0);

long long fr_count = 0, au_count = 0;

double f_tol = 0.5;

bool f_diff = false;

bool f_highburst = (in_freq == 4);
bool f_flip = false;
//bool f_flip = true;
int writeonfield = 2;

bool audio_only = false;

double inscale = 327.68;
double inbase = (inscale * 20);	// IRE == -40

long long a_read = 0, v_read = 0;
int va_ratio = 80;

const int vblen = (pal_iplinei * 1100);	// should be divisible evenly by 16
const int ablen = (pal_iplinei * 1100) / 40;

const int absize = ablen * 8;
const int vbsize = vblen * 2;
	
float abuf[ablen * 2];
unsigned short inbuf[vblen];
unsigned short filtbuf[vblen];

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
	
//def quadpeak(y):
//        return (y[2] - y[0]) / (2 * (2 * y[1] - y[0] - y[2]))

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

inline void Scale(uint16_t *buf, double *outbuf, double start, double end, double outlen)
{
	double inlen = end - start;
	double perpel = inlen / outlen; 

	cerr << "scale " << start << ' ' << end << ' ' << outlen << endl;

	double p1 = start;
	for (int i = 0; i < outlen; i++) {
		int index = (int)p1;
		if (index < 1) index = 1;

		outbuf[i] = clamp(CubicInterpolate(&buf[index - 1], p1 - index), 0, 65535);

		p1 += perpel;
	}
}
                
bool InRange(double v, double l, double h) {
	return ((v >= l) && (v <= h));
}

bool InRangeF(double v, double l, double h) {
	l *= in_freq;
	h *= in_freq;
	return ((v >= l) && (v <= h));
}

// tunables

bool freeze_frame = false;
bool despackle = true;
int afd = -1, fd = 0;

double black_ire = 7.5;

int write_locs = -1;

uint16_t frame[610][1052];

Filter f_bpcolor4(f_colorbp4);
Filter f_bpcolor8(f_colorbp8);

#ifdef FSC10
Filter f_longsync(f_dsync10);
Filter f_syncid(f_syncid10);
int syncid_offset = syncid10_offset;
#elif defined(FSC4)
Filter f_longsync(f_dsync4);
Filter f_syncid(f_syncid4);
int syncid_offset = syncid4_offset; 
#else
Filter f_longsync(f_dsync);
Filter f_syncid(f_syncid8);
int syncid_offset = syncid8_offset;
#endif

bool PilotDetect(double *line, double loc, double &plevel, double &pphase) 
{
	int len = (12 * in_freq);
	int count = 0, cmax = 0;
	double ptot = 0, tpeak = 0, tmax = 0;
	double start = 0;

	double phase = 0;

	loc *= 4;

//	cerr << ire_to_in(7) << ' ' << ire_to_in(16) << endl;
	double min = 5000;
	double max = 20000;
	double lowmin = 5000;
	double lowmax = 13000;
//	cerr << lowmin << ' ' << lowmax << endl;

	for (int i = 28 + loc; i < len + loc; i++) {
		if ((line[i] > lowmin) && (line[i] < lowmax) && (line[i] < line[i - 1]) && (line[i] < line[i + 1])) {
			double c = round(((i + peakdetect_quad(&line[i - 1])) / 4)) * 4;

			phase = (i + peakdetect_quad(&line[i - 1])) - c;
			ptot += phase;

			tpeak += line[i];
			count++;
//			cerr << "BDP " << i << ' ' << in_to_ire(line[i]) << ' ' << line[i - 1] << ' ' << line[i] << ' ' << line[i + 1] << ' ' << phase << ' ' << (i + peakdetect_quad(&line[i - 1])) << ' ' << c << ' ' << ptot << endl; 
		} 
	}

	plevel = ((tpeak / count) /*- (tmin / cmin)*/) / 2.25;
	pphase = (ptot / count) * 1;

//	cerr << "PhaseDetect plevel " << plevel << " pphase " << pphase << ' ' << count << endl;
//	exit(0);
	return (count >= 2);
}

bool BurstDetect(double *line, int start, int end, double &plevel, double &pphase) 
{
	double freq = out_freq;
	int count = 0, cmin = 0;
	double ptot = 0, tpeak = 0, tmin = 0;

	double phase = 0;

//	cerr << ire_to_in(7) << ' ' << ire_to_in(16) << endl;
	double highmin = 35500; // ire_to_in(f_highburst ? 12 : 7);
	double highmax = 39000; // ire_to_in(f_highburst ? 23 : 22);
//	cerr << lowmin << ' ' << lowmax << endl;

	for (int i = start; i < end; i++) {
//		cerr << "BN " << ' ' << i << ' ' << line[i] << endl;
		if ((line[i] > highmin) && (line[i] < highmax) && (line[i] > line[i - 1]) && (line[i] > line[i + 1])) {
			double c = round(((i + peakdetect_quad(&line[i - 1])) / 4) ) * 4;

//			cerr << "B " << i + peakdetect_quad(&line[i - 1]) << ' ' << c << endl;

//			if (tgt) c -= 2;
			phase = (i + peakdetect_quad(&line[i - 1])) - c;

			ptot += phase;

			tpeak += line[i];

			count++;
//			cerr << "BDN " << i << ' ' << in_to_ire(line[i]) << ' ' << line[i - 1] << ' ' << line[i] << ' ' << line[i + 1] << ' ' << phase << ' ' << (i + peakdetect_quad(&line[i - 1])) << ' ' << c << ' ' << ptot << endl; 
		} 
		else if (/*(line[i] < lowmin) && (line[i] > lowmax) &&*/ (line[i] < line[i - 1]) && (line[i] < line[i + 1])) {
			cmin++;
			tmin += line[i];
		}
	}

	plevel = (tpeak / count) /* - (tmin / cmin)) */ / 4.2;
	pphase = (ptot / count) * 1;

//	cerr << "BurstDetect end " << plevel << ' ' << pphase << ' ' << count << endl;
	
	return (count >= 3);
}

	

int get_oline(double line)
{
	int l = (int)line;
	int rv = -1;

	if (l < 10) rv = -1;
	else if (l < 314) rv = ((l - 10) * 2) + 0;
	else if (l < 319) rv = -1;
	else if (l < 625) rv = ((l - 318) * 2) + 1;

	if (rv > 609) rv = -1;

	return rv;
}

double pleft = 0, pright = 0;
double _left = 0, _right = 0;
Filter f_fml(f_fmdeemp), f_fmr(f_fmdeemp);

uint16_t aout[512];
int aout_i = 0;
void ProcessAudioSample(float left, float right, double vel)
{
//	double scale = ((vel - 1) * 0.5) + 1;

	left *= (65535.0 / 300000.0);
	left = f_fml.feed(left);
	left += 32768;
	
	right *= (65535.0 / 300000.0);
	right = f_fmr.feed(right);
	right += 32768;

	_left = left;
	_right = right;

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
double prev_linelen = pal_ipline;
double prev_offset_begin = 0.0;
double prev_offset_end = 0.0;

double prev_begin = 0;

int iline = 0;
int frameno = -1;

static int offburst = 0;

struct Line {
	double center;
	double peak;
	double beginsync, endsync;
	int linenum;
	bool bad;
};

double ProcessLine(uint16_t *buf, vector<Line> &lines, int index)
{
	double tout[8192];
	double adjlen = pal_ipline;
	int pass = 0;

	double begin_offset, end_offset;

	double plevel1, plevel2;
	double nphase1, nphase2;
	
	double burstlevel = 0;
	double burstphase = 0;	
	
	int line = lines[index].linenum;
	int oline = get_oline(line);
	if (oline < 0) return 0;

	bool err = lines[index].bad;

	// use 1usec of padding
	double pixels_per_usec = 28.625; 
	double begin = lines[index].beginsync - pixels_per_usec;
	double end = lines[index+1].endsync + pixels_per_usec;

	double orig_begin = begin;
	double orig_end = end;
	
	double tgt_nphase = 0;

	cerr << "PPL " << line << ' ' << lines[index].beginsync << ' ' << lines[index+1].endsync << ' ' << lines[index+1].endsync - lines[index].beginsync << endl;
	cerr << "PL " << line << ' ' << begin << ' ' << end << ' ' << err << ' ' << end - begin << endl;

	cerr << "ProcessLine " << begin << ' ' << end << endl;

	Scale(buf, tout, begin, end, scale15_len); 

	bool valid = PilotDetect(tout, 0, plevel1, nphase1); 
	cerr << "second pilot:" << endl;
	PilotDetect(tout, 240, plevel2, nphase2); 
	
	double nadj1 = nphase1 * 1;
	double nadj2 = nphase2 * 1;

	cerr << "Beginning Pilot levels " << plevel1 << ' ' << plevel2 << " valid " << valid << endl;

	if (!valid /* || (plevel1 < (f_highburst ? 1800 : 1000)) || (plevel2 < (f_highburst ? 1000 : 800)) */) {
		begin += prev_offset_begin;
		end += prev_offset_end;
	
		Scale(buf, tout, begin, end, scale4fsc_len); 
		goto wrapup;
	}

	adjlen = (end - begin) / (scale15_len / pal_opline);

	for (pass = 0; (pass < 12) && ((fabs(nadj1) + fabs(nadj2)) > .005); pass++) {
		if (!pass) nadj2 = 0;
	
		cerr << "adjusting " << nadj1 << ' ' << nadj2 << endl;

		begin += nadj1;
		end += nadj2;

		Scale(buf, tout, begin, end, scale15_len); 
		PilotDetect(tout, 0, plevel1, nphase1); 
		cerr << "second burst" << endl;
		PilotDetect(tout, 240, plevel2, nphase2); 
		
		nadj1 = nphase1 * 1;
		nadj2 = nphase2 * 1;

		adjlen = (end - begin) / (scale15_len / pal_opline);
	}
	
	cerr << "End Pilot levels " << pass << ' ' << plevel1 << ':' << nphase1 << " " << plevel2 << ':' << nphase2 << " valid " << valid << endl;

	begin_offset = begin - orig_begin;
	end_offset = end - orig_end;
	cerr << "offset " << oline << ' ' << begin_offset << ' ' << end_offset << ' ' << end - begin << ' ' << (begin - prev_begin) * (70.7 / 64.0) << ' ' << endl;

	{
		double orig_len = orig_end - orig_begin;
		double new_len = end - begin;
		cerr << "len " << frameno + 1 << ":" << oline << ' ' << orig_len << ' ' << new_len << ' ' << orig_begin << ' ' << begin << ' ' << orig_end << ' ' << end << endl;
		if (fabs(new_len - orig_len) > (in_freq * f_tol)) {
			cerr << "ERRP len " << frameno + 1 << ":" << oline << ' ' << orig_len << ' ' << new_len << ' ' << orig_begin << ' ' << begin << ' ' << orig_end << ' ' << end << endl;

			if (fabs(begin_offset) > fabs(end_offset)) 
				begin = orig_begin + end_offset;
			else
				end = orig_end + begin_offset;
	
			cerr << "noffset " << begin - orig_begin << ' ' << end - orig_end << endl;

			Scale(buf, tout, begin, end, scale15_len); 
			PilotDetect(tout, 0, plevel1, nphase1); 
			PilotDetect(tout, 240, plevel2, nphase2); 
		}
	}

	cerr << "final levels " << plevel1 << ' ' << plevel2 << endl;
	begin += 4.0 * (burstfreq / 3.75);
	end += 4.0 * (burstfreq / 3.75);
	Scale(buf, tout, begin, end, scale4fsc_len); 
		
	BurstDetect(tout, 120, 164, burstlevel, burstphase); 
	cerr << "BURST " << get_oline(line) << ' ' << line << ' ' << burstlevel << ' ' << burstphase << endl;

wrapup:
	// LD only: need to adjust output value for velocity, and remove defects as possible
	double lvl_adjust = ((((end - begin) / iscale15_len) - 1) * 1.0) + 1;
	int ldo = -128;

	cerr << "leveladj " << lvl_adjust << endl;

	double rotdetect = p_rotdetect * inscale;
	
	double diff[1052];
	double prev_o = 0;
	for (int h = 0; (oline > 2) && (h < 1052); h++) {
		double v = tout[h + 94 ];
		double ire = in_to_ire(v);
		double o;

		if (in_freq != 4) {
			double freq = (ire * ((7900000 - 7100000) / 100)) + 7100000; 

//			cerr << h << ' ' << v << ' ' << ire << ' ' << freq << ' ';
			freq *= lvl_adjust;
//			cerr << freq << ' ';

			ire = ((freq - 7100000) / 800000) * 100;
//			cerr << ire << endl;
			o = ire_to_out(ire);
		} else { 
			o = ire_to_out(in_to_ire(v));
		}

		if (despackle && (h > (20 * out_freq)) && ((fabs(o - prev_o) > rotdetect) || (ire < -25))) {
//		if (despackle && (ire < -30) && (h > 80)) {
			if ((h - ldo) > 16) {
				for (int j = h - 4; j > 2 && j < h; j++) {
					double to = (frame[oline - 2][j - 2] + frame[oline - 2][j + 2]) / 2;
					frame[oline][j] = clamp(to, 0, 65535);
				}
			}
			ldo = h;
		}

		if (((h - ldo) < 16) && (h > 4)) {
			o = (frame[oline - 2][h - 2] + frame[oline - 2][h + 2]) / 2;
//			cerr << "R " << o << endl;
		}

		frame[oline][h] = clamp(o, 0, 65535);
		diff[h] = o - prev_o;
		prev_o = o;
		//if (!(oline % 2)) frame[oline][h] = clamp(o, 0, 65535);
	}
	
	for (int h = 0; f_diff && (oline > 2) && (h < 1052); h++) {
		frame[oline][h] = clamp(diff[h], 0, 65535);
	}
	
        if (!pass) {
                frame[oline][2] = 32000;
                frame[oline][3] = 32000;
                frame[oline][4] = 32000;
                frame[oline][5] = 32000;
		cerr << "BURST ERROR " << line << " " << pass << ' ' << begin << ' ' << (begin + adjlen) << '/' << end  << ' ' << endl;
        } else {
		prev_offset_begin = begin - orig_begin;
		prev_offset_end = begin - orig_begin;
	}

	cerr << line << " GAP " << begin - prev_begin << ' ' << prev_begin << ' ' << begin << endl;
	
	frame[oline][0] = (tgt_nphase != 0) ? 32768 : 16384; 
	frame[oline][1] = plevel1; 

	prev_begin = begin;

	return adjlen;
}

//uint16_t synclevel = 12000;
uint16_t synclevel = 22500; // inbase + (inscale * 15);

bool IsPeak(double *p, int i)
{
	return (p[i] >= p[i - 1]) && (p[i] >= p[i + 1]);
}

double psync[pal_iplinei*1200];

int Process(uint16_t *buf, int len, float *abuf, int alen)
{
	vector<Line> peaks; 

	for (int i = 0; i < len; i++) {
		double val = f_psync8.feed(buf[i]);
		if (i > 16) filtbuf[i - 16] = val;
	}
	
	f_linelen.clear(pal_ipline);

	// sample syncs
	f_syncid.clear(0);

	for (int i = 0; i < len; i++) {
		double val = f_syncid.feed(filtbuf[i] && (filtbuf[i] < synclevel)); 
		if (i > syncid_offset) psync[i - syncid_offset] = val; 
	}

	for (int i = 0; i < len - syncid_offset; i++) {
		double level = psync[i];

		if ((level > .05) && (level > psync [i - 1]) && (level > psync [i + 1])) {
			Line l;

			l.beginsync = i;
			l.endsync = i;
			l.center = i;
			l.peak   = level;
			l.bad = false;
			l.linenum = -1;

			peaks.push_back(l);	
//			cerr << peaks.size() << ' ' << i << ' ' << level << endl;

		}
	}
			
	if (peaks[0].center > (pal_ipline * 300)) {
		return pal_ipline * 300;
	} 

	// find first field index - returned as firstline 
	int firstpeak = -1, firstline = -1, lastline = -1;
	for (int i = 9; (i < peaks.size() - 9) && (firstline == -1); i++) {
		if (peaks[i].peak > 1.0) {
			if (peaks[i].center < (pal_ipline * 8)) {
				return (pal_ipline * 400);
			} else {
				if ((firstpeak < 0) && (peaks[i].center > (pal_ipline * 300))) {
					return pal_ipline * 300;
				} 

				firstpeak = i;
				firstline = -1; lastline = -1;

				cerr << firstpeak << ' ' << peaks[firstpeak].peak << ' ' << peaks[firstpeak].center << endl;
	
				for (int i = firstpeak - 1; (i > 0) && (lastline == -1); i--) {
					if ((peaks[i].peak > 0.2) && (peaks[i].peak < 0.75)) lastline = i;
				}	

				int distance_prev = peaks[lastline + 1].center - peaks[lastline].center;
				int synctype = (distance_prev > (in_freq * 140)) ? 1 : 2;

				if (f_flip) {
					synctype = (distance_prev > (in_freq * 140)) ? 2 : 1;
				}

				cerr << "P1_" << lastline << ' ' << synctype << ' ' << (in_freq * 140) << ' ' << distance_prev << ' ' << peaks[lastline + 1].center - peaks[lastline].center << endl;
	
				for (int i = firstpeak + 1; (i < peaks.size()) && (firstline == -1); i++) {
					if ((peaks[i].peak > 0.2) && (peaks[i].peak < 0.75)) firstline = i;
				}	
	
				cerr << firstline << ' ' << peaks[firstline].center - peaks[firstline-1].center << endl;

				cerr << synctype << ' ' << writeonfield << endl;
				if (synctype != writeonfield) {
					firstline = firstpeak = -1; 
					i += 6;
				}
			}
		}
	}

	cerr << "# of peaks # " << peaks.size() << endl;

	bool field2 = false;
	int line = -10;
	double prev_linelen = 1832;

	for (int i = firstline - 2; (i < (firstline + 650)) && (line < 623) && (i < peaks.size()); i++) {
//		cerr << "P2A " << i << ' ' << peaks[i].peak << endl;
		bool canstartsync = false;
		if ((line < 0) || InRange(line, 310, 317) || InRange(line, 623, 630)) canstartsync = true;

		if (!canstartsync && ((peaks[i].center - peaks[i - 1].center) > (440 * in_freq)) && (peaks[i].center > peaks[i - 1].center)) {
			// looks like we outright skipped a line because of corruption.  add a new one! 
			cerr << "LONG " << i << ' ' << peaks[i].center << ' ' << peaks[i].center - peaks[i - 1].center << ' ' << peaks.size() << endl ;

			Line l;

			l.center = peaks[i - 1].center + 1820;
			l.peak   = peaks[i - 1].peak;
			l.bad = true;
			l.linenum = -1;

			peaks.insert(peaks.begin()+i, l);

			i--;
			line--;
		} else if (!canstartsync && ((peaks[i].center - peaks[i - 1].center) < (207.5 * in_freq)) && (peaks[i].center > peaks[i - 1].center)) {
			cerr << "SHORT " << i << ' ' << peaks[i].center << ' ' << peaks[i].center - peaks[i - 1].center << ' ' << peaks.size() << endl ;
			peaks.erase(peaks.begin()+i);
			i--;
//			cerr << "ohoh." << i << ' ' << peaks.size() << endl ;
			line--;
		} else if (InRange(peaks[i].peak, canstartsync ? .25 : .0, .5)) {
			int cbeginsync = 0, cendsync = 0;
			int center = peaks[i].center;

			if (line <= -1) {
				line = field2 ? 318 : 10;
				field2 = true;
			}

			peaks[i].beginsync = peaks[i].endsync = -1;
			for (int x = 0; x < 200 && InRange(peaks[i].peak, .20, .5) && ((peaks[i].beginsync == -1) || (peaks[i].endsync == -1)); x++) {
				cbeginsync++;
				cendsync++;
	
				if (buf[center - x] < 26500) cbeginsync = 0;
				if (buf[center + x] < 26500) cendsync = 0;

				if ((cbeginsync == 4) && (peaks[i].beginsync < 0)) peaks[i].beginsync = center - x + 4;			
				if ((cendsync == 4) && (peaks[i].endsync < 0)) peaks[i].endsync = center + x - 4;			
			}

			// this is asymetric since on an NTSC player playback is sped up to 1820 pixels/line 
			double prev_linelen_cf = clamp(prev_linelen / in_freq, 224, 232);

			peaks[i].bad = !InRangeF(peaks[i].endsync - peaks[i].beginsync, 14.5, 20.5);

			if (!peaks[i - 1].bad) peaks[i].bad |= get_oline(line) > 22 && (!InRangeF(peaks[i].beginsync - peaks[i-1].beginsync, prev_linelen_cf - f_tol, prev_linelen_cf + f_tol) || !InRangeF(peaks[i].endsync - peaks[i-1].endsync, prev_linelen_cf - f_tol, prev_linelen_cf + f_tol)); 

			peaks[i].linenum = line;
			
			cerr << "P2_" << line << ' ' << i << ' ' << peaks[i].bad << ' ' <<  peaks[i].peak << ' ' << peaks[i].center << ' ' << peaks[i].center - peaks[i-1].center << ' ' << peaks[i].beginsync << ' ' << peaks[i].endsync << ' ' << peaks[i].endsync - peaks[i].beginsync << ' ' << peaks[i].beginsync - peaks[i-1].beginsync << ' ' << prev_linelen << endl;
				
			// HACK!
			if (line == 318) peaks[i].linenum = -1;

			// if we have a good line, feed it's length to the line LPF.  The 8 line lag is insignificant 
			// since it's a ~30hz oscillation. 
			double linelen = peaks[i].beginsync - peaks[i-1].beginsync;
			if (!peaks[i].bad && !peaks[i - 1].bad && InRangeF(linelen, 227.5 - 4, 229 + 4)) {
//				cerr << "feeding " << linelen << endl;
				prev_linelen = f_linelen.feed(linelen);
			}
		} else if (peaks[i].peak > .9) {
			line = -10;
			peaks[i].linenum = -1;
		}
		line++;
	}

	line = -1;	
	for (int i = firstline - 1; (i < (firstline + 650)) && (line < 623) && (i < peaks.size()); i++) {
		cerr << "proc " << i << endl;
		if (peaks[i].linenum > 0) {
			line = peaks[i].linenum ;
			if (peaks[i].bad) {
				cerr << "BAD " << i << ' ' << line << ' ';
				cerr << peaks[i].beginsync << ' ' << peaks[i].center << ' ' << peaks[i].endsync << ' ' << peaks[i].endsync - peaks[i].beginsync << endl;

				int lg = 1;

				for (lg = 1; lg < 8 && (peaks[i - lg].bad || peaks[i + lg].bad); lg++);

				cerr << peaks[i-lg].beginsync << ' ' << peaks[i-lg].center << ' ' << peaks[i-lg].endsync << ' ' << peaks[i-lg].endsync - peaks[i-lg].beginsync << endl;
				cerr << "BADLG " << lg << ' ';
				double gap = (peaks[i + lg].beginsync - peaks[i - lg].beginsync) / 2;
				peaks[i].beginsync = peaks[i - lg].beginsync + (gap * lg); 
				peaks[i].center = peaks[i - lg].center + (gap * lg); 
				peaks[i].endsync = peaks[i - lg].endsync + (gap * lg); 
				cerr << peaks[i].beginsync << ' ' << peaks[i].center << ' ' << peaks[i].endsync << ' ' << peaks[i].endsync - peaks[i].beginsync << endl;
				cerr << peaks[i+lg].beginsync << ' ' << peaks[i+lg].center << ' ' << peaks[i+lg].endsync << ' ' << peaks[i+lg].endsync - peaks[i+lg].beginsync << endl;
			}
		}
	}

	line = -1;	
	for (int i = firstline - 1; (i < (firstline + 650)) && (line < 623) && (i < peaks.size()); i++) {
		if ((peaks[i].linenum > 0) && (peaks[i].linenum <= 625)) {
			line = peaks[i].linenum ;
			cerr << line << ' ' << i << ' ' << peaks[i].bad << ' ' <<  peaks[i].peak << ' ' << peaks[i].center << ' ' << peaks[i].center - peaks[i-1].center << ' ' << peaks[i].beginsync << ' ' << peaks[i].endsync << ' ' << peaks[i].endsync - peaks[i].beginsync << endl;
				
			double send = peaks[i - 1].beginsync + ((peaks[i].beginsync - peaks[i - 1].beginsync) * scale_linelen);
					
			double linelen = ProcessLine(buf, peaks, i); 

			cerr << "PA " << (line / 625.0) + frameno << ' ' << v_read + peaks[i].beginsync << endl;
			ProcessAudio((line / 625.0) + frameno, v_read + peaks[i].beginsync, abuf); 
				
			if (peaks[i].bad) {
				int oline = get_oline(line);
                		frame[oline][2] = 65000;
		                frame[oline][3] = 48000;
          		        frame[oline][4] = 65000;
		                frame[oline][5] = 48000;
			}
		}
	}

	frameno++;
	cerr << "WRITING\n";
	write(1, frame, sizeof(frame));
	memset(frame, 0, sizeof(frame));

	if (!freeze_frame && phase >= 0) phase = !phase;
	
	return peaks[firstline + 500].center;
}

bool seven_five = (in_freq == 4);
double low = 65535, high = 0;

double f[vblen];

void autoset(uint16_t *buf, int len, bool fullagc = true)
{
	int lowloc = -1;
	int checklen = (int)(in_freq * 4);

	if (!fullagc) {
		low = 65535;
		high = 0;
	}

	cerr << "old base:scale = " << inbase << ':' << inscale << endl;
	
//	f_longsync.clear(0);

	// phase 1:  get low (-40ire) and high (??ire)
	for (int i = 0; i < len; i++) {
		f[i] = f_longsync.feed(buf[i]);

		if ((i > (in_freq * 256)) && (f[i] < low) && (f[i - checklen] < low)) {
			if (f[i - checklen] > f[i]) 
				low = f[i - checklen];
			else 
				low = f[i];

			lowloc = i;
		}
		
		if ((i > (in_freq * 256)) && (f[i] > high) && (f[i - checklen] > high)) {
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

		for (nloc = lowloc; (nloc > lowloc - (in_freq * 320)) && (f[nloc] < (low + (gap / 8))); nloc--);

		cerr << nloc << ' ' << (lowloc - nloc) / in_freq << ' ' << f[nloc] << endl;

		nloc -= (in_freq * 4);
		cerr << nloc << ' ' << (lowloc - nloc) / in_freq << ' ' << f[nloc] << endl;
	
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
	bool do_autoset = (in_freq == 4);
	long long dlen = -1;
	unsigned char *cinbuf = (unsigned char *)inbuf;
	unsigned char *cabuf = (unsigned char *)abuf;

	int c;

	cerr << std::setprecision(10);

	opterr = 0;
	
	while ((c = getopt(argc, argv, "dHmhgs:n:i:a:AfFt:r:")) != -1) {
		switch (c) {
			case 'd':	// show differences between pixels
				f_diff = true;
				break;
			case 'm':	// "magnetic video" mode - bottom field first
				writeonfield = 1;
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
			case 't':
				sscanf(optarg, "%lf", &f_tol);		
				break;
			case 'r':
				sscanf(optarg, "%lf", &p_rotdetect);		
				break;
			default:
				return -1;
		} 
	} 

	cerr << "freq = " << in_freq << endl;

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
		cerr << "plen " << plen << endl;
	
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
