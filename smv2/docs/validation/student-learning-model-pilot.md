# Student Learning Model Pilot Protocol

## Purpose

This pilot evaluates whether concept-targeted adaptive practice improves delayed performance on unseen, reviewed items relative to workload-matched baseline review. It validates a product intervention; it does not establish a learner trait or a causal diagnosis of why a learner struggled.

## Eligibility and assignment

- Eligible units are learner–concept pairs with a published curriculum, reviewed primary item mappings, at least three distinct evidence items across two occasions, and at least one unseen reviewed probe item aligned to the same learning claim.
- Assignment is stored once as `adaptive_targeted` or `baseline_review` using a versioned seed and deterministic balanced ordering. Database constraints and an update trigger prevent reassignment after outcomes are observed.
- Both groups receive the same activity-count target. The control group retains ordinary due and coverage review but does not receive the likely-struggling priority boost for its assigned concept.
- Learners outside an active study receive the normal adaptive policy.

## Intervention and leakage controls

- Treatment items and delayed probes must be different immutable `EvidenceItem` records.
- A probe must have a verified primary claim mapping and must be unseen by the learner when scheduled.
- Scheduled probes are withheld from the study queue until the delayed window opens.
- Probe completion is linked to the append-only learner evidence event produced by the answer; the assignment and scheduled item are not rewritten.

## Outcomes

The primary outcome is correctness on the first delayed probe completed 7–14 days after assignment. Secondary outcomes are longer-delay correctness, transfer-task correctness where a separately reviewed transfer item exists, activity workload, completion, attrition, and blinded instructor agreement with the learner-model classification.

Reports include assignment counts, completion counts, out-of-window responses, attrition, workload by group, and group correctness. No effect or causal summary is shown unless both groups meet the stored minimum sample threshold. Missing probes are reported as attrition, not silently excluded from the denominator of participation reporting.

## Stopping and review

- Stop for a material workload imbalance, a probe-leakage defect, assignment mutation, or evidence of harm such as sharply lower completion in either group.
- Do not promote a challenger model from this experiment alone. Challenger promotion follows `challenger-model-promotion.md` and requires calibration, delayed prediction, subgroup, interpretability, and rollback review.
- A local-profile installation is a single-user pilot surface. Any classroom or remote deployment requires consent language, authentication, role-based access, retention policy, and institutional review appropriate to the deployment context.

## Interpretation limits

Correctness is evidence about performance on mapped tasks, not direct observation of a mental state. Item quality, mapping quality, opportunity to learn, language demands, accessibility, and outside study can affect results. Small samples and repeated measures within a learner invalidate naive independent-observation significance tests; analysis should use learner-aware uncertainty and report confidence intervals alongside raw outcomes.
