#include <stdio.h>

void add_range(int lo, int hi, int * restrict out,
               const int * restrict a, const int * restrict b) {
    for (int i = lo; i < hi; ++i)
        out[i] = a[i] + b[i];
}

int main(void) {
    int a[8], b[8], out[8];
    for (int i = 0; i < 8; i++) {
        a[i] = i;
        b[i] = 10;
    }
    add_range(0, 8, out, a, b);
    printf("out[7]=%d\n", out[7]);
    return 0;
}
