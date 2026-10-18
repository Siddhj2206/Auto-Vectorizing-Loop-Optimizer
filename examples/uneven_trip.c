#include <stdio.h>

int main(void) {
    int a[101], b[101], c[101];
    for (int i = 0; i < 101; ++i) { a[i] = i; b[i] = 2 * i; }
    for (int i = 0; i < 101; ++i)
        c[i] = a[i] + b[i];
    printf("c[100]=%d\n", c[100]);
    return 0;
}
