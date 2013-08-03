/* LD decoder prototype, Copyright (C) 2013 Chad Page.  License: LGPL2 */

#include <stdio.h>
#include <iostream>
#include <iomanip>
#include <vector>
#include <list>
#include <queue>
#include <complex>
#include <unistd.h>
#include <sys/fcntl.h>
#include <fftw3.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>

// capture frequency and fundamental NTSC color frequency
const double CHZ = (1000000.0*(315.0/88.0)*8.0);
const double FSC = (1000000.0*(315.0/88.0));

using namespace std;

double ctor(double r, double i)
{
	return sqrt((r * r) + (i * i));
}

inline double dftc(double *buf, int offset, int len, double bin, double &fc, double &fci) 
{
	fc = 0.0; fci = 0.0;

	for (int k = (-len + 1); k < len; k++) {
//		cout << offset + k << ' ' << len << endl;
		double o = buf[offset + k]; 
		
		fc += (o * cos((2.0 * M_PIl * ((double)(offset - k) / bin)))); 
		fci -= (o * sin((2.0 * M_PIl * ((double)(offset - k) / bin)))); 
	}

	return ctor(fc, fci);
}

inline double dft(double *buf, int offset, int len, double bin) 
{
	double fc, fci;

	dftc(buf, offset, len, bin, fc, fci);

	return ctor(fc, fci);
}

/* Linear difference equation - used for running filters (compute with Octave, etc) */

class LDE {
	protected:
		int order;
		const double *a, *b;
		double *y, *x;
	public:
		LDE(int _order, const double *_a, const double *_b) {
			order = _order + 1;
			a = _a;
			b = _b;
			x = new double[order];
			y = new double[order];
	
			clear();
		}

		LDE(LDE *orig) {
			order = orig->order;
			a = orig->a;
			b = orig->b;
			x = new double[order];
			y = new double[order];
				
			clear();
		}

		~LDE() {
//			delete [] x;
//			delete [] y;
		}

		void clear(double val = 0) {
			for (int i = 0; i < order; i++) {
				x[i] = y[i] = val;
			}
		}

		inline double feed(double val) {
			double a0;

			if (!a) a0 = 1;

			for (int i = order - 1; i >= 1; i--) {
				x[i] = x[i - 1];
				if (a) y[i] = y[i - 1];
			}
		
			x[0] = val;
	
			y[0] = ((b[0] / a0) * x[0]);
			//cerr << "0 " << x[0] << ' ' << b[0] << ' ' << (b[0] * x[0]) << ' ' << y[0] << endl;
			for (int o = 1; o < order; o++) {
				y[0] += ((b[o] / a0) * x[o]);
				if (a) y[0] -= ((a[o] / a[0]) * y[o]);
				//cerr << o << ' ' << x[o] << ' ' << y[o] << ' ' << a[o] << ' ' << b[o] << ' ' << (b[o] * x[o]) << ' ' << -(a[o] * y[o]) << ' ' << y[0] << endl;
			}

			return y[0];
		}
		double val() {return y[0];}
};

// longer-duration .5mhz filter, used for sync

const double f_0_5mhz_b[] {2.8935325675960790e-03, 3.4577251216393609e-03, 4.7838244505790843e-03, 6.9572831696391620e-03, 1.0011907953112537e-02, 1.3924181711788889e-02, 1.8611409324653432e-02, 2.3933941132695716e-02, 2.9701434113594740e-02, 3.5682813848999163e-02, 4.1619323616848357e-02, 4.7239811465409724e-02, 5.2277230286682991e-02, 5.6485223640968835e-02, 5.9653649812310708e-02, 6.1621960508198896e-02, 6.2289494550564671e-02, 6.1621960508198896e-02, 5.9653649812310708e-02, 5.6485223640968821e-02, 5.2277230286682998e-02, 4.7239811465409724e-02, 4.1619323616848378e-02, 3.5682813848999170e-02, 2.9701434113594740e-02, 2.3933941132695712e-02, 1.8611409324653432e-02, 1.3924181711788901e-02, 1.0011907953112541e-02, 6.9572831696391620e-03, 4.7838244505790896e-03, 3.4577251216393622e-03, 2.8935325675960790e-03 };

// 4.2mhz filter
const double f_inband4_b[] {0.0208161638876772, 0.2314704348431369, 0.4954268025383716, 0.2314704348431369, 0.0208161638876772};

const double f_inband8_b[] {-3.5634174409531622e-03, 9.4654740832740107e-03, 9.1456278081537348e-02, 2.4141004764330087e-01, 3.2246323526568188e-01, 2.4141004764330090e-01, 9.1456278081537348e-02, 9.4654740832740124e-03, -3.5634174409531609e-03}; 

//const double f_inband7_b[] { 2.0639067636214502e-02, 6.5484287559733512e-02, 1.6641090209130313e-01, 2.4746574271274874e-01, 2.4746574271274879e-01, 1.6641090209130316e-01, 6.5484287559733539e-02, 2.0639067636214502e-02 }; 

const double f_inband7_b[] { -6.2211448918489030e-04, 2.8265367663495418e-02, 1.5675884606312396e-01, 3.1559790076256550e-01, 3.1559790076256550e-01, 1.5675884606312396e-01, 2.8265367663495432e-02, -6.2211448918488910e-04};

// 8-tap 3.5mhz high-pass fir1
const double f_hp8_b[] {-5.2233122995139940e-04, -1.7082609318519331e-02, -8.5929313061105295e-02, -1.9084603032392095e-01, 7.5704600929723254e-01, -1.9084603032392097e-01, -8.5929313061105309e-02, -1.7082609318519335e-02, -5.2233122995139940e-04};

const double f_butter4_a[] {1.0000000000000000, -1.6232715948812961, 1.3304266228523409, -0.5121023075052276, 0.0810552055606200};
const double f_butter4_b[] {0.0172567453766523, 0.0690269815066093, 0.1035404722599139, 0.0690269815066093, 0.0172567453766523};

const double f_butter6_a[] {1.0000000000000000, -2.4594002236413273, 3.0570327078873287, -2.1912939461291545, 0.9464602376928106, -0.2285198647947151, 0.0239658552682254};
const double f_butter6_b[] {0.0023163244731745, 0.0138979468390470, 0.0347448670976174, 0.0463264894634899, 0.0347448670976174, 0.0138979468390470, 0.0023163244731745};

const double f_butter8_a[] {1.0000000000000000, -3.2910431389188823, 5.4649816845801347, -5.5946268902911909, 3.8014233895293916, -1.7314645265989386, 0.5125138525205987, -0.0895781664897369, 0.0070486692595647};
const double f_butter8_b[] {0.0003095893499646, 0.0024767147997169, 0.0086685017990093, 0.0173370035980186, 0.0216712544975232, 0.0173370035980186, 0.0086685017990093, 0.0024767147997169, 0.0003095893499646};

//const double f_boost6_b[] {0.0171085311223133, 0.0066159866434093, -0.0287374093196349, -1.4956846203123810, 4.1364660365098924, -1.4956846203123810, -0.0287374093196349, 0.0066159866434093, 0.0171085311223133};
//const double f_boost6_b[] {0.0254170399264351, -0.0059024716440027, -0.0364988745431467, -1.8598195331511393, 4.9380431080332725, -1.8598195331511400, -0.0364988745431467, -0.0059024716440027, 0.0254170399264351};
// fir2(8, [0, 4/freq, 5/freq, 6/freq, 10/freq, 1], [1.0, 1.0, 2, 3, 4, 5])
const double f_boost6_b[] {0.0111989816340250, 0.0048865621882266, -0.0481490541009254, -0.8694087656392513, 2.8936261819359768, -0.8694087656392512, -0.0481490541009254, 0.0048865621882266, 0.0111989816340250};
//const double f_boost6_b[] {0.0168027211008027, 0.0022145267218688, 0.0416814439546960, -1.4449168967980353, 3.8620269283049078, -1.4449168967980355, 0.0416814439546960, 0.0022145267218688, 0.0168027211008027};

const double f_2_0mhz_b[] { 2.0725950133615822e-03, -8.3463967955793583e-04, -9.7490566449315967e-03, -2.1735983355962385e-02, -1.4929346936560809e-02, 3.7413352363703849e-02, 1.3482681278026168e-01, 2.3446159984589487e-01, 2.7694933322758158e-01, 2.3446159984589490e-01, 1.3482681278026165e-01, 3.7413352363703870e-02, -1.4929346936560811e-02, -2.1735983355962385e-02, -9.7490566449315984e-03, -8.3463967955793670e-04, 2.0725950133615822e-03 };
const double f_2_0mhz_a[16] {1, 0};

const double f28_1_3mhz_b[] {-1.606520060122928e-03, -1.655407847264293e-03, -1.775562785865866e-03, -1.613365514625196e-03, -6.608951305251436e-04, 1.658880771815467e-03, 5.878138286414544e-03, 1.236192372717719e-02, 2.120122219652129e-02, 3.214365150841308e-02, 4.457824331557173e-02, 5.758147137495655e-02, 7.002060196594841e-02, 8.069966942725533e-02, 8.852500613801824e-02, 9.266294262631157e-02, 9.266294262631157e-02, 8.852500613801825e-02, 8.069966942725534e-02, 7.002060196594842e-02, 5.758147137495655e-02, 4.457824331557171e-02, 3.214365150841310e-02, 2.120122219652130e-02, 1.236192372717719e-02, 5.878138286414545e-03, 1.658880771815467e-03, -6.608951305251436e-04, -1.613365514625196e-03, -1.775562785865866e-03, -1.655407847264294e-03, -1.606520060122928e-03};

const double f28_0_6mhz_b[] {2.418525441220349e-03, 3.032499155527502e-03, 4.402843624075901e-03, 6.673297306993343e-03, 9.925756676326794e-03, 1.416822744109794e-02, 1.932851039649254e-02, 2.525438455323643e-02, 3.172049685116917e-02, 3.844158358553873e-02, 4.509108637168183e-02, 5.132373645854953e-02, 5.680031079400327e-02, 6.121254638517508e-02, 6.430615740210396e-02, 6.590003755680766e-02, 6.590003755680766e-02, 6.430615740210398e-02, 6.121254638517508e-02, 5.680031079400327e-02, 5.132373645854953e-02, 4.509108637168181e-02, 3.844158358553876e-02, 3.172049685116920e-02, 2.525438455323643e-02, 1.932851039649254e-02, 1.416822744109794e-02, 9.925756676326791e-03, 6.673297306993343e-03, 4.402843624075902e-03, 3.032499155527506e-03, 2.418525441220350e-03};

const double f_lpf02_64_b[] {1.785079571600233e-03, 1.871256387908000e-03, 2.060891268622261e-03, 2.358034740999874e-03, 2.765349920913731e-03, 3.284041202271052e-03, 3.913803237428164e-03, 4.652791269950761e-03, 5.497613560998612e-03, 6.443346315818078e-03, 7.483571172591150e-03, 8.610434967691238e-03, 9.814731144807718e-03, 1.108600183600479e-02, 1.241265931607188e-02, 1.378212522282291e-02, 1.518098565036490e-02, 1.659515996448901e-02, 1.801008096351505e-02, 1.941088381791982e-02, 2.078260107111147e-02, 2.211036087436589e-02, 2.337958556314357e-02, 2.457618766098266e-02, 2.568676042142219e-02, 2.669876008772367e-02, 2.760067716357312e-02, 2.838219414379064e-02, 2.903432734998789e-02, 2.954955074908480e-02, 2.992189989900669e-02, 3.014705446157090e-02, 3.022239804289450e-02, 3.014705446157089e-02, 2.992189989900668e-02, 2.954955074908479e-02, 2.903432734998789e-02, 2.838219414379064e-02, 2.760067716357312e-02, 2.669876008772367e-02, 2.568676042142220e-02, 2.457618766098266e-02, 2.337958556314357e-02, 2.211036087436589e-02, 2.078260107111148e-02, 1.941088381791982e-02, 1.801008096351506e-02, 1.659515996448901e-02, 1.518098565036491e-02, 1.378212522282292e-02, 1.241265931607188e-02, 1.108600183600479e-02, 9.814731144807716e-03, 8.610434967691242e-03, 7.483571172591156e-03, 6.443346315818077e-03, 5.497613560998612e-03, 4.652791269950765e-03, 3.913803237428165e-03, 3.284041202271053e-03, 2.765349920913733e-03, 2.358034740999874e-03, 2.060891268622262e-03, 1.871256387907999e-03, 1.785079571600233e-03};

const double f_lpf30_b7_a[] {1.000000000000000e+00, -1.001752925667820e+01, 4.818012448934698e+01, -1.474362068100452e+02, 3.209452996998522e+02, -5.266697808887541e+02, 6.738478922002332e+02, -6.859158541504489e+02, 5.618723553981042e+02, -3.722260094293712e+02, 1.992906245125886e+02, -8.569286834120848e+01, 2.921444510991529e+01, -7.727318853556639e+00, 1.530726275923486e+00, -2.139064948453619e-01, 1.882054672323584e-02, -7.847626261975797e-04};
const double f_lpf30_b7_b[] {2.231228112437725e-10, 3.793087791144133e-09, 3.034470232915306e-08, 1.517235116457653e-07, 5.310322907601786e-07, 1.380683955976464e-06, 2.761367911952929e-06, 4.339292433068888e-06, 5.424115541336110e-06, 5.424115541336110e-06, 4.339292433068888e-06, 2.761367911952929e-06, 1.380683955976464e-06, 5.310322907601786e-07, 1.517235116457653e-07, 3.034470232915306e-08, 3.793087791144133e-09, 2.231228112437725e-10};

const double f_lpf30_32_b[] {-1.386894684039784e-03, -7.392108445957141e-04, 6.528422922646250e-04, 3.039709459458449e-03, 5.697141304519828e-03, 6.569233424905397e-03, 3.075613418906020e-03, -6.006254594139485e-03, -1.855650972427626e-02, -2.842165268593719e-02, -2.698327706840176e-02, -6.785002057053770e-03, 3.428376859229806e-02, 9.040001150127136e-02, 1.484856228852927e-01, 1.923408150190244e-01, 2.086680875210060e-01, 1.923408150190244e-01, 1.484856228852927e-01, 9.040001150127136e-02, 3.428376859229806e-02, -6.785002057053770e-03, -2.698327706840176e-02, -2.842165268593720e-02, -1.855650972427626e-02, -6.006254594139486e-03, 3.075613418906019e-03, 6.569233424905402e-03, 5.697141304519829e-03, 3.039709459458449e-03, 6.528422922646255e-04, -7.392108445957147e-04, -1.386894684039784e-03}; 

const double f_lpf02_b1_a[] {1.000000000000000e+00, -9.999937186442455e-01}; 
const double f_lpf02_b1_b[] {3.140677877222177e-06, 3.140677877222177e-06}; 

const double f_lpburst_a[] {1.000000000000000, -1.570398851228172, 1.275613324983280, -0.484403368335086, 0.076197064610332};
const double f_lpburst_b[] {0.018563010626897, 0.074252042507589, 0.111378063761383, 0.074252042507589, 0.018563010626897}; 

const double f_hp32_b[] { 2.727748521075775e-03, 2.493444033678934e-02, 1.071670557197850e-01, 2.243407006421851e-01, 2.816601095603296e-01, 2.243407006421851e-01, 1.071670557197850e-01, 2.493444033678935e-02, 2.727748521075775e-03};

const double f_hp35_14_b[] {2.920242503210705e-03, 6.624873097752306e-03, 1.019323615024227e-02, -2.860428785028677e-03, -5.117884625321341e-02, -1.317695333943684e-01, -2.108392223608709e-01, 7.582009982420270e-01, -2.108392223608709e-01, -1.317695333943685e-01, -5.117884625321342e-02, -2.860428785028680e-03, 1.019323615024228e-02, 6.624873097752300e-03, 2.920242503210705e-03};

const double f_hp35_b7_a[] { 1.000000000000000e+00, -3.560303553782462e+00, 5.933262502831511e+00, -5.806826093963448e+00, 3.560914834236377e+00, -1.356645514969462e+00, 2.956929537894906e-01, -2.832366986279234e-02};
const double f_hp35_b7_b[] {1.682966337768402e-01, -1.178076436437882e+00, 3.534229309313644e+00, -5.890382182189407e+00, 5.890382182189407e+00, -3.534229309313644e+00, 1.178076436437882e+00, -1.682966337768402e-01}; 

const double f_a[256] {1,};

const double zero = 7600000.0;
const double one = 9400000.0;
const double mfactor = 65536.0 / (one - zero);

const int linelen = 2048;

// todo?:  move into object

const int low = 7400000, high=9800000, bd = 300000;
const int nbands = ((high + 1 - low) / bd);

double fbin[nbands];

LDE lpf45(7, NULL, f_inband7_b);

struct FreqBand : public vector<double> {
	public:
		double flow, fhigh, gap;
		double fbase;

		FreqBand(double _fbase = CHZ, double _flow = 7500000, double _fhigh = 9600000, double _gap = 100000) {
	//	FreqBand(double _fbase = CHZ, double _flow = 7600000, double _fhigh = 9300000, double _gap = 250000) {
			flow = _flow;
			fhigh = _fhigh;
			gap = _gap;
			fbase = _fbase;
			
			int numbands = floor(((fhigh - flow) / gap) + 1);

			for (int i = 0; i < numbands; i++) push_back(flow + (gap * i));
		}
};

typedef vector<complex<double>> cossin;

class FM_demod {
	protected:
		vector<LDE> f_q, f_i;
		LDE *f_pre, *f_post;
		vector<cossin> ldft;
	
		int linelen;

		int min_offset;

		FreqBand fb;
	public:
		FM_demod(int _linelen, FreqBand _fb, LDE *prefilt, LDE *filt, LDE *postfilt) {
			linelen = _linelen;

			fb = _fb;

			for (double f : fb) {
				cossin tmpdft;
				double fmult = f / fb.fbase; 

				for (int i = 0; i < linelen; i++) {
					tmpdft.push_back(complex<double>(sin(i * 2.0 * M_PIl * fmult), cos(i * 2.0 * M_PIl * fmult))); 
				}	
				ldft.push_back(tmpdft);

				f_i.push_back(LDE(filt));
				f_q.push_back(LDE(filt));
			}
	
			f_pre = prefilt ? new LDE(*prefilt) : NULL;
			f_post = postfilt ? new LDE(*postfilt) : NULL;

			min_offset = 128;
		}

		vector<double> process(vector<double> in) 
		{
			vector<double> out;
			vector<double> phase(fb.size() + 1);
			double avg = 0, total = 0.0;

			if (in.size() < (size_t)linelen) return out;

			for (double n : in) avg += n / in.size();

			int i = 0;
			for (double n : in) {
				vector<double> level(fb.size() + 1);
				double peak = 500000, pf = 0.0;
				int npeak;
				int j = 0;

				n -= avg;
				total += fabs(n);
				if (f_pre) n = f_pre->feed(n);

				level[j] = 0;

				cerr << n << endl;
	
//				auto c = ldft[j]->begin(); 
				for (double f: fb) {
					double fci = f_i[j].feed(n * ldft[j][i].real());
					double fcq = f_q[j].feed(-n * ldft[j][i].imag());
		
//					cerr << fci << ' ' << fcq << endl;
	
					level[j] = atan2(fci, fcq) - phase[j];
					if (level[j] > M_PIl) level[j] -= (2 * M_PIl);
					else if (level[j] < -M_PIl) level[j] += (2 * M_PIl);
						
					if (fabs(level[j]) < fabs(peak)) {
						npeak = j;
						peak = level[j];
						pf = f + ((f / 2.0) * level[j]);
					}
					phase[j] = atan2(fci, fcq);

//					cerr << f << ' ' << pf << ' ' << fci << ' ' << fcq << ' ' << level[j] << ' ' << phase[j] << ' ' << peak << endl;

					j++;
				}
	
				double thisout = pf;	
				if (f_post) thisout = f_post->feed(pf);	
				if (i > min_offset) out.push_back(thisout);
				i++;
			}
/*		
			double avgout = 0.0;	
			for (double n : out) {
				n = (n - zero) / (9400000.0 - 7600000.0);
				avgout += n / out.size();
			}
			
			double sdev = 0.0;	
			for (double n : out) {
				sdev += ((n - avgout) * (n - avgout));
			}
*/

			cerr << total / in.size() << endl;
			return out;
		}
};

inline double IRE(double in) 
{
	return (in * 140.0) - 40.0;
}

struct YIQ {
	double y, i, q;

	YIQ(double _y = 0.0, double _i = 0.0, double _q = 0.0) {
		y = _y; i = _i; q = _q;
	};
};

double clamp(double v, double low, double high)
{
	if (v < low) return low;
	else if (v > high) return high;
	else return v;
}

struct RGB {
	double r, g, b;

	void conv(YIQ y) { 
		y.i = clamp(y.i, -0.5957, .5957);
		y.q = clamp(y.q, -0.5226, .5226);

		y.y -= (.4 / 1.4);
		y.y *= 1.4; 
		y.y = clamp(y.y, 0, 1);

//		r = y.y + 0.9563 * y.i + 0.6210 * y.q; 
//		g = y.y - 0.2721 * y.i - 0.6474 * y.q; 
//		b = y.y - 1.1070 * y.i + 1.7046 * y.q; 

		r = (y.y * 1.164) + (1.596 * y.i);
		g = (y.y * 1.164) - (0.813 * y.i) - (y.q * 0.391);
		b = (y.y * 1.164) + (y.q * 2.018);

		r = clamp(r, 0, 1);
		g = clamp(g, 0, 1);
		b = clamp(b, 0, 1);
		//cerr << 'y' << y.y << " i" << y.i << " q" << y.q << ' ';
		//cerr << 'r' << r << " g" << g << " b" << b << endl;
	};
};

class NTSColor {
	protected:
		LDE *f_i, *f_q, *f_sync, *f_burst;
		double fc, fci;
		double freq;

		int counter, lastsync;
		bool insync;

		double phase, level;
		int phase_count;
		bool phased;

		double nextphase;
		int nextphase_count;
	
		list<double> prev;

		vector<YIQ> *buf;

		int igap;
	public:
		bool get_newphase(double &np) {
			if (phased) {
				np = phase;
				phased = false;
				return true;
			} else return false;
		}	

		void set_phase(double np) {
			nextphase = np;
			nextphase_count = counter + 1820;
		}

		NTSColor(vector<YIQ> *_buf = NULL, double _freq = 8.0) {
			nextphase_count = lastsync = -1;
			counter = 0;
			phased = insync = false;

			level = phase = 0.0;

			freq = _freq;

			buf = _buf;

			igap = -1;

			f_i = new LDE(31, NULL, f28_1_3mhz_b);
			f_q = new LDE(31, NULL, f28_1_3mhz_b);
			
			f_sync = new LDE(31, NULL, f28_0_6mhz_b);
			f_burst = new LDE(4, f_lpburst_a, f_lpburst_b);
		}

		YIQ feed(double in) {
			counter++;
			if (lastsync >= 0) lastsync++;

			f_sync->feed(in);

//			cerr << insync << ' ' << lastsync << endl;

			prev.push_back(in);	
			if (prev.size() > 32) prev.pop_front();

			int count = 0;
			if (insync == false) {
				for (double v: prev) {
					if (v < 0.1) {
						count++;
					}
				}
				if (count >= 24) {
                                        for (int i = lastsync; i >= 0 && i < 1820; i++) {
                                               if (buf) buf->push_back(YIQ(0,0,0));
                                        }
					igap = lastsync;

					lastsync = 0;

					//cerr << "sync at " << counter - 24 << ' ' << igap << endl;
					insync = true;
					prev.clear();
				}

				if (counter == nextphase_count) phase = nextphase; 
				// average 20 color value samples to get phase/level
				if ((lastsync >= 186) && (lastsync < 210)) {
					fc = f_q->val();
					fci = f_i->val();
				} else if ((igap > 1000) && lastsync == 210) {
					level = f_burst->feed(ctor(fc, fci));
					if (nextphase_count < 0) {
						phase -= atan2(fci, ctor(fc, fci));
						phased = true;
						phase_count = counter;
						//cerr << "level " << level << " q " << fc / 20 << " i " << fci / 20 << " phase " << atan2(fci, ctor(fc, fci)) << " cphase " << phase << ' ' << igap << ' ' << f_sync->val() << endl ;
					}
				}
			} else {
				if (lastsync == 16) {
					//cerr << "fsync " << (f_sync->val() * 1700000) + 7600000 << ' ' << igap << endl; 
				}
				for (double v: prev) {
					if (v > 0.2) count++;
				}
				if (count >= 16) {
					insync = false;
					prev.clear();
					fc = fci = 0;
				}
			}

			double curphase = phase;
			if (nextphase_count > counter) {
				int gap = nextphase_count - phase_count;

				curphase = (phase * (1.0 - ((counter - phase_count) / (double)gap)));
				curphase += (nextphase * (((counter - phase_count) / (double)gap)));

				//cerr << 'C' << counter << ' ' <<  phase << ' ' << curphase << ' ' << nextphase << endl;
			}

                        double q = f_q->feed(in * cos(curphase + (2.0 * M_PIl * ((double)(counter) / freq))));
			double i = f_i->feed(-in * sin(curphase + (2.0 * M_PIl * ((double)(counter) / freq))));

			if (buf && (lastsync >= 0) && (lastsync < 1820)) {
				double y = in;

				if (prev.size() > 17) {
					list<double>::iterator cur = prev.begin();
	
					for (int i = 0; i < (prev.size() - 16); i++, cur++);	
					y = *cur;
				}

				//cerr << "i " << i << " q " << q << " y " << y;
				y += i * 2 * (cos(curphase + (2.0 * M_PIl * (((double)(counter - 17) / freq)))));
                               y += q * 2 * (sin(curphase + (2.0 * M_PIl * (((double)(counter - 17) / freq))))); //cerr << " " << y << endl;
				YIQ outc = YIQ(y, i * (.2 / level), q * (.2 / level));
//				YIQ outc = YIQ(y, 0,0);
				if (!lastsync) outc.y = 1.0;
				buf->push_back(outc);	
			}

			return YIQ();
		}
};

int main(int argc, char *argv[])
{
	int rv = 0, fd = 0, dlen = -1 ;
	//double output[2048];
	unsigned char inbuf[2048];

	cerr << std::setprecision(10);

	cerr << argc << endl;

	cerr << strncmp(argv[1], "-", 1) << endl;

	if (argc >= 2 && (strncmp(argv[1], "-", 1))) {
		fd = open(argv[1], O_RDONLY);
	}

	if (argc >= 3) {
		unsigned long long offset = atoll(argv[2]);

		if (offset) lseek64(fd, offset, SEEK_SET);
	}
		
	if (argc >= 4) {
		if ((size_t)atoi(argv[3]) < dlen) {
			dlen = atoi(argv[3]); 
		}
	}

	cout << std::setprecision(8);
	
	rv = read(fd, inbuf, 2048);

	int i = 2048;

//	LDE f_hp35(7, f_hp35_b7_a, f_hp35_b7_b);
	LDE f_hp35(14, NULL, f_hp35_14_b);
	LDE f_lpf30(32, f_lpf30_b7_a, f_lpf30_b7_b);
	LDE f_lpf02(1, f_lpf02_b1_a, f_lpf02_b1_b);
	LDE f_butter6(6, f_butter6_a, f_butter6_b);
	LDE f_boost6(8, NULL, f_boost6_b);

	FreqBand fb(CHZ, 7500000, 9600000, 250000); 
	FreqBand fb_a_left(CHZ, 2150000, 2450000, 10000); 
	FreqBand fb_a_right(CHZ, 2650000, 2950000, 10000); 

	FM_demod a_left(2048, fb_a_left, &f_lpf30, &f_lpf02, NULL);
	FM_demod a_right(2048, fb_a_right, &f_lpf30, &f_lpf02, NULL);

//	FM_demod video(2048, fb, 4, f_butter4_a, f_butter4_b, 7, NULL, f_inband7_b);
	FM_demod video(2048, fb, &f_hp35, &f_butter6, NULL);
//	FM_demod video(2048, fb, 8, f_butter8_a, f_butter8_b, 8, NULL, f_inband8_b);
//	FM_demod video(2048, fb, 8, NULL, f_inband8_b, 7, NULL, f_inband7_b);
//	FM_demod video(2048, fb, 8, NULL, f_inband8_b, 7, NULL, f_inband7_b);
//	FM_demod video(2048, fb, 4, NULL, f_inband4_b, 7, NULL, f_inband7_b);
	
	vector<YIQ> outbuf;	
	NTSColor color, color2(&outbuf);
//	NTSColor color(&outbuf), color2;
	queue<double> delaybuf;

	double nextphase;

	while ((rv == 2048) && ((dlen == -1) || (i < dlen))) {
		vector<double> dinbuf;

		for (int j = 0; j < 2048; j++) dinbuf.push_back(inbuf[j]); 

		vector<double> outline = video.process(dinbuf);
		vector<double> outaudiol = a_left.process(dinbuf);
		vector<double> outaudior = a_right.process(dinbuf);

		vector<unsigned short> bout;

		cerr << outline.size() << ' ' << outaudiol.size() << endl;
//		int agap = outaudiol.size() - outline.size();
		int agap = 0;

		for (int i = 0; i < outline.size(); i++) {
			double n = outline[i];
			double l = outaudiol[i + agap];
			double r = outaudior[i + agap];
//			cerr << n << ' ' << endl;
			n -= 7600000.0;
			n /= (9300000.0 - 7600000.0);
			if (n < 0) n = 0;
			if (n > (65535.0 / 62000.0)) n = (65535.0 / 62000.0);
			color.feed(n);
			if (color.get_newphase(nextphase)) {
				color2.set_phase(nextphase);
			}
			delaybuf.push(n);
			if (delaybuf.size() >= 1820) {
				color2.feed(delaybuf.front());
				delaybuf.pop();
			}
//			bout.push_back(n * 62000.0);

			cerr << outline[i] << ' ' << l << ' ' << r << endl;
		}

//cerr << "z\n";
		for (YIQ i : outbuf) {
			RGB r;
			r.conv(i);
			bout.push_back(r.r * 62000.0);
			bout.push_back(r.g * 62000.0);
			bout.push_back(r.b * 62000.0);
		}
		outbuf.clear();

		unsigned short *boutput = bout.data();
		int len = outline.size();
		if (write(1, boutput, bout.size() * 2) != bout.size() * 2) {
			//cerr << "write error\n";
			exit(0);
		}

		i += len;
		memmove(inbuf, &inbuf[len], 2048 - len);
		rv = read(fd, &inbuf[(2048 - len)], len) + (2048 - len);
		
		if (rv < 2048) return 0;
		cerr << i << ' ' << rv << endl;
	}
	return 0;
}

