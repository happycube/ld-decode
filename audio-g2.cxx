/* LD decoder prototype, Copyright (C) 2013 Chad Page.  License: LGPL2 */

#include "ld-decoder.h"
#include "deemp.h"

// From http://lists.apple.com/archives/perfoptimization-dev/2005/Jan/msg00051.html. 
const double PI_FLOAT = M_PIl;
const double PIBY2_FLOAT = (M_PIl/2.0); 
// |error| < 0.005
double fast_atan2( double y, double x )
{
	if ( x == 0.0f )
	{
		if ( y > 0.0f ) return PIBY2_FLOAT;
		if ( y == 0.0f ) return 0.0f;
		return -PIBY2_FLOAT;
	}
	double atan;
	double z = y/x;
	if (  fabs( z ) < 1.0f  )
	{
		atan = z/(1.0f + 0.28f*z*z);
		if ( x < 0.0f )
		{
			if ( y < 0.0f ) return atan - PI_FLOAT;
			return atan + PI_FLOAT;
		}
	}
	else
	{
		atan = PIBY2_FLOAT - z/(z*z + 0.28f);
		if ( y < 0.0f ) return atan - PI_FLOAT;
	}
	return atan;
}

inline double WrapAngle(double a1, double a2) {
        double v = a2 - a1;

        if (v > M_PIl) v -= (2 * M_PIl);
        else if (v <= -M_PIl) v += (2 * M_PIl);

        return v;
}

class FM_demod_audio {
	protected:
		Filter *f_pre;
		Filter *f_post;

		int linelen;

		int min_offset;

		double deemp;

		vector<double> fb;
	public:
		FM_demod_audio(int _linelen, Filter *prefilt, Filter *postfilt) {
			linelen = _linelen;

			deemp = 0;

			f_pre = prefilt;
			f_post = postfilt ? new Filter(*postfilt) : NULL;

			min_offset = 128;
		}

		~FM_demod_audio() {
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

			int i = 0, t = 0;
			for (double n : in) {
				double v = 0;	

				n = f_pre->feed(n);
				t++;

				double real = f_hilbertr.feed(n);
				double imag = f_hilberti.feed(n);

				double ang = atan2(real, imag);
		
				if (!i) prev_ang = ang;

				double diff = WrapAngle(ang, prev_ang);

				v = diff * (4557618 / 4);
				if (f_post) v = f_post->feed(v);	

				//cerr << ang << ' ' << diff << ' ' << diff * (4557618 / 4)<< ' ' << v << endl;

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
	//double output[262144];
	unsigned char inbuf[256*1024];

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
		if ((size_t)atoll(argv[3]) < dlen) {
			dlen = atoll(argv[3]); 
		}
	}

	cout << std::setprecision(8);
	
	rv = read(fd, inbuf, 256*1024);

	FM_demod_audio left(64*1024, &f_leftbp, &f_audiolp);
	FM_demod_audio right(64*1024, &f_rightbp, &f_audiolp);

	int tot = 0;
	int i = 0;

	while ((rv == 262144) && ((dlen == -1) || (i < dlen))) {
		vector<double> dinbuf;
		vector<unsigned short> ioutbuf;

		for (int j = 0; j < 262144; j++) {
			double filt = f_audioin.feed(inbuf[j]);
			if (!(j % 4)) dinbuf.push_back(filt); 
		}

		vector<double> outleft = left.process(dinbuf);
		vector<double> outright = right.process(dinbuf);

		vector<float> out;

		for (int i = 0; i < outleft.size(); i++) {
			tot++;

			if (!(tot % 20)) {
				out.push_back((float)outleft[i]);
				out.push_back((float)outright[i]);
			}
		}

//		cerr << out.size() << ' ' << out.size() / 2 * 80 << endl;
		
		float *output = out.data();
		if (write(1, output, out.size() * 4) != out.size() * 4) {
			//cerr << "write error\n";
			exit(0);
		}
		
		int len = outleft.size() * 4;

		i += len;
		memmove(inbuf, &inbuf[len], 262144 - len);
		rv = read(fd, &inbuf[(262144 - len)], len) + (262144 - len);
		
		if (rv < 262144) return 0;
	}

	return 0;
}

