#include <unistd.h>
#include <sys/fcntl.h>
#include <stdio.h>
#include <iostream>
#include <fstream>
#include <sstream>
#include <string>
#include <cstdlib>

using namespace std;

#define MAX 8000000

double data[MAX];
unsigned char odata[MAX];

int main(int argc, char *argv[])
{
	int rv;

	if (argc < 2) return -1;

	fstream f(argv[1]);

	double low = 0, high = 0;
	int i = 0;

	while (f && (i < MAX)) {
		string buf;

		if (!getline(f, buf, ',')) break;
		if (!getline(f, buf, ',')) break;
//		cout << 'l' << endl;
//		cout << ::strtod(buf.c_str(), 0) << endl;

		data[i] = ::strtod(buf.c_str(), 0);
		if (data[i] > high) high = data[i];
		if (data[i] < low) low = data[i];

		i++;
	};

	cout << low << ' ' << high << endl;

	for (int j = 0; j < i; j++) {
		double out;

		out = (data[j] - low) / (high - low);
		out *= 255.0;
		out += 0.49;

		odata[j] = out;
	}

	write (1, odata, i);

	return 0; 

}

