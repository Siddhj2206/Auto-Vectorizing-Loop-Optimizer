#include <stdio.h>

void copy_range(int n, int offset, int * restrict dst,
                const int * restrict src) {
    for (int i = 0; i < n; i++)
        dst[i + offset] = src[i + offset];
}

int main(void) {
    int src[12], dst[12];
    for (int i = 0; i < 12; i++)
        src[i] = i * 3;
    copy_range(8, 2, dst, src);
    printf("dst[9]=%d\n", dst[9]);
    return 0;
}
