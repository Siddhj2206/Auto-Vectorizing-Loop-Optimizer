#include <stdio.h>

static inline int square(int value) {
    return value * value;
}

int main(void) {
    int input[8], output[8];
    for (int i = 0; i < 8; i++)
        input[i] = i;
    for (int i = 0; i < 8; i++)
        output[i] = square(input[i]);
    printf("output[7]=%d\n", output[7]);
    return 0;
}
