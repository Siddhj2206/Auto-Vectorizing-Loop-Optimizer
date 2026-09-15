# Auto-Vectorizing Loop Optimizer

A small, self-contained **IR-to-IR auto-vectorizing loop optimizer** for
Compiler Design (BCSE307). It demonstrates the core vectorization pipeline on
a simplified *toy IR* instead of full LLVM IR, so that each stage can be read,
run and tested on its own.

Given a counted loop written in a tiny text format, the tool:

1. parses it into a toy-IR loop object,
2. checks it is inside the supported shape,
3. decides whether its array accesses contain a **loop-carried dependence**
   using a simplified GCD / Banerjee-style offset comparison,
4. checks a set of **legality preconditions**,
5. if both checks pass, **strip-mines** the loop into a vector main loop plus a
   scalar remainder loop (emitted as `VLOAD` / `VADD` / `VSTORE`-style
   pseudo-operations); otherwise the loop is left in scalar form.

No real SIMD instructions are generated or executed — the output is toy IR.

## Quick start

```bash
# install (uv manages the virtualenv and dev tools)
uv sync

# run the tool on an example loop
uv run avlo examples/saxpy.loop

# machine-readable output
uv run avlo --json examples/recurrence.loop

# execute the scalar and vectorized forms and check they agree
uv run avlo --verify examples/saxpy.loop

# run the test suite
uv run pytest
```

`uv run python -m avlo examples/copy.loop` works too.

## The toy IR text format

```text
# comments start with '#'
vector_width 4                # optional; defaults to 4

loop i = 0 to 100             # iterations are start .. end-1 (trip count = 100)
    y[i] = alpha * x[i] + y[i]
end
```

* Array indices are **affine** in the induction variable: `i`, `i-1`, `i+1`,
  `2*i+1`.
* Statements are assignments to array elements. The right-hand side may use
  `+ - * /`, array reads, integer literals and loop-invariant scalars.
* A function call in the body (`foo(b[i])`) is representable but is rejected by
  the legality checker as out of scope.
* One loop per file, single basic block, one induction variable.

The example files in [`examples/`](examples) map one-to-one onto the test plan.

## Pipeline and modules

| Stage | Module | Responsibility |
|---|---|---|
| 1. IR model | `src/avlo/ir.py` | Loop / statement / access / index data model and rendering |
| 2. Parse | `src/avlo/parser.py` | Text IR → `Loop`; affine index reduction |
| 3. Scope check | `src/avlo/scope.py` | Single-basic-block counted loop, known non-negative trip count |
| 4. Dependence | `src/avlo/dependence.py` | GCD / Banerjee-style offset comparison, RAW/WAR/WAW, distances |
| 5. Legality | `src/avlo/legality.py` | Affine + unit-stride accesses, supported ops, no unsupported constructs |
| 6. Transform | `src/avlo/transform.py` | Strip-mining, vector body lowering, remainder loop |
| Driver | `src/avlo/pipeline.py` | Wires the stages together and produces a `Report` |
| Execute / verify | `src/avlo/executor.py` | Runs the scalar loop and the vectorized output on identical inputs and compares |
| Output | `src/avlo/report.py` | Text and JSON rendering |
| CLI | `src/avlo/cli.py` | `avlo <file.loop>` |

### Dependence test in one paragraph

For two accesses to the same array, the index expressions are reduced to
`c1*i + c0` and `c1'*j + c0'`. If `c1 == c1'` the equal-index equation gives an
exact dependence distance `d = (c0' - c0) / c1`; the pair is loop-carried when
`0 < |d| < trip`. If the coefficients differ, the **GCD test** is used as a
necessary condition: when `gcd(c1, c1')` does not divide `c0' - c0` the accesses
are provably independent, otherwise the simplified test cannot prove
independence and the pair is treated conservatively as possibly dependent.
Read-read pairs are skipped and distinct arrays are assumed not to alias.

## Test plan

| ID | Category | Input | Expected |
|---|---|---|---|
| T-01 | Positive | `c[i] = a[i] + b[i]` | VECTORIZED |
| T-02 | Positive | `c[i] = a[i] - b[i]` | VECTORIZED |
| T-03 | Positive | `c[i] = a[i] * b[i]` | VECTORIZED |
| T-04 | Positive | `b[i] = a[i]` | VECTORIZED |
| T-05 | Positive | `y[i] = alpha*x[i] + y[i]` | VECTORIZED |
| T-06 | Negative | `a[i] = a[i-1] + 1` | REJECTED (loop-carried RAW, distance −1) |
| T-07 | Negative | `a[i+1] = a[i] * 2` | REJECTED (cross-offset dependence) |
| T-08 | Negative | body containing `foo(...)` | REJECTED (function call out of scope) |
| T-09 | Boundary | trip count < vector width | remainder loop only |
| T-10 | Boundary | trip count not divisible by width | vector loop + non-empty remainder |
| T-11 | Boundary | trip count = 0 | no-op, no crash |

These are encoded as executable assertions in
[`tests/test_taxonomy.py`](tests/test_taxonomy.py); unit tests for the parser,
affine reduction, dependence distances and lowering live in
[`tests/test_units.py`](tests/test_units.py).

**Correctness.** `executor.py` interprets both the original scalar loop and the
emitted vector program (`VLOAD` reads `V` consecutive elements, `VBCAST`
broadcasts a scalar, arithmetic runs element-wise, `VSTORE` writes `V`
consecutive elements) over identical, deterministically generated arrays and
compares the results. [`tests/test_executor.py`](tests/test_executor.py)
asserts equality for every positive case, across vector widths 1–8 and for
trip counts that are smaller than, equal to, and larger than the width — so
strip-mining failures surface as failing tests, not silent wrong output.

## Scope and limitations

In scope: single-basic-block counted loops, one-dimensional arrays, affine
**unit-stride** accesses, element-wise arithmetic, SAXPY-style operations,
configurable vector width, scalar remainder loop.

Out of scope (as frozen at Review 1): general alias analysis, multi-dimensional
arrays, reductions, function calls, exceptions, data-dependent control flow,
real SIMD code generation and hardware execution.

Known simplifications:

* only unit-stride accesses are vectorized; a strided access such as `a[2*i]`
  is reported and rejected rather than lowered;
* when coefficients differ the dependence test is conservative (it may report a
  dependence that a general solver would disprove);
* `vector_width` is a scalar knob, not a target cost model.

## Module ownership (responsibility assignment)

| Member | Owns | Files |
|---|---|---|
| Member 2 (front-end) | IR model, parser, scope check | `ir.py`, `parser.py`, `scope.py` |
| Member 3 (algorithm) | Dependence analysis, legality | `dependence.py`, `legality.py` |
| Member 1 (integration) | Transformer, pipeline driver | `transform.py`, `pipeline.py` |
| Member 4 (testing/interface) | Test suite, executor, CLI, README | `tests/`, `executor.py`, `cli.py`, `README.md` |

Ownership is a responsibility assignment; contribution evidence is each
member's own commits against their files.

## Requirements

* Python ≥ 3.11 (developed on 3.14)
* [`uv`](https://docs.astral.sh/uv/) for environment management
* `pytest` (dev dependency, installed by `uv sync`)

No third-party runtime dependencies.
