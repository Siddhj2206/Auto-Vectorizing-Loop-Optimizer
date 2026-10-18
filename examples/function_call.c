#include <stdio.h>

static int calls;
static int effect(int value) {
    ++calls;
    return value;
}

int main(void) {
    int a[8] = {0}, b[8] = {0}, c[8] = {0};
    for (int i = 0; i < 8; ++i)
        c[i] = a[i] + effect(b[i]);
    printf("c[7]=%d calls=%d\n", c[7], calls);
    return 0;
}
