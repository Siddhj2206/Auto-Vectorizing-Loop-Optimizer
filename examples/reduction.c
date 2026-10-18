#include <stdio.h>

int main(void) {
    const int n = 16;
    int values[16];
    for (int i = 0; i < n; i++)
        values[i] = i + 1;

    int sum = 0;
    for (int i = 0; i < n; i++)
        sum += values[i];

    printf("sum=%d\n", sum);
    return 0;
}
