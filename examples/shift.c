#include <stdio.h>

int main(void) {
    int values[101];
    for (int i = 0; i < 101; ++i) values[i] = i;
    for (int i = 0; i < 100; ++i)
        values[i + 1] = values[i] * 2;
    printf("values[100]=%d\n", values[100]);
    return 0;
}
