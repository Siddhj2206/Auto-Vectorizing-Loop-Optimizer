#include <stdio.h>

int main(void) {
    int a[16], b[16], c[16];
    for (int i = 0; i < 8; i++) {
        a[2 * i] = i;
        b[2 * i] = 3 * i;
    }
    for (int i = 0; i < 8; i++)
        c[2 * i] = a[2 * i] + b[2 * i];
    printf("c[14]=%d\n", c[14]);
    return 0;
}
