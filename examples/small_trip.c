#include <stdio.h>

int main(void) {
    int a[3] = {1, 2, 3}, b[3] = {10, 20, 30}, c[3] = {0};
    for (int i = 0; i < 3; ++i)
        c[i] = a[i] + b[i];
    printf("c[2]=%d\n", c[2]);
    return 0;
}
