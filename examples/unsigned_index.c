#include <stddef.h>
#include <stdio.h>

void add(size_t n, int * restrict out,
         const int * restrict a, const int * restrict b) {
    for (size_t i = 0; i < n; ++i)
        out[i] = a[i] + b[i];
}

int main(void) {
    int a[8] = {0, 1, 2, 3, 4, 5, 6, 7};
    int b[8] = {10, 10, 10, 10, 10, 10, 10, 10};
    int out[8];
    add(8, out, a, b);
    printf("out[7]=%d\n", out[7]);
    return 0;
}
