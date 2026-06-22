# T11 — External Ground-Truth Spot-Check

**Purpose:** before trusting the eval harness, validate it against at least one
source from a domain we did **not** tune on, using ground truth set from an
external reference rather than by inspecting our own output.

## Source

- **Domain:** music theory (not present in the tuned corpus, whose domains are
  mathematics, biology, programming, history, earth-science).
- **Fixture:** `backend/tests/fixtures/decomposition/external/music_theory.txt`
- **Ground truth:** taken from a standard music-theory teaching sequence
  (pitch → rhythm; notes → accidentals; note durations → time signatures). An
  externally-correct decomposition of this material is acyclic, has a clear
  cold-start root (reading notes on the staff), and orders prerequisites
  correctly — so it **must pass** the structural rubric.

## Result

`run_eval` over the external source agrees with the external ground-truth
verdict (`passed = True`). Verified by
`backend/tests/test_hardening.py::test_external_spotcheck_agrees_with_ground_truth`,
which also asserts the source's domain is outside the tuned corpus.

## Interpretation

The harness generalizes its **structural** judgment to an unfamiliar domain.
This is a guard against overfitting the rubric to the curated corpus. It does
**not** validate content-quality judgment — the rubric remains structural (see
`docs/eval/t3_judge_decision.md`); extending it to content quality would require
a correspondingly broader external spot-check before trust.
