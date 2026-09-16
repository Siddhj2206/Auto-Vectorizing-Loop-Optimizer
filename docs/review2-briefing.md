# Review 2 Briefing — Auto-Vectorizing Loop Optimizer

**Course:** BCSE307 Compiler Design · **Team:** A9
**Members:** Kaviya Shree S (24BCE2348) · Ayush Garg (24BCE0275) · Siddhant Jain (24BCI0190) · Gnana Sasidhar (24BCE0926)
**Review date:** 16 September 2026

---

## 1. The project in one paragraph

**Auto-Vectorizing Loop Optimizer** takes a counted loop written in a tiny custom IR
(a "toy IR"), decides whether the loop can safely become SIMD code, and if so rewrites
it into a vector main loop plus a scalar remainder loop. It is an **IR-to-IR** tool: it
never emits or runs real machine SIMD. It exists to demonstrate the *decision* that
production vectorizers make — dependency analysis, legality checking, and transformation
— as small, inspectable, independently testable stages, instead of hidden inside
LLVM/GCC.

## 2. The problem and the correctness condition

Real compilers auto-vectorize a loop only when they can **prove** it is safe. The safety
question is: do two iterations ever touch the same memory in a way that forces them to
run in order? If they do, the loop has a *loop-carried dependence* and vectorizing it
would compute wrong answers.

Correctness condition, from the Review 1 design: **for every input that satisfies the
stated preconditions, the vectorized output must compute exactly the same array values
as the original scalar loop.** We do not merely claim this — `executor.py` runs both and
compares.

## 3. The 100% scope (Review 3 target)

The full deliverable, frozen at Review 1:

| # | Item | Status |
|---|---|---|
| 1 | Toy IR data model | built |
| 2 | Text-IR parser + affine index reduction | built |
| 3 | Scope check / loop identification | built |
| 4 | GCD / Banerjee-style dependence analyzer | built |
| 5 | Legality checker | built |
| 6 | Strip-mining transformer (vector + remainder) | built |
| 7 | Interpreter + equivalence checking | built |
| 8 | Known-answer test suite | built |
| 9 | CLI + runnable examples + documentation | built |
| 10 | Static op-count "performance" comparison | Review 3 |
| 11 | Visualisation / step trace | Review 3 |
| 12 | Wider invalid and boundary test set | Review 3 |
| 13 | Formal progress document and slides | Review 3 |

## 4. What the "60%" means

For Review 2 we agreed to deliver roughly **60% of the full thing** — specifically a
**depth cut, not a breadth cut**: every pipeline stage is implemented at real, demoable
depth, and the final-polish layer is deferred to Review 3.

Because the interpreter (item 7, the optional stretch) landed, the project is actually
at **~9 of 13 ≈ 70%**. Only items 10–13 remain.

The 60% was chosen to hit the components Review 2 actually grades: **core module
implementation (2.5), integration (1.5) and testing/correctness (1.5)** — 5.5 of the
10 marks — which is exactly what items 1–9 buy.

## 5. What is out of scope, and why

| Out of scope | Why |
|---|---|
| Multi-dimensional arrays and loops | Would need a real polyhedral model, not an offset comparison |
| Reductions (`sum += a[i]`) | Not vectorizable without hardware intrinsics / horizontal ops |
| Function calls, exceptions, `if/else` in the body | Cannot reason about their effect on memory |
| General pointer / array alias analysis | Distinct array names are *assumed* not to alias (stated assumption) |
| Real SIMD codegen, hardware execution, measured speedup | We emit pseudo-ops; no speedup number is claimed |
| **Strided** accesses (`a[2*i]`) | Rejected on purpose — `VLOAD` means "V contiguous elements", so a stride-2 load would compute wrong values |
| **Non-affine** indices (`a[i*i]`) | Not expressible as `coeff*i + offset` |

Everything out of scope is **rejected with a reason**, never silently mishandled.

## 6. Repository layout

```
pyproject.toml            uv project; pytest config; no runtime dependencies
uv.lock
README.md                 living document: architecture, tests, defect log, matrix
examples/*.loop           11 example inputs, one per test case
src/avlo/
  ir.py          data model: Index, expressions, Statement, Loop, VectorOp, Operand
  parser.py      tokenizer + recursive-descent parser + affine reduction (to_affine)
  scope.py       stage 2 - scope check
  dependence.py  stage 3 - loop-carried dependence analysis
  legality.py    stage 4 - preconditions
  transform.py   stage 5 - strip-mining and lowering to pseudo-ops
  executor.py    interpreter + equivalence checker
  pipeline.py    driver: wires the stages, returns a Report
  report.py      text and JSON rendering
  cli.py         `avlo <file.loop> [--json] [--verify]`
  __main__.py    `python -m avlo`
tests/
  test_taxonomy.py    T-01 .. T-11 known-answer suite
  test_ir_parser.py   parser / affine unit tests
  test_dependence.py  distance and GCD tests
  test_transform.py   strip-mine partition tests
  test_executor.py    equivalence tests
  test_cli.py         CLI tests
```

**Git:** `master` holds the bootstrap; four module branches
(`feat/frontend`, `feat/analysis`, `feat/transform`, `feat/verify`) merge into it one by
one; `testing` is the integrated reference snapshot. **34 tests, all green.**

## 7. How it works, stage by stage

The pipeline is a straight line with **three rejection points**:

```
file --> Parser --> Scope --x--> scalar
                    --> Dependence --x--> scalar
                          --> Legality --x--> scalar
                                --> Transform --> vector IR --> Executor --> PASS / FAIL
```

**Stage 1 — Parser** (`parser.py`). Tokenizes with a single regex, then recursive-descent
parses. The interesting part is `to_affine`: it reduces any index expression to
`Index(coeff, offset)` by walking the expression tree. `2*i+1` becomes `Index(2, 1)`;
`i-1` becomes `Index(1, -1)`; `i*i` becomes `None` (flagged non-affine, rejected later).
This stage produces the toy-IR `Loop` object.

**Stage 2 — Scope check** (`scope.py`). Confirms the shape: trip count non-negative, body
not empty, the induction variable not reused as an array name, every write index affine.
Because the text format cannot express control flow, most structural assumptions hold by
construction — this stage is the explicit gate.

**Stage 3 — Dependence analysis** (`dependence.py`). Collects every read and write. For
each pair on the **same array** with at least one write:

- Equal coefficients (`c1 == c1'`): solve `c1*i + c0 = c1*j + c0'` exactly -> dependence
  distance `d = (c0' - c0) / c1`. The pair is loop-carried iff `0 < |d| < trip`.
- Differing coefficients: apply the **GCD necessary condition** — if `gcd(c1, c1')` does
  **not** divide `c0' - c0`, the accesses are provably independent; if it does, the
  simplified test cannot disprove a dependence, so the pair is treated conservatively as
  possibly dependent.

Read-read pairs are skipped (they commute). Distinct array names are assumed
non-aliasing. The result is `DependenceResult(has_dependence, pairs, distances)`, with
each pair labelled RAW / WAR / WAW.

**Stage 4 — Legality** (`legality.py`). Hard preconditions, each with a reason string:
every index affine; every access **unit-stride** (`coeff == 1`); no function calls; the
induction variable not used as a scalar value; only supported operators. Any failure
leaves the loop scalar.

**Stage 5 — Transform** (`transform.py`). Strip-mining with width `V`:
`vector_trip = (trip // V) * V` iterations go to the vector loop, `remainder_trip =
trip % V` to the scalar tail. The scalar body is lowered to pseudo-ops — `VLOAD`,
`VBCAST`, `VADD/VSUB/VMUL/VDIV`, `VSTORE` — through a small temp allocator (`v0, v1, ...`).

**Executor** (`executor.py`). Generates deterministic arrays, runs the **scalar** loop,
runs the **vectorized** program (interpreting each pseudo-op over V consecutive
elements), and compares the two array states. This turns "semantics-preserving" into a
passing test.

## 8. Input format

A `.loop` file:

```text
# comments start with '#'
vector_width 4                # optional; defaults to 4

loop i = 0 to 100             # iterations are start .. end-1 (trip count = 100)
    y[i] = alpha * x[i] + y[i]
end
```

Rules: one loop per file; one induction variable; one basic block; affine indices (`i`,
`i-1`, `i+1`, `2*i+1`); right-hand sides use `+ - * /`, array reads, integer literals and
loop-invariant scalars. A call such as `foo(...)` parses but is rejected as out of scope.
A malformed file exits with code `2` and a message.

## 9. Output format

**Human report** (`uv run avlo examples/saxpy.loop`):

```
Input (examples/saxpy.loop):
  loop i = 0 to 100    (trip count = 100, vector width = 4)
      y[i] = alpha * x[i] + y[i]

[1] Scope check         : PASS
[2] Dependence analysis : INDEPENDENT
[3] Legality check      : PASS

Verdict: VECTORIZED

Output IR:
  # vector main loop: i = 0, 4, ... < 100  (25 vector iteration(s), 4 elements each)
  i = 0
  while i < 100:
      v0 = VBCAST alpha
      v1 = VLOAD x[i]
      v2 = VMUL v0, v1
      v3 = VLOAD y[i]
      v4 = VADD v2, v3
      VSTORE y[i], v4
      i = i + 4
```

**JSON** (`--json`) — the same data machine-readable, used by the test suite.
**Equivalence** (`--verify`) — appends `Equivalence check: PASS`, or lists the mismatched
elements.

## 10. Two worked examples to know cold

**Vectorizable** — `c[i] = a[i] + b[i]`: write `c[i]`, read `a[i]` and `b[i]` — three
different arrays, no dependence — emits `VLOAD a`, `VLOAD b`, `VADD`, `VSTORE c`.

**Not vectorizable** — `a[i] = a[i-1] + 1`: the write to `a[i]` at iteration `i` and the
read of `a[i-1]` at iteration `i+1` touch the same element in different iterations ->
`REJECTED — RAW on a, distance -1`. It is rejected at **stage 3**, so the report shows
`[3] Legality check : not reached`.

## 11. How to run it

```bash
git checkout testing
uv sync
uv run pytest                              # 34 passed
uv run avlo examples/saxpy.loop            # vectorized
uv run avlo --verify examples/saxpy.loop   # equivalence PASS
uv run avlo examples/recurrence.loop       # rejected: RAW -1
uv run avlo examples/function_call.loop    # rejected by legality
uv run avlo examples/uneven_trip.loop      # vector main loop + scalar remainder
```

## 12. Who explains what (viva)

| Member | Files | Must be able to explain |
|---|---|---|
| **Ayush** (front-end) | `ir.py`, `parser.py`, `scope.py` | tokenizer -> recursive descent; how `2*i+1` becomes `Index(2,1)`; what happens when it cannot; why a negative trip count is rejected |
| **Siddhant** (algorithm) | `dependence.py`, `legality.py` | the equal-coefficient distance formula; when GCD disproves a dependence; the legality preconditions; why differing coefficients are conservative |
| **Kaviya** (integration) | `transform.py`, `pipeline.py` | why a remainder loop exists; what sets its trip count; stage order and which stage rejects first |
| **Gnana** (testing/interface) | `executor.py`, `report.py`, `cli.py`, `tests/`, README | how `VLOAD/VBCAST/VSTORE` execute; what equivalence checking proves; how to run the demo from a clean clone |

Everyone should be able to answer the cross-cutting question: **"walk me through what
happens to `a[i] = a[i-1] + 1` when I run it"** — parse, scope passes, dependence finds
RAW at distance -1, the loop is rejected, and it is left in scalar form.

## 13. Likely viva probes, with answers

- **"Is this real vectorization?"** No. It is an IR-to-IR decision-and-transformation
  demo; the output is pseudo-ops, not SIMD. No speedup is claimed.
- **"How do you know the transform is correct?"** `executor.py` runs the scalar loop and
  the vectorized program on identical inputs and compares the results; tested across
  widths 1–8 and trip counts below, equal to, and above the width.
- **"What is your dependence test's weakness?"** When coefficients differ it cannot solve
  the two-variable Diophantine, so it falls back to the GCD necessary condition and is
  conservative — it may report a dependence a full solver would disprove. Documented as
  defect D-04.
- **"What did you find and fix?"** The defect log: the right-hand-side array parse bug
  (D-01), plus two correctness traps *prevented* by rejection — induction-variable-as-
  scalar (D-02) and strided accesses (D-03).

## 14. Test evidence

| ID | Category | Input | Expected | Actual | Result |
|---|---|---|---|---|---|
| T-01 | Positive | `c[i] = a[i] + b[i]` | VECTORIZED | VECTORIZED | PASS |
| T-02 | Positive | `c[i] = a[i] - b[i]` | VECTORIZED | VECTORIZED | PASS |
| T-03 | Positive | `c[i] = a[i] * b[i]` | VECTORIZED | VECTORIZED | PASS |
| T-04 | Positive | `b[i] = a[i]` | VECTORIZED | VECTORIZED | PASS |
| T-05 | Positive | `y[i] = alpha*x[i] + y[i]` | VECTORIZED | VECTORIZED | PASS |
| T-06 | Negative | `a[i] = a[i-1] + 1` | REJECTED | REJECTED — RAW, distance -1 | PASS |
| T-07 | Negative | `a[i+1] = a[i] * 2` | REJECTED | REJECTED — RAW, distance -1 | PASS |
| T-08 | Negative | body containing `foo(...)` | REJECTED | REJECTED — legality: function call | PASS |
| T-09 | Boundary | trip count < vector width | remainder loop only | vector_trip = 0, remainder = 3 | PASS |
| T-10 | Boundary | trip count not divisible by width | vector loop + remainder | vector_trip = 100, remainder = 1 | PASS |
| T-11 | Boundary | trip count = 0 | no-op, no crash | no loops emitted | PASS |

Total: **34 tests, all passing** (`uv run pytest`).
