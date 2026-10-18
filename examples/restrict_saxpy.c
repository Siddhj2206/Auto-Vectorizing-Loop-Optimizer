#include <stdio.h>

void saxpy(int n, float * restrict y, const float * restrict x, float alpha) {
    for (int i = 0; i < n; i++)
        y[i] = alpha * x[i] + y[i];
}

int main(void) {
    float x[8], y[8];
    for (int i = 0; i < 8; i++) {
        x[i] = (float)i;
        y[i] = 1.0f;
    }
    saxpy(8, y, x, 2.0f);
    printf("y[7]=%.1f\n", y[7]);
    return 0;
}
