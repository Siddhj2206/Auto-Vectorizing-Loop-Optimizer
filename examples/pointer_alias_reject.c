/* AVLO keeps this loop scalar because the three pointer parameters may alias. */
void add_without_alias_contract(int n, int *out, const int *a, const int *b) {
    for (int i = 0; i < n; i++)
        out[i] = a[i] + b[i];
}
