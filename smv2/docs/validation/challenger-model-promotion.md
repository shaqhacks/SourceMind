# Challenger Learner-Model Promotion Protocol

Status: required gate; no challenger is learner-facing by default.

## Authority boundary

`transparent-beta-v1` is the only learner-facing readiness estimator. BKT,
PFA, and the DAS3H-style model consume the same cutoff-bounded evidence
snapshot and write immutable shadow predictions. Their output must not be
read by the concept map, classification logic, or study scheduler before a
separate promotion decision is approved.

## Data gates

The coded minimums are conservative pilot hypotheses, not literature-derived
universal constants. A model emits `insufficient_data` when any of its gates
fails. Current gates cover learner count, attempts, unique items, distinct
occasions, reviewed-mapping coverage, outcome prevalence, and—specifically for
the DAS3H-style estimator—usable spacing observations. A gate change requires
a model-version change and a new prospective evaluation window.

## Prospective evaluation

1. Freeze the model, feature schema, mappings, curriculum version, prediction
   horizon, target definition, and training cutoff before collecting outcomes.
2. Evaluate only later responses to representative, reviewed items. Use
   learner-aware temporal splits; events after the cutoff must never become
   features for that prediction.
3. Report Brier score, log loss, calibration by probability band, delayed
   correctness, bootstrap intervals, and results by course/domain, task type,
   and evidence-sufficiency band.
4. Compare each challenger against `transparent-beta-v1` on the identical
   scored cases. Training fit alone is inadmissible evidence.
5. Pair predictive evaluation with blinded instructor agreement and the
   workload-matched delayed-retention pilot described in the implementation
   plan.

## Promotion gate

A challenger may be proposed for learner-facing use only when all conditions
hold across at least two prospective evaluation windows:

- calibration and Brier score are better than the baseline, with bootstrap
  intervals that do not indicate material degradation;
- log loss is non-inferior to the baseline, using a pre-registered maximum
  relative degradation of 2%;
- delayed representative-item correctness is non-inferior, with a
  pre-registered maximum absolute degradation of 2 percentage points;
- no sufficiently sized reported subgroup shows a material safety, access, or
  calibration regression;
- mapping-review coverage and missingness remain above their registered gates;
- an instructor can understand the evidence trail and contest bad mappings;
- an architecture owner and learning-science reviewer approve the change.

The 2% floors are release criteria to validate during the pilot, not established
scientific constants.

## Rollback

Promotion must ship behind a versioned course-level authority flag. Retain the
transparent projection and its configuration. Roll back immediately if live
calibration crosses the registered tolerance, delayed performance declines,
subgroup monitoring identifies a material regression, evidence pipelines lose
mapping coverage, or predictions cannot be reproduced from the stored cutoff
and snapshot hash.

## Research basis and limitations

The model family choices follow the project research synthesis: BKT is useful
when a learned/unlearned latent state is defensible; PFA represents success and
failure opportunity counts; DAS3H adds time-window and forgetting features.
Comparative research does not establish a universal winner, so SourceMind must
validate them on its own concepts, mappings, and outcomes. See
[`sources/research_student_learning_diagnostic_system_2026-08-02.md`](../../sources/research_student_learning_diagnostic_system_2026-08-02.md)
for the cited literature and evidence limitations.
