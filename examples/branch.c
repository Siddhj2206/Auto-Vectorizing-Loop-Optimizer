#include <stdio.h>

int main(void) {
    int a[16], b[16], c[16];
    for (int i = 0; i < 16; i++) {
        a[i] = i;
        b[i] = 100 + i;
    }
    for (int i = 0; i < 16; i++) {
        if (a[i] % 2 == 0)
            c[i] = a[i];
        else
            c[i] = b[i];
    }
    printf("c[15]=%d\n", c[15]);
    return 0;
}
