#include <stdio.h>

int main(void) {
    int values[101] = {0};
    for (int i = 1; i < 101; ++i)
        values[i] = values[i - 1] + 1;
    printf("values[100]=%d\n", values[100]);
    return 0;
}
