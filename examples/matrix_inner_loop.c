#include <stdio.h>

int main(void) {
    int a[4][8], b[4][8], c[4][8];
    for (int i = 0; i < 4; i++) {
        for (int j = 0; j < 8; j++) {
            a[i][j] = i + j;
            b[i][j] = 2 * j;
        }
    }
    for (int i = 0; i < 4; i++) {
        for (int j = 0; j < 8; j++)
            c[i][j] = a[i][j] + b[i][j];
    }
    printf("c[3][7]=%d\n", c[3][7]);
    return 0;
}
