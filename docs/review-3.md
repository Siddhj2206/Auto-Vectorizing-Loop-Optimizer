# Project Review 3 — Final Demonstration and Evaluation

**Project:** Auto-Vectorizing Loop Optimizer (AVLO)
**Course:** BCSE307 Compiler Design
**Team:** A9
**Review date:** ____________________
**Faculty / evaluator:** ____________________

## Project outcome

AVLO analyzes supported counted loops in C, checks their memory dependences and
legality, and reports the full source with accepted loops strip-mined: a main
loop holding V copies of the body (four by default) plus a scalar remainder
loop, with rejected loops printed unchanged. `--emit-c` writes the original C
with OpenMP SIMD directives on accepted loops. The printed strip-mined form is a
reference view; the emitted C is the compiled artifact, and a regular C compiler
performs machine-code generation. The repository also retains a small internal loop IR
for analysis and transformation tests; `.loop` files are no longer the project
examples or the primary user input.

## Objectives and evidence

| Objective | Review 3 evidence | Status |
|---|---|---|
| Analyze real C programs and report loop decisions | `avlo <file.c>` and JSON output; C examples in `examples/` | Implemented for the documented subset |
| Reject unsafe or unsupported loop forms with a reason | Scope, dependence, legality, alias, control-flow and unsupported-form checks | Implemented conservatively within the documented subset |
| Emit compilable C with SIMD annotations for accepted loops | `avlo <file.c> --emit-c output.c`; OpenMP SIMD pragmas | Implemented |
| Show the strip-mined form of accepted loops | `avlo <file.c>` prints the full source with a V-iteration main loop (four by default; `#pragma avlo width(N)` or `--width N`) and a scalar remainder | Implemented as a display-only representation; `--emit-c` remains the compiled artifact |
| Cover control flow, nested loops, reductions, function calls and affine accesses | Branch, nested-loop, reduction, call, stride and rejection examples | Partial; see supported subset and limitations below |
| Validate emitted output | `uv run pytest`; `uv run python scripts/e2e_c_examples.py` | 42 tests passed; 29 C examples compiled and ran or compiled as translation units |
| Reproduce the project on another system | `uv sync`, README commands, C example end-to-end script | Documented; script requires GCC or compatible `CC` with OpenMP SIMD support |

## Implementation completed since Review 2

- Added a `pycparser` C front end and C-oriented CLI analysis, including JSON
  output and source locations.
- Added analysis support for counted loops, perfect loop nests, selected nested
  branches, reductions, affine and strided accesses, common scalar types, and
  selected pure function calls. Added pointer/restrict checks that reject cases
  the analyzer cannot establish as safe.
- Added C emission with OpenMP SIMD directives for accepted loops, reduction
  clauses, and `declare simd` annotations for supported pure helper functions.
  Emission handles multiple loops on one source line and source locations that
  are shifted by macro expansion.
- The C report prints the full source with accepted loops strip-mined: four
  copies of the body with the induction variable shifted, followed by the
  original loop as the scalar remainder. Rejected loops are printed unchanged.
  This form is illustrative; `--emit-c` remains the output that is compiled.
- Expanded the C examples and end-to-end compile/output comparison script;
  replaced the toy `.loop` examples with C examples.
- Updated the README and CLI descriptions for C input and documented behavior.

## Supported behavior and remaining limits

The current front end targets counted `for` loops with a constant, non-zero
induction step and constant or runtime bounds. It supports perfect nests with
innermost-loop analysis, selected affine subscripts (including strides),
fixed local multidimensional arrays, selected `if/else` branches, `+` and `*`
reductions, and a limited set of pure math or single-return helper calls. The
report prints accepted loops as a strip-mined main loop plus a scalar remainder;
the emitter preserves the C source and adds OpenMP SIMD directives where
analysis accepts a loop.

The printed strip-mined form is generated from the analyzed loop: the body is
duplicated once per lane with the induction variable shifted, then the original
loop follows as the scalar remainder. It is not compiled or executed. Only the
`--emit-c` output is compiled by the regression script, so that file remains the
artifact to inspect for code generation.

The implementation is not a complete C compiler or general-purpose optimizer.
Conditional compilation, arbitrary pointer-to-pointer row accesses, general
pointer alias analysis, side-effecting or unrecognized calls, early loop exits,
and general control flow are unsupported or rejected. Alias conclusions rely on
the documented rules, including `restrict` where it is needed to establish
disjoint pointer bases. Dependence analysis is simplified and conservative for
some affine patterns; it can reject a loop that a more complete solver might
prove safe. AVLO does not itself generate machine SIMD instructions or claim
measured speedups. See the README for the current subset and known
simplifications.

## Reproducible demonstration

From the repository root:

```bash
uv sync
uv run avlo examples/vector_add.c
uv run avlo examples/vector_add.c --width 8
uv run avlo examples/branch.c --emit-c /tmp/branch.simd.c
gcc -O3 -fopenmp-simd /tmp/branch.simd.c -o /tmp/branch
/tmp/branch
uv run pytest
uv run python scripts/e2e_c_examples.py
```

Suggested live sequence:

1. Show the repository revision, dependencies, and commands above.
2. Analyze and emit a representative valid C loop; explain the reported decision,
   the printed strip-mined representation, and where the directive appears
   in generated C. Change `#pragma avlo width(4)` in `examples/vector_add.c` to
   `8` (or pass `--width 8`) to show the printed lane count change live.
3. Demonstrate a nested or boundary case and a reduction or supported branch.
4. Analyze an unsafe dependence or unsupported pointer/control-flow case and
   show why it remains unannotated.
5. Run the test suite and C example script; inspect an internal source location
   or JSON record and explain a design trade-off.
6. Invite an evaluator-selected input, then discuss its expected behavior and
   actual result.

The checked results recorded for this workspace are **42 passing pytest tests**
and **29 validated C examples**. Across those examples the analysis accepts 47
loops, rejects 4 and marks 1 unsupported. The end-to-end script compiles original
and emitted programs with GCC using `-std=c11 -O2 -fopenmp-simd` and compares
their stdout for runnable examples; a non-runnable translation unit is
compile-checked. This is regression evidence for these examples, not a proof of
correctness for all C programs.

## Member-wise contribution record

Complete this table with each member and evidence that can be checked in the
repository (commits, files, tests, or demo). Do not infer individual marks from
the team-level results above.

| Member | Primary technical ownership | Final deliverable | Evidence / commit / test | Integration or support | Viva module |
|---|---|---|---|---|---|
| 1 |  |  |  |  |  |
| 2 |  |  |  |  |  |
| 3 |  |  |  |  |  |
| 4 |  |  |  |  |  |

## Final review record

| Criterion | Maximum | Marks awarded | Evaluator remarks |
|---|---:|---:|---|
| Final system completeness and correctness | 2.5 |  |  |
| Live demonstration and use-case coverage | 1.5 |  |  |
| Testing, results and evaluation | 1.5 |  |  |
| Technical depth, design decisions and innovation | 1.0 |  |  |
| Final report, repository and reproducibility | 1.0 |  |  |
| Verified individual contribution | 1.5 |  |  |
| Presentation and viva | 1.0 |  |  |
| **Total** | **10.0** |  |  |

**Overall decision:** ☐ Completed satisfactorily  ☐ Completed with minor corrections  ☐ Incomplete / major correction required

**Final remarks / corrections / distinctive achievement:**

______________________________________________________________________________

______________________________________________________________________________

| Team leader signature | Faculty / evaluator signature | Date |
|---|---|---|
|  |  |  |

## Final submission checklist

- [ ] Final presentation and consolidated report reflect the implementation and
  results actually demonstrated.
- [ ] Repository, README, dependencies, build/run instructions and sample C
  inputs are present.
- [ ] Test suite and C end-to-end compile/output checks run on the demonstration
  system.
- [ ] Architecture, module descriptions, known limitations and future work are
  current.
- [ ] Contribution matrix is completed with verifiable member-specific evidence.
- [ ] External code, libraries, datasets and other reused material are
  acknowledged; no credentials or unapproved private data are included.
- [ ] Backup copy of code, report, presentation and sample data is available.
