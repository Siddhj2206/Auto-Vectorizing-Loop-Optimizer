#include <stdio.h>

int main(void) {
    int input[16], output[16];
    for (int i = 0; i < 16; i++)
        input[i] = i;
    for (int i = 0; i < 16; i += 2)
        output[i] = input[i] + 1;
    for (int i = 15; i >= 1; i -= 2)
        output[i] = input[i] + 2;
    printf("output[14]=%d output[15]=%d\n", output[14], output[15]);
    return 0;
}
