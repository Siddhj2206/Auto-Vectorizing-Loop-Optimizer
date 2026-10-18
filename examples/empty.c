#include <stdio.h>

int main(void) {
    int a[1] = {1}, b[1] = {2}, c[1] = {0};
    for (int i = 0; i < 0; ++i)
        c[i] = a[i] + b[i];
    printf("c[0]=%d\n", c[0]);
    return 0;
}
