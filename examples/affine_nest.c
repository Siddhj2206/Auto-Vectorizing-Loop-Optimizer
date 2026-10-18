#include <stdio.h>

int main(void) {
    int input[32], output[32];
    for (int i = 0; i < 32; ++i)
        input[i] = i * 3;
    for (int i = 0; i < 4; ++i) {
        for (int j = 1; j < 8; ++j)
            output[8 * i + j] = input[8 * i + j - 1];
    }
    printf("output[31]=%d\n", output[31]);
    return 0;
}
