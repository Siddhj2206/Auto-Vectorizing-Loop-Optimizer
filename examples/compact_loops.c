#include <stdio.h>
#define COUNT 8
int main(void) { int a[COUNT], b[COUNT]; for (int i = 0; i < COUNT; ++i) a[i] = i; for (int j = 0; j < COUNT; ++j) b[j] = a[j] + 1; printf("b[7]=%d\n", b[7]); return 0; }
