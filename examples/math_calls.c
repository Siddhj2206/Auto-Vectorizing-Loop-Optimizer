#include <math.h>
#include <stdio.h>

int main(void) {
    float input[8], output[8];
    for (int i = 0; i < 8; i++)
        input[i] = (float)(i * i);
    for (int i = 0; i < 8; i++)
        output[i] = sqrtf(input[i]);
    printf("output[7]=%.1f\n", output[7]);
    return 0;
}
