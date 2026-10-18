#include <stdio.h>

int main(void) {
    signed char small[8];
    unsigned char offset[8];
    double output[8];
    for (long long i = 0; i < 8; ++i) {
        small[i] = (signed char)i;
        offset[i] = (unsigned char)(10 + i);
    }
    for (long long i = 0; i < 8; ++i)
        output[i] = (double)small[i] + (double)offset[i] * 0.5;
    printf("output[7]=%.1f\n", output[7]);
    return 0;
}
