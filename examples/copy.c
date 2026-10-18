#include <stdio.h>

void copy_array(int n, int * restrict dst, const int * restrict src) {
    for (int i = 0; i < n; ++i)
        dst[i] = src[i];
}

int main(void) {
    int src[100], dst[100];
    for (int i = 0; i < 100; ++i) src[i] = i * 3;
    copy_array(100, dst, src);
    printf("dst[99]=%d\n", dst[99]);
    return 0;
}
