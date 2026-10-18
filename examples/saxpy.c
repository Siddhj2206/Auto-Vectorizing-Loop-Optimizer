#include <stdio.h>

void saxpy(int n, float alpha, float * restrict y,
           const float * restrict x) {
    for (int i = 0; i < n; ++i)
        y[i] = alpha * x[i] + y[i];
}

int main(void) {
    float x[100], y[100];
    for (int i = 0; i < 100; ++i) { x[i] = (float)i; y[i] = 1.0f; }
    saxpy(100, 2.0f, y, x);
    printf("y[99]=%.1f\n", y[99]);
    return 0;
}
