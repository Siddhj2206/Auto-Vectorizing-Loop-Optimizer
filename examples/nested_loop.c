#include <stddef.h>
#include <stdio.h>

int main(void) {
    int left[4][8], right[4][8], output[4][8];
    for (size_t i = 0; i < 4; ++i) {
        for (size_t j = 0; j < 8; ++j) {
            left[i][j] = (int)(i + j);
            right[i][j] = (int)(2 * j);
        }
    }
    for (size_t i = 0; i < 4; ++i) {
        for (size_t j = 0; j < 8; ++j)
            output[i][j] = left[i][j] + right[i][j];
    }
    printf("output[3][7]=%d\n", output[3][7]);
    return 0;
}
