#include <stdio.h>

int main(void) {
    int flag[8], value[8], output[8];
    for (int i = 0; i < 8; ++i) {
        flag[i] = i % 2;
        value[i] = i - 3;
    }
    for (int i = 0; i < 8; ++i) {
        if (flag[i]) {
            if (value[i] > 0)
                output[i] = value[i] * 2;
            else
                output[i] = -value[i];
        } else {
            output[i] = value[i] + 10;
        }
    }
    printf("output[7]=%d output[4]=%d\n", output[7], output[4]);
    return 0;
}
