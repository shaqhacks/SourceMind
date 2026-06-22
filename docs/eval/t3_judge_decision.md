# T3 — LLM-Judge Self-Repair: Decision

**Verdict: SKIP the LLM judge. Ship only the non-LLM revert-guard.**

## The conditional gate

T3 was scoped to build only if **both** hold:

1. T2 shows decomposition is *good-but-improvable*, and
2. a quick prototype shows the judge **raises the eval score**.

## Evidence

T2's structural rubric scores every fixture in the corpus at **total = 1.00**
(`docs/eval/decomposition_scores.json`): acyclic, genuine prerequisites,
cold-start root, and correct ordering are all satisfied. This is not luck —
`CourseEngine.build_competency_map` constructs a linear prerequisite chain by
construction, so any non-empty outline is structurally perfect on this rubric.

Consequences for the gate:

- **Not "good-but-improvable" on the measured axis.** The score is already at the
  ceiling, so condition (1) fails.
- **A judge cannot raise the score.** Since `repaired.total <= 1.00 == original.total`,
  the best a repair can do is tie. No prototype can show a positive delta, so
  condition (2) fails by deduction — no live LLM run is needed to know this.

## Why a judge would be premature (not just unnecessary)

The current rubric is **structural**. It deliberately does not measure content
quality (e.g. the `messy_scan` OCR fixture also scores 1.00 despite garbled
content). A judge wired against this rubric would be optimizing a metric it has
already maxed, with no signal to climb — it would burn latency/tokens for zero
measurable gain and risk silent regressions.

**Prerequisite for revisiting T3:** extend the eval rubric to a content-quality
axis (concept coverage vs. source, prerequisite *semantics*, granularity) that
the heuristic decomposer does **not** trivially max. Only once the harness can
distinguish good from better does a self-repair judge have a gradient to follow.

## What we still shipped

`backend/services/decomposition_judge.apply_judge_if_improved(original, repaired)`
— the safety invariant a future judge MUST pass through: keep the repaired tree
only if `repaired.total >= original.total`, else revert. Self-repair becomes a
no-regression operation by construction, independent of the repair's source.
Covered by `backend/tests/test_decomposition_judge.py`.
