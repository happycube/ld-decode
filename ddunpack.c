#include <stdio.h>
#include <unistd.h>
#include <stdint.h>

// in number of samples - must be divisible by 3
#define BUFSIZE 32768 
	
uint32_t inbuf[BUFSIZE];
int16_t outbuf[BUFSIZE * 3];

int16_t extend(uint32_t sample) 
{
	uint16_t out = (uint16_t)(sample & 0x3ff);

	out = out << 6;

	// add the last 6 bits if signed
	//if (out & 0x8000) out |= 0x3f;
	return (int16_t)out;
}

int main(void)
{
	size_t rv = 0;
	int i, o = 0;

	while ((rv = read(0, inbuf, sizeof(inbuf))) > 0) {
		o = 0;
		for (i = 0; i < (rv / sizeof(uint32_t)); i++) {
			outbuf[o++] = extend(inbuf[i]);
			outbuf[o++] = extend(inbuf[i] >> 10);
			outbuf[o++] = extend(inbuf[i] >> 20);
		}
		rv = write(1, outbuf, o * sizeof(int16_t));
	}
}

