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
//			delete x;
//			delete y;
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

//const double f_butter6_a[] {1.0000000000000000, -2.4594002236413273, 3.0570327078873287, -2.1912939461291545, 0.9464602376928106, -0.2285198647947151, 0.0239658552682254};
//const double f_butter6_b[] {0.0023163244731745, 0.0138979468390470, 0.0347448670976174, 0.0463264894634899, 0.0347448670976174, 0.0138979468390470, 0.0023163244731745};

// [n, Wc] = buttord(4.0 / freq, 3.5 / freq, 6, 12); [b, a] = butter(n, Wc)
const double f_butter6_a[] {1.000000000000000e+00, -2.352249761025037e+00, 2.861013965944460e+00, -2.009740195346082e+00, 8.553145693150709e-01, -2.037566682488971e-01, 2.113751308567020e-02};
const double f_butter6_b[] {2.683115995706020e-03, 1.609869597423612e-02, 4.024673993559030e-02, 5.366231991412039e-02, 4.024673993559030e-02, 1.609869597423612e-02, 2.683115995706020e-03};  

//const double f_butter6_a[] {1.000000000000000e+00, -2.176093103298010e+00, 2.558369553340582e+00, -1.736746576197926e+00, 7.220024028506609e-01, -1.682075513126257e-01, 1.715021646708015e-02};
//const double f_butter6_b[] {3.382420966402511e-03, 2.029452579841506e-02, 5.073631449603766e-02, 6.764841932805021e-02, 5.073631449603766e-02, 2.029452579841506e-02, 3.382420966402511e-03};
//const double f_butter6_a[] {1.000000000000000e+00, -1.479015896529934e+00, 1.596890758027192e+00, -9.184863635688618e-01, 3.569843597015975e-01, -7.505248516623388e-02, 7.266546349155719e-03};
//const double f_butter6_b[] {7.634170606451799e-03, 4.580502363871079e-02, 1.145125590967770e-01, 1.526834121290360e-01, 1.145125590967770e-01, 4.580502363871079e-02, 7.634170606451799e-03}; 

const double f_butter8_a[] {1.0000000000000000, -3.2910431389188823, 5.4649816845801347, -5.5946268902911909, 3.8014233895293916, -1.7314645265989386, 0.5125138525205987, -0.0895781664897369, 0.0070486692595647};
const double f_butter8_b[] {0.0003095893499646, 0.0024767147997169, 0.0086685017990093, 0.0173370035980186, 0.0216712544975232, 0.0173370035980186, 0.0086685017990093, 0.0024767147997169, 0.0003095893499646};

// fir2(8, [0, 4/freq, 5/freq, 6/freq, 10/freq, 1], [1.0, 1.0, 2, 3, 4, 5])
//const double f_boost6_b[] {0.0111989816340250, 0.0048865621882266, -0.0481490541009254, -0.8694087656392513, 2.8936261819359768, -0.8694087656392512, -0.0481490541009254, 0.0048865621882266, 0.0111989816340250};
// fir2(8, [0, 3.0/freq, 3.5/freq, 5/freq, 6/freq, 10/freq, 1], [0.0, 0.0, 1.0, 2, 3, 4, 5]) 
//const double f_boost8_b[] {8.226231487511369e-03, -1.760999224010931e-02, -1.354044946940760e-01, -1.040291091550781e+00, 2.684106353139590e+00, -1.040291091550782e+00, -1.354044946940761e-01, -1.760999224010932e-02, 8.226231487511367e-03};
// b = fir2(8, [0, 3.0/freq, 3.5/freq, 4.0/freq, 5/freq, 7/freq, 9/freq, 11/freq, 13/freq, 1], [0.0, 0.0, 0.5, 1.0, 1.2, 1.6, 2.0, 2.4, 2.6, 2.6] 
const double f_boost6_b[] {-4.033954487174667e-03, -3.408583476980324e-02, -5.031202829325306e-01, 1.454592400360107e+00, -5.031202829325309e-01, -3.408583476980324e-02, -4.033954487174666e-03};
const double f_boost8_b[] {1.990859784029516e-03, -1.466569224478291e-02, -3.522213674516057e-02, -6.922384231866260e-01, 1.669825180053711e+00, -6.922384231866261e-01, -3.522213674516058e-02, -1.466569224478292e-02, 1.990859784029516e-03};
const double f_boost16_b[] {1.598977954996517e-04, 3.075456659938196e-03, 9.185596072285866e-03, 1.709531178223861e-02, 3.432562296816891e-03, -3.610562619607920e-02, -9.514006526914356e-02, -6.305237888418010e-01, 1.454592400360107e+00, -6.305237888418012e-01, -9.514006526914358e-02, -3.610562619607921e-02, 3.432562296816892e-03, 1.709531178223861e-02, 9.185596072285866e-03, 3.075456659938199e-03, 1.598977954996517e-04};

const double f_2_0mhz_b[] { 2.0725950133615822e-03, -8.3463967955793583e-04, -9.7490566449315967e-03, -2.1735983355962385e-02, -1.4929346936560809e-02, 3.7413352363703849e-02, 1.3482681278026168e-01, 2.3446159984589487e-01, 2.7694933322758158e-01, 2.3446159984589490e-01, 1.3482681278026165e-01, 3.7413352363703870e-02, -1.4929346936560811e-02, -2.1735983355962385e-02, -9.7490566449315984e-03, -8.3463967955793670e-04, 2.0725950133615822e-03 };
const double f_2_0mhz_a[16] {1, 0};

const double f28_1_3mhz_b[] {-1.606520060122928e-03, -1.655407847264293e-03, -1.775562785865866e-03, -1.613365514625196e-03, -6.608951305251436e-04, 1.658880771815467e-03, 5.878138286414544e-03, 1.236192372717719e-02, 2.120122219652129e-02, 3.214365150841308e-02, 4.457824331557173e-02, 5.758147137495655e-02, 7.002060196594841e-02, 8.069966942725533e-02, 8.852500613801824e-02, 9.266294262631157e-02, 9.266294262631157e-02, 8.852500613801825e-02, 8.069966942725534e-02, 7.002060196594842e-02, 5.758147137495655e-02, 4.457824331557171e-02, 3.214365150841310e-02, 2.120122219652130e-02, 1.236192372717719e-02, 5.878138286414545e-03, 1.658880771815467e-03, -6.608951305251436e-04, -1.613365514625196e-03, -1.775562785865866e-03, -1.655407847264294e-03, -1.606520060122928e-03};

const double f_1_3_b7_a[] {1.000000000000000e+00, -7.396276582145773e+00, 2.443468934606965e+01, -4.730770392148882e+01, 5.913667585513913e+01, -4.948376216668154e+01, 2.771076495156773e+01, -1.001220824786418e+01, 2.117521591068093e+00, -1.996960414398089e-01};
const double f_1_3_b7_b[] {9.344188421209170e-09, 8.409769579088253e-08, 3.363907831635301e-07, 7.849118273815703e-07, 1.177367741072355e-06, 1.177367741072355e-06, 7.849118273815703e-07, 3.363907831635301e-07, 8.409769579088253e-08, 9.344188421209170e-09};

const double f28_0_6mhz_b[] {2.418525441220349e-03, 3.032499155527502e-03, 4.402843624075901e-03, 6.673297306993343e-03, 9.925756676326794e-03, 1.416822744109794e-02, 1.932851039649254e-02, 2.525438455323643e-02, 3.172049685116917e-02, 3.844158358553873e-02, 4.509108637168183e-02, 5.132373645854953e-02, 5.680031079400327e-02, 6.121254638517508e-02, 6.430615740210396e-02, 6.590003755680766e-02, 6.590003755680766e-02, 6.430615740210398e-02, 6.121254638517508e-02, 5.680031079400327e-02, 5.132373645854953e-02, 4.509108637168181e-02, 3.844158358553876e-02, 3.172049685116920e-02, 2.525438455323643e-02, 1.932851039649254e-02, 1.416822744109794e-02, 9.925756676326791e-03, 6.673297306993343e-03, 4.402843624075902e-03, 3.032499155527506e-03, 2.418525441220350e-03};

const double f_lpf048_b4_b[] {5.164738337291061e-10, 2.065895334916424e-09, 3.098843002374636e-09, 2.065895334916424e-09, 5.164738337291061e-10};
const double f_lpf048_b4_a[] {1.000000000000000e+00, -3.975007767097551e+00, 5.925335133687553e+00, -3.925644691784699e+00, 9.753173334582784e-01};

const double f_lpf02_b10_a[] {1.000000000000000e+00, -9.711859090988344e+00, 4.244814355964149e+01, -1.099543302485029e+02, 1.869287195307871e+02, -2.179331623808879e+02, 1.764607744527764e+02, -9.798418160199763e+01, 3.570857176090681e+01, -7.712306725921948e+00, 7.496307441868854e-01};
const double f_lpf02_b10_b[] {2.932632075123687e-17, 2.932632075123687e-16, 1.319684433805659e-15, 3.519158490148425e-15, 6.158527357759743e-15, 7.390232829311692e-15, 6.158527357759743e-15, 3.519158490148425e-15, 1.319684433805659e-15, 2.932632075123687e-16, 2.932632075123687e-17};

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

const double f_lpf49_8_b[] {-6.035564708478322e-03, -1.459747550010019e-03, 7.617213234063192e-02, 2.530939844348266e-01, 3.564583909660596e-01, 2.530939844348267e-01, 7.617213234063196e-02, -1.459747550010020e-03, -6.035564708478321e-03};

const double f_lpf45_8_b[] {-4.889502734137763e-03, 4.595036240066151e-03, 8.519412674978986e-02, 2.466567238634809e-01, 3.368872317616017e-01, 2.466567238634810e-01, 8.519412674978988e-02, 4.595036240066152e-03, -4.889502734137763e-03};

const double f_lpf13_8_b[] {1.511108761398408e-02, 4.481461214778652e-02, 1.207230841165654e-01, 2.014075783203990e-01, 2.358872756025299e-01, 2.014075783203991e-01, 1.207230841165654e-01, 4.481461214778654e-02, 1.511108761398408e-02};

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

typedef vector<complex<double>> cossin;

class FM_demod {
	protected:
		vector<LDE> f_q, f_i;
		LDE *f_pre, *f_post;
		vector<cossin> ldft;
	
		int linelen;

		int min_offset;

		vector<double> fb;
	public:
		FM_demod(int _linelen, vector<double> _fb, LDE *prefilt, LDE *filt, LDE *postfilt) {
			linelen = _linelen;

			fb = _fb;

			for (double f : fb) {
				cossin tmpdft;
				double fmult = f / CHZ; 

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

				//cerr << n << endl;
	
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

//			cerr << total / in.size() << endl;
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
	//	y.i = clamp(y.i, -0.5957, .5957);
	//	y.q = clamp(y.q, -0.5226, .5226);

		y.y -= (.4 / 1.4);
		y.y *= 1.4; 
		y.y = clamp(y.y, 0, 1.0);

		r = (y.y * 1.164) + (1.596 * y.i);
		g = (y.y * 1.164) - (0.813 * y.i) - (y.q * 0.391);
		b = (y.y * 1.164) + (y.q * 2.018);

		r = clamp(r, 0, 1.05);
		g = clamp(g, 0, 1.05);
		b = clamp(b, 0, 1.05);
		//cerr << 'y' << y.y << " i" << y.i << " q" << y.q << ' ';
		//cerr << 'r' << r << " g" << g << " b" << b << endl;
	};
};

class NTSColor {
	protected:
		LDE *f_i, *f_q, *f_burst;
		LDE *f_post;
		double fc, fci;
		double freq;

		int cfline;

		int counter, lastsync;
		bool insync;

		double phase, level;
		int phase_count;
		bool phased;

		double adjfreq;

		double poffset, pix_poffset;

		vector<double> line;
	
		list<double> prev;

		vector<YIQ> *buf;

		int igap;
	public:
		bool get_newphase(double &afreq, double &np) {
			if (phased) {
				afreq = adjfreq;
				np = phase;
				phased = false;
				return true;
			} else return false;
		}	

		void phillips_decode() {
			int i = 0;
			int oc = 0;
			int lastone = 220 - 55 - 00;

			unsigned long code = 0;

			for (double c: line) {
				if (c > 0.8) {
					oc++;
				} else {
					if (oc) {
						int firstone = (i - oc) - 167;	
						int bit = firstone / 57;

						int offset = firstone - (bit * 57);
						if ((offset > 10) && (offset < 50)) {
							code |= (1 << (23 - bit));
						}

//						cerr << cfline << ' ' << i << ' ' << firstone << ' ' << bit * 57 << ' ' << bit << ' ' << hex << code << dec << endl;
						lastone = i;
					}
					oc = 0;
				}
				i++;
			}
			cerr << "P " << cfline << ' ' << hex << code << dec << endl;
		}

		NTSColor(vector<YIQ> *_buf = NULL, LDE *_f_post = NULL, LDE *_f_postc = NULL, double _freq = 8.0) {
			counter = 0;
			phased = insync = false;

			cfline = -1;

			pix_poffset = poffset = 0;
			adjfreq = 1.0;

			lastsync = -1;

			level = phase = 0.0;

			freq = _freq;

			buf = _buf;

			igap = -1;

			f_i = new LDE(31, NULL, f28_1_3mhz_b);
			f_q = new LDE(31, NULL, f28_1_3mhz_b);
			
			f_burst = new LDE(4, f_lpburst_a, f_lpburst_b);
			
			f_post = _f_post ? new LDE(*_f_post) : NULL;
		}

		void feed(double in) {
			counter++;
			if (lastsync >= 0) lastsync++;

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
#ifndef NOSNAP
                                        for (int i = lastsync; i >= 0 && i < 1820; i++) {
                                               if (buf) buf->push_back(YIQ(0,0,0));
                                        }
#endif
					
					if (igap > 300 && igap < 1200) {
						cfline = 0;
					} else {
						if ((cfline >= 6) && cfline <= 8) phillips_decode();
						if (cfline >= 0) cfline++;
					}
					
					igap = lastsync;

					lastsync = 0;

					//cerr << "sync at " << counter - 24 << ' ' << igap << endl;
					insync = true;
					prev.clear();
					line.clear();
				}
					
				line.push_back(in);

				if ((igap > 1000) && lastsync == 210) {
					fc = f_q->val();
					fci = f_i->val();
					level = ctor(fc, fci);
					if ((level > .05) && (level < .15)) {
						double padj = atan2(fci, ctor(fc, fci));

						if (fc > 0) {
							if (igap > 1820) 
								padj = (M_PIl / 2.0) - padj; 
							else
								padj = -(M_PIl / 2.0) - padj; 
						}

						phase -= (padj * sqrt(2.0));
						phased = true;
						phase_count = counter;

						pix_poffset = phase / M_PIl * 4.0;
						poffset += (igap - 1820);	

//						adjfreq = 1820.0 / igap; // (igap + ((padj / M_PIl) * 4.0));
						adjfreq = 1820.0 / (1820 + (padj * 1.15 * (M_PIl / 2.0)));
					}

					cerr << (buf ? 'B' : 'A') << ' ' ;
					cerr << counter << " level " << level << " q " << fc << " i " << fci << " phase " << atan2(fci, ctor(fc, fci)) << " adjfreq " << adjfreq << ' ' << igap << ' ' << poffset - pix_poffset << endl ;
				} else {
					if (buf && lastsync == 210 && igap >= 0) cerr << "S " << counter << ' ' << igap << endl;
				}
			} else {
				for (double v: prev) {
					if (v > 0.2) count++;
				}
				if (count >= 16) {
					insync = false;
					prev.clear();
					fc = fci = 0;
				}
			}

                        double q = f_q->feed(in * cos(phase + (2.0 * M_PIl * ((double)(counter) / freq))));
			double i = f_i->feed(-in * sin(phase + (2.0 * M_PIl * ((double)(counter) / freq))));

#ifdef NOSNAP
			if (buf && (lastsync >= 0)) {
#else
			if (buf && (lastsync >= 0) && (lastsync < 1820)) {
#endif
				double y = in;

				if (prev.size() > 17) {
					list<double>::iterator cur = prev.begin();
	
					for (int i = 0; i < (prev.size() - 16); i++, cur++);	
					y = *cur;
				}

#ifndef BW
				double iadj = i * 2 * (cos(phase + (2.0 * M_PIl * (((double)(counter - 17) / freq)))));
				double qadj = q * 2 * (sin(phase + (2.0 * M_PIl * (((double)(counter - 17) / freq))))); 
				//cerr << "p " << lastsync << ' ' << ctor(i, q) << ' ' << (atan2(i, ctor(i,q)) / (M_PIl / 180.0)) + 180.0 << " iadj " << iadj << " qadj " << qadj << " y " << y;
				//cerr << "p " << atan2(i, q) << " iadj " << iadj << " qadj " << qadj << " y " << y;
				y += iadj + qadj;
				//cerr << " " << y << endl;

				if (f_post) y = f_post->feed(y);
				YIQ outc = YIQ(y, i * 2.0, q * 2.0);
#else
				YIQ outc = YIQ(y, 0,0);
#endif
				if (!lastsync) outc.y = 1.0;
				buf->push_back(outc);	
			}

	//		return YIQ();
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
	LDE f_lpf02(4, f_lpf048_b4_a, f_lpf048_b4_b);
	LDE f_butter6(6, f_butter6_a, f_butter6_b);
	LDE f_boost6(8, NULL, f_boost6_b);
	LDE f_boost8(8, NULL, f_boost8_b);
	LDE f_boost16(8, NULL, f_boost16_b);

	LDE f_lpf49(8, NULL, f_lpf49_8_b);
	LDE f_lpf45(8, NULL, f_lpf45_8_b);
	LDE f_lpf13(8, NULL, f_lpf13_8_b);

	vector<double> fb({7600000, 8100000, 8500000, 8900000, 9300000}); 

	FM_demod video(2048, fb, &f_boost8, &f_butter6, NULL);
	
	vector<YIQ> outbuf;	
//	NTSColor color, color2(&outbuf, &f_lpf45, &f_lpf13);
	NTSColor color, color2(&outbuf, NULL);
//	NTSColor color(&outbuf, &f_lpf45), color2;
	queue<double> delaybuf;

	int nextcount = 0, count = 0;
	double nextfreq = 1.0000, nextphase = 0.0;
	double cval = 0.0, cloc = 0.0;
		
	while ((rv == 2048) && ((dlen == -1) || (i < dlen))) {
		vector<double> dinbuf;

		for (int j = 0; j < 2048; j++) dinbuf.push_back(inbuf[j]); 

		vector<double> outline = video.process(dinbuf);

		vector<unsigned short> bout;

		for (int i = 0; i < outline.size(); i++) {
			double n = outline[i];

			n -= 7600000.0;
			n /= (9400000.0 - 7600000.0);
			if (n < 0) n = 0;
			if (n > (65535.0 / 62000.0)) n = (65535.0 / 62000.0);

			color.feed(n);

			count++;

			if (color.get_newphase(nextfreq, nextphase)) {
//				color2.set_phase(nextfreq, nextphase);
				//cerr << "F " << nextfreq << ' ' << nextphase << endl;
//				nextfreq = 1.0;
				nextcount = count;	
			}

			delaybuf.push(n);

			if (delaybuf.size() >= 1820) {
				double len = nextfreq;
				double newval = delaybuf.front();
				while (len > 0.0) {
					double avail = 1.0 - (cloc - floor(cloc));  
					if (avail > len) {
						cval += (len * newval); 
						cloc += len;
						len = 0.0;
					} else {
						cval += (avail * newval);
						//cerr << "V " << cloc << ' ' << newval << ' ' << cval << endl;
						color2.feed(cval);
						cval = 0;					
						cloc += avail;
						len -= avail;
					} 
				}
				delaybuf.pop();
			} 

/*
			delaybuf.push(n);
			if (delaybuf.size() >= 1820) {
				color2.feed(delaybuf.front());
				delaybuf.pop();
			}
*/
		}

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
//		cerr << i << ' ' << rv << endl;
	}
	return 0;
}

