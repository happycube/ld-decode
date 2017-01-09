/* LD decoder prototype, Copyright (C) 2013 Chad Page.  License: LGPL2 */

#include "ld-decoder.h"

const double CHZ = (1000000.0*(315.0/88.0)*8.0);

#include "deemp.h"

vector<double> c_deemp_b = {9.075768293948128e-03, -8.237285180536874e-03, 1.525400109890641e-01, 1.271261981795985e-02, -1.772601911252877e-03, -5.061921080347066e-03, -5.526588869733499e-03, -5.112432800144701e-03, -4.491518795193911e-03, };
vector <double> c_deemp_a = {1.000000000000000e+00, -2.739289771643778e-01, -1.628794813742291e-01, -1.018574697801082e-01, -6.551811195197693e-02, -4.321668274634510e-02, -2.921443695973032e-02, -1.747512379029513e-02, -1.518230676503862e-02, };

Filter f_deemp(c_deemp_b, c_deemp_a);

vector<double> c_deemp10_b = {5.033030306263742e-02, 1.326615246049396e-01, -4.699753787161509e-02, -5.387607463636233e-03, 3.034857259022750e-03, 4.993124726086266e-03, 5.003608995847797e-03, 4.444995350933708e-03, 3.754281167962590e-03, };
vector <double> c_deemp10_a = {1.000000000000000e+00, -2.556876643286093e-01, -1.528934687661787e-01, -8.597146102900972e-02, -4.577471369551848e-02, -2.260746572729532e-02, -9.521446563288450e-03, -1.552858509482608e-03, -7.850714120476686e-04, };

Filter f_deemp10(c_deemp10_b, c_deemp10_a);


bool fast = false;
bool fscten = false;	// 10x fsc - todo

class FM_demod {
	protected:
		Filter *f_pre;
		Filter *f_post;

		int linelen;

		int min_offset;

		double deemp;

		vector<double> fb;
	public:
		FM_demod(int _linelen, Filter *prefilt, Filter *postfilt) {
			int i = 0;
			linelen = _linelen;

			deemp = 0;

			f_pre = prefilt;
			f_post = postfilt ? new Filter(*postfilt) : NULL;

			min_offset = 128;
		}

		~FM_demod() {
//			if (f_pre) free(f_pre);
			if (f_post) free(f_post);
		}

		vector<double> process(vector<double> in) 
		{
			vector<double> out;
			vector<double> phase(fb.size() + 1);
			vector<double> level(fb.size() + 1);
			
			if (in.size() < (size_t)linelen) return out;

			double prev_ang = 0;

			int i = 0;
			for (double n : in) {
				double v = 0;	

				n = f_pre->feed(n);

				double real = f_hilbertr.feed(n);
				double imag = f_hilberti.feed(n);

				double ang;
	
				if (fast)
					ang = fast_atan2(real, imag); 
				else 
					ang = atan2(real, imag);
		
				if (!i) prev_ang = ang;

				double diff = WrapAngle(prev_ang - ang);

				v = diff * 4557618;
				if (f_post) v = f_post->feed(v);	

			//	cerr << ang << ' ' << diff << ' ' << diff * 4557618 << ' ' << v << endl;

				prev_ang = ang;

				if (i > 1024) out.push_back(v);

				i++;
			}

			return out;
		}
};

int main(int argc, char *argv[])
{
	int rv = 0, fd = 0;
	long long dlen = -1;
	//double output[2048];
	unsigned char inbuf[2048];
	char c;

	cerr << std::setprecision(10);
	cerr << argc << endl;
	cerr << strncmp(argv[1], "-", 1) << endl;
	
	opterr = 0;
	while ((c = getopt (argc, argv, "ft")) != -1) {
		switch (c) {
			case 'f':
				fast = true;
				break;
			case 't':
				fscten = true;
				break;
			default:
				cerr << "unknown option " << c << endl;
				break;
		}
	} 

	int optsleft = argc - optind;

	if (optsleft >= 1 && (strncmp(argv[optind], "-", 1))) {
		fd = open(argv[optind], O_RDONLY);
	}

	if (optsleft >= 2) {
		unsigned long long offset = atoll(argv[optind + 1]);

		if (offset) lseek64(fd, offset, SEEK_SET);
	}
		
	if (optsleft >= 3) {
		if ((size_t)atoll(argv[optind + 2]) < dlen) {
			dlen = atoll(argv[optind + 2]); 
		}
	}

	cout << std::setprecision(8);
	
	rv = read(fd, inbuf, 2048);

	int i = 2048;
	
	FM_demod video(2048, &f_boost, &f_lpf);

	double minire = -60;
	double maxire = 140;
	double hz_ire_scale = (9300000 - 8100000) / 100;

	double min = 8100000 + (hz_ire_scale * -60);

	double out_scale = 65534.0 / (maxire - minire);

	cerr << "ire scale " << out_scale << endl;

	while ((rv == 2048) && ((dlen == -1) || (i < dlen))) {
		vector<double> dinbuf;
		vector<unsigned short> ioutbuf;

		for (int j = 0; j < 2048; j++) dinbuf.push_back(inbuf[j]); 

		vector<double> outline = video.process(dinbuf);

		vector<unsigned short> bout;

		for (int i = 0; i < outline.size(); i++) {
			double n = outline[i];
			int in;

			if (n > 0) {
//				cerr << "d " << n << ' ';
				n = f_deemp.feed(n) / .4960;
//				cerr << " " << n << endl;

				n -= min;
				n /= hz_ire_scale;
				if (n < 0) n = 0;
				in = 1 + (n * out_scale);
				if (in > 65535) in = 65535;
//				cerr << in << endl;
			} else {
				in = 0;
			}

			bout.push_back(in);
		}
		
		unsigned short *boutput = bout.data();
		int len = outline.size();
		if (write(1, boutput, bout.size() * 2) != bout.size() * 2) {
			//cerr << "write error\n";
			exit(0);
		}

		i += (len > 1820) ? 1820 : len;
		memmove(inbuf, &inbuf[len], 2048 - len);
		rv = read(fd, &inbuf[(2048 - len)], len) + (2048 - len);
		
		if (rv < 2048) return 0;
		//cerr << i << ' ' << rv << endl;
	}
	return 0;
}

