#pragma avlo width(4)
#include <stdio.h>

int main(void) {
    const int n = 16;
    int a[16], b[16], c[16];
    for (int i = 0; i < n; i++) {
        a[i] = i;
        b[i] = 2 * i;
    }
    for (int i = 0; i < n; i++) {
        c[i] = a[i] + b[i];
    }
    printf("c[15]=%d\n", c[15]);
    return 0;
}
