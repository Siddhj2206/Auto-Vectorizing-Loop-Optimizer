"""Auto-Vectorizing Loop Optimizer (``avlo``).

A small, self-contained IR-to-IR auto-vectorizing loop optimizer that
demonstrates the core vectorization pipeline on a simplified toy IR:

    parse -> scope check -> dependence analysis -> legality check -> strip-mine

Only single-basic-block counted loops over one-dimensional arrays with
affine, unit-stride accesses are supported. Real SIMD instructions are
not generated; the transformer emits VLOAD / VADD / VSTORE-style
pseudo-operations.
"""

__version__ = "0.1.0"
