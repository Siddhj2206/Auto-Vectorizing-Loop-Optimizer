#include <stdio.h>

int main(void) {
    int values[3][8] = {{0}};
    for (int i = 0; i < 3; ++i) {
        for (int j = 1; j < 8; ++j)
            values[i][j] = values[i][j - 1] + 1;
    }
    printf("values[2][7]=%d\n", values[2][7]);
    return 0;
}
