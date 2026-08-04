# Research synthesis: a student learning and diagnostic system for SourceMind

Date: 2026-08-02

## Research question

How should SourceMind extract a defensible concept model from arbitrary books, connect learner answers to those concepts, identify likely concept-level struggle, display an honest learner estimate, and adapt Anki-style review so that retention improves and instructors agree with the diagnosis?

## User-confirmed boundaries

- Diagnose likely **concept-level struggle**, not named misconceptions or causal root causes.
- Infer from concept-linked quiz and spaced-review responses; do not require shown work or explanations by default.
- Support both procedural/quantitative and conceptual/explanatory material.
- Derive the curriculum from the book by default, with optional instructor standards and corrections.
- Add weak concepts to more frequent, concept-targeted review and question practice.
- Display an evidence-weighted concept estimate on the map.
- Validate success through delayed retention and instructor agreement.
- Do not hard-lock content in the first version.

## Method and evidence policy

Web research prioritized standards bodies, peer-reviewed journals, ACL/AAAI/EDM proceedings, ETS/ERIC, and open primary studies. The earlier SourceMind research artifact on book-to-competency extraction was reused. Claims below distinguish well-supported principles from product hypotheses that must be calibrated in SourceMind.

## Executive conclusion

SourceMind should not replace its current weighted mastery percentage with a more complicated formula in the same architecture. It should introduce an **evidence ledger and four explicitly separated models**:

1. a versioned curriculum/domain model;
2. an item/evidence model with explicit item-to-concept mappings;
3. a learner-state model with uncertainty and forgetting;
4. a pedagogical policy that schedules targeted review.

The recommended strategy is staged. Begin with a transparent, sparse-data-friendly probabilistic baseline and collect clean evidence. Evaluate PFA/BKT/DAS3H-like challengers in shadow mode after the item mappings and data volume are adequate. Promote a more complex model only if it improves calibration, delayed retention, and instructor agreement.

## 1. The governing architecture: Evidence-Centered Design

Evidence-Centered Design (ECD) treats assessment as an evidentiary argument. The student/proficiency model specifies the claim about the learner; the evidence model specifies what observations support it; and the task model specifies what tasks can elicit that evidence. An applied computer-science assessment project emphasizes that construct definitions and learning progressions must be made explicit before assessment items are authored.

For SourceMind, the claim is deliberately narrow:

> Given sufficient recent and spaced evidence from representative items, the learner is likely struggling with concept X.

It is not:

> The system knows the student's misconception or the causal root of the difficulty.

Design implication: every displayed diagnosis must be traceable backward from learner estimate -> evidence events -> item mapping -> learning claim -> source material/instructor framework.

Sources:

- Grover et al. (2021), applied ECD: https://www.frontiersin.org/journals/education/articles/10.3389/feduc.2021.695376/full
- Expanded ECD for combined learning and assessment systems: https://pmc.ncbi.nlm.nih.gov/articles/PMC6498139/

## 2. What SourceMind should model

### 2.1 Keep four semantic layers separate

1. **Concept:** a domain idea, procedure, principle, fact, or strategy discussed in the material.
2. **Learning claim:** an observable performance involving a concept, such as explaining, comparing, applying, computing, or evaluating.
3. **Evidence event:** a learner response that bears on a learning claim/concept.
4. **Learner-state estimate:** a time-dependent inference from evidence, never a property stored on the concept itself.

This permits one user-facing concept to contain multiple assessable claims. For example:

- Concept: conditional probability
- Claim: interpret a conditional probability statement
- Claim: calculate a conditional probability
- Claim: decide when conditional probability applies

A student can struggle with application while succeeding at recall. Collapsing these into one unqualified score hides the exact breakdown the product is trying to provide.

### 2.2 Versioned curriculum/domain records

Each concept should have a stable identifier independent of its generated slug, aliases, definition, concept kind, source spans, source version, review state, and instructor provenance. Each learning claim should have an observable action, object, optional conditions, cognitive demand, importance, and linked source spans.

Relations should be typed and versioned:

- `is-part-of`
- `requires`
- `recommended-before`
- `develops-into`
- `related-to`
- `equivalent-to`
- `aligns-to-standard`

Only strongly validated `requires` relations should influence consequential prerequisite logic. Presentation order is evidence for `precedes`, not proof of dependency. CASE 1.1 is a useful import/export boundary and includes association types such as `isChildOf`, `isPartOf`, `exactMatchOf`, `precedes`, `isRelatedTo`, `replacedBy`, and `hasSkillLevel`; it is not a learner-model standard.

Sources:

- 1EdTech CASE 1.1 specification: https://www.imsglobal.org/spec/case/v1p1/
- CASE 1.1 information model: https://standards.1edtech.org/case/specifications/standards/v1p1/im
- Pelánek (2024/2025), modeling challenges: https://link.springer.com/article/10.1007/s40593-024-00400-6

## 3. Extracting the model from books

### 3.1 Use automation for candidate generation, not silent publication

Research shows that textbook structure, headings, paragraphs, examples, exercises, semantic features, and ordering can support concept and prerequisite extraction. Recent weakly supervised work evaluated concept extraction over 28 economics textbooks. A 2025 LLM concept-mapping study across ten disciplines found a precision/recall tradeoff by chunk scale: section processing improved precision, while paragraph processing improved recall. Its learner evaluation was only n=14, so it supports feasibility rather than a broad validity claim.

The pipeline should therefore use multiple passes:

1. Preserve book structure and stable paragraph/exercise identifiers.
2. Extract high-precision candidates from headings, definitions, summaries, examples, and exercises.
3. Extract high-recall candidates from paragraphs and repeated terminology.
4. Normalize aliases and merge candidates using stable IDs.
5. Generate observable learning claims from explanations, worked examples, and exercises.
6. Generate typed relation candidates with source rationale and confidence.
7. Require review for low-confidence nodes, merges/splits, and high-impact `requires` edges.
8. Record accepted, edited, merged, split, and rejected candidates as evaluation data.

Sources:

- De Kuthy, Girrbach, and Meurers (2025): https://aclanthology.org/2025.bea-1.13/
- Han and Choi (2025): https://aclanthology.org/2025.bea-1.58/
- Lu et al. (2019): https://doi.org/10.1609/aaai.v33i01.33019678
- Pal et al. (2020): https://arxiv.org/abs/2011.10337
- Wang et al. (2020), reliable textbook concept annotation procedure/gold data: https://arxiv.org/abs/2005.11422

### 3.2 Granularity is an empirical hypothesis

A useful concept must be teachable, assessable through several non-duplicate items, interpretable to an instructor, and capable of showing learning/transfer patterns. Too coarse a concept hides actionable differences. Too fine a concept produces sparse data and unstable estimates.

SourceMind should permit instructor merge/split operations and preserve version history. Later, learner data should test candidate granularity through learning curves, prediction on unseen items, and instructor interpretation. KC-Finder illustrates both the promise and limit: its discovered knowledge components followed desirable learning-curve properties and were sometimes meaningful, but were not more predictive than random in that study.

Sources:

- KC-Finder (EDM 2023): https://educationaldatamining.org/edm2023/proceedings/2023.EDM-long-papers.3/
- Learning-map validation: https://www.frontiersin.org/journals/education/articles/10.3389/feduc.2021.714736/full

## 4. Item-to-concept evidence is the load-bearing layer

### 4.1 Explicit Q-matrix-style mappings

Every quiz or review item must declare which concepts/claims it provides evidence about. This is commonly represented as a Q-matrix. Q-matrix misspecification can produce invalid learner classifications regardless of the downstream diagnostic model. A reading-assessment study built an initial mapping from literature, think-aloud protocols, and expert ratings, then validated it empirically on a large response dataset.

Minimum item mapping:

- stable item and item-version ID;
- primary concept/claim;
- optional supporting concepts;
- evidence role (`primary`, `supporting`, `prerequisite`);
- task type and cognitive demand;
- authored/estimated difficulty;
- source span and answer evidence;
- generation provenance and review state;
- mapping confidence and mapping version.

Sources:

- Li and Suen (2013): https://eric.ed.gov/?id=EJ994673
- Recent Q-matrix estimation/validation warning: https://pmc.ncbi.nlm.nih.gov/articles/PMC11560062/
- ETS learning-progression classification validation: https://www.ets.org/research/policy_research_reports/publications/report/2019/kabr.html

### 4.2 Favor isolating diagnostic items

When one item requires several concepts, a wrong response does not say which concept failed. SourceMind should prefer one primary target per diagnostic item. Supporting concepts should not automatically receive the same negative update. Complex, multi-concept items remain useful for transfer, but their evidence must be down-weighted or modeled jointly until the system has sufficient data.

This is especially important for the current product: attributing every question in a section-scoped quiz to every concept linked to that section creates false evidence.

### 4.3 Generated items must be treated as versioned hypotheses

Question generation should begin from a selected learning claim and source evidence, not generate a question and invent a concept slug afterward. Validation should check:

- answer grounding in the source;
- one clearly stated primary claim;
- solvability and exactly one defensible answer;
- cognitive demand and difficulty target;
- duplicate/near-duplicate detection;
- leakage of answer text;
- instructor review priority;
- later empirical item difficulty and discrimination.

LLM generation can reduce authoring effort, but content alignment and psychometric quality vary by domain. Generated content should not establish its own validity.

## 5. Learner-state model

### 5.1 Store evidence events; derive estimates

The canonical record should be an append-only learner evidence event:

- learner ID;
- course/curriculum version;
- concept/claim and mapping version;
- item and item version;
- timestamp/session;
- evidence channel (`quiz`, `retrieval-card`, later others);
- result/grade;
- attempt number;
- spacing since previous relevant evidence;
- optional response latency/hint use;
- model version used for any contemporaneous recommendation.

Historical evidence must not be silently reinterpreted when an item mapping or concept changes.

### 5.2 Do not collapse memory and application prematurely

Flashcard recall and quiz transfer are related but not equivalent. The model should maintain at least:

- **retrieval strength/recall probability** from spaced-review events;
- **application estimate** from representative quiz items;
- **evidence sufficiency/uncertainty**;
- **trend** and last meaningful evidence time.

The concept-map headline can be an estimated probability of success on a representative current item, but the detail view must expose the two channels and confidence. `Insufficient evidence` must be different from `0%`.

### 5.3 Recommended staged models

#### Stage 1: transparent Bayesian evidence baseline

Use separate, recency-aware success/failure posteriors for quiz and review evidence. Adjust the effective evidence weight for unique items, spacing, task type, and mapping confidence. Use a weak prior and expose uncertainty. Do not hard-code the current fixed 0.5/0.3/0.2 blend as a validity claim.

This stage is implementable with sparse data and auditable by instructors. Exact diagnosis thresholds and minimum evidence counts are product hypotheses to calibrate in pilots, not universal values established by the literature.

#### Stage 2: interpretable learning-and-forgetting challenger

Once SourceMind has adequate learner/item data, evaluate:

- **PFA/logistic factor models** for successes, failures, learner ability, and item difficulty;
- **BKT** when a binary latent learned/not-learned assumption is defensible;
- **DAS3H-like models** when multiple-skill items, time windows, learning, and forgetting must be combined.

DAS3H explicitly incorporates item-skill mappings and forgetting and performed better than comparison models on three educational datasets. PFA has outperformed BKT in some comparisons, but neither is universally superior. Both have difficulty predicting incorrect responses, which is directly relevant to a struggle detector.

Sources:

- Gong, Beck, and Heffernan (2011), KT vs PFA: https://doi.org/10.3233/JAI-2011-016
- DAS3H: https://arxiv.org/abs/1905.06873
- Knowledge-tracing survey: https://doi.org/10.1145/3569576

#### Stage 3: complex models only after evidence justifies them

Deep knowledge tracing and cognitive diagnostic models should not be the cold-start default. A large empirical evaluation found deep models generally—but not always and not by much—outperformed traditional models, with sensitivity to metrics, baselines, hyperparameters, randomness, and reproducibility. Cognitive diagnostic models require a defensible Q-matrix and enough items/learners per attribute profile.

Source:

- Sarsa, Leinonen, and Hellas (2022): https://eric.ed.gov/?id=EJ1362649

## 6. Defining “likely struggling”

The system should make a decision from both the estimate and its uncertainty:

- `insufficient evidence`: too little independent evidence to classify;
- `watch`: negative signal exists but uncertainty remains high;
- `likely struggling`: sufficiently strong probability that current performance is below the target;
- `building`: improving but not yet stable across spacing and item variation;
- `retained`: successful delayed retrieval/application with adequate evidence.

Exact cutoffs must be calibrated. A safe logic shape is:

> Flag likely struggle only when the posterior probability of being below the performance target exceeds a chosen confidence threshold and evidence covers more than one unique item/occasion.

The UI should show:

- current estimate;
- confidence/evidence sufficiency;
- quiz/application sub-estimate;
- review/recall sub-estimate;
- evidence count and date range;
- trend;
- “why this is shown” evidence trail.

This is more honest than displaying `67% mastery` without defining the estimand.

## 7. Adaptive Anki-style intervention

### 7.1 Separate concept priority from item scheduling

The scheduler needs two decisions:

1. **Which concept needs attention?** Based on likely struggle, forgetting risk, uncertainty reduction, curriculum importance, and workload.
2. **Which item should be shown?** Based on target claim, item novelty, difficulty, cognitive demand, prior exposures, and spacing.

A concept can be weak while a particular flashcard is memorized. Repeating the same card can create item-specific memorization without transfer. Recovery should therefore require delayed success on varied or unseen items.

### 7.2 Review behavior

When a concept becomes likely struggling:

1. raise its concept-level review priority;
2. schedule a short retrieval item grounded in the relevant reading;
3. schedule a later varied quiz/application item;
4. interleave it with other concepts rather than massing repetitions;
5. lengthen intervals after successful delayed retrieval;
6. if failures persist, surface the relevant reading/example and notify the instructor-facing diagnosis view;
7. cap remediation workload so one weak concept does not consume the whole plan.

The product should retain an exploration/coverage budget for new or uncertain concepts, otherwise the feedback loop will over-focus on already measured weaknesses.

### 7.3 Research support and limits

Retrieval practice and spacing have strong support for retention, including classroom research and meta-analytic evidence. A large randomized experiment with roughly 50,700 adult learners found an ML item-selection algorithm improved memorization duration by about 69% after controlling study length/frequency. However, the domain was a driver's-permit question bank, so it does not prove the same effect for arbitrary books or conceptual transfer.

Half-life regression improved recall prediction for Duolingo language items and operational engagement, but language lexemes are not the same as broad concepts. DAS3H is more relevant because it models time, forgetting, and multi-skill items, but its published evidence is predictive comparison rather than a SourceMind retention trial.

Sources:

- Upadhyay et al. (2021) randomized experiment: https://www.nature.com/articles/s41539-021-00105-8
- Settles and Meeder (2016), half-life regression: https://aclanthology.org/P16-1174/
- DAS3H: https://arxiv.org/abs/1905.06873
- Classroom retrieval-practice review: https://www.frontiersin.org/journals/education/articles/10.3389/feduc.2019.00005/full

## 8. Validation program

### 8.1 Gate 1: content and mapping validity

Before learner diagnoses are trusted:

- instructors review concept definitions/granularity;
- instructors review a stratified sample of item-to-concept mappings;
- disagreements are adjudicated and used to revise instructions/schema;
- learning curves and item statistics identify implausible concepts or mappings;
- low-quality or low-discrimination items are retired.

Expert review and empirical data are complementary. Q-matrix and learning-progression research uses both.

### 8.2 Gate 2: instructor agreement

Instructor agreement is a user-selected success criterion, but teachers are not an infallible gold standard. A 75-study meta-analysis found an overall correlation of 0.63 between teacher judgments and standardized achievement, with better correspondence when judgments were informed. Therefore:

- collect instructor judgments at the same concept granularity as the system;
- blind instructors to the model flag during validation;
- use at least two raters for a subset when practical;
- report precision/recall for `likely struggling`, agreement coefficients, and disagreement reasons;
- distinguish model error, item-mapping error, concept-granularity error, and teacher disagreement.

Sources:

- Südkamp, Kaiser, and Möller (2012): https://eric.ed.gov/?id=EJ993888
- Learning-map work comparing blind teacher placement with response evidence: https://www.frontiersin.org/journals/education/articles/10.3389/feduc.2021.714736/full

### 8.3 Gate 3: delayed retention

Immediate practice gains are not sufficient. Run a workload-matched experiment:

- eligibility: concepts with sufficient evidence and uncertain/weak estimates;
- treatment: concept-targeted adaptive review;
- control: current/static or difficulty-only review with equal study time;
- primary outcome: delayed performance on unseen but equivalent concept-linked items;
- secondary outcomes: longer-delay retention, transfer task performance, review workload, completion, and instructor agreement;
- analysis: concept- and learner-level effects, not only aggregate accuracy.

A within-learner randomization by eligible concept can be efficient for an early pilot, but contamination and prerequisite spillover must be considered. Causal “improves retention” claims require randomization or a comparably strong design.

### 8.4 Necessary internal metric: calibration

Although the user selected retention and instructor agreement as product success, the displayed probability must still be calibrated. If SourceMind displays approximately 67% for many comparable cases, roughly that proportion should succeed on future representative items. Track Brier score/log loss, calibration curves, and performance by evidence sufficiency, subject family, and task type.

## 9. Comparison of architectural approaches

### Approach A: improve the current weighted score

Add recency and attempt counts to the existing quiz/practice/SRS weighted average.

- Advantages: smallest migration; easy to explain.
- Failure: preserves invalid section-level attribution, fixed signal weights, missing uncertainty, cross-learner leakage, and flashcard/quiz equivalence.
- Verdict: acceptable only as a disposable UI prototype, not the requested diagnostic system.

### Approach B: evidence ledger + transparent probabilistic baseline

Version concepts and item mappings, store learner evidence events, keep quiz and retrieval channels separate, derive an uncertainty-aware estimate, and drive a bounded adaptive scheduler. Evaluate richer models in shadow mode.

- Advantages: works with sparse data; auditable; supports local-first; creates the data needed for future models; aligns with ECD and Q-matrix validation.
- Costs: schema and generation pipeline changes; instructor tooling; staged calibration.
- Verdict: recommended.

### Approach C: full knowledge-tracing/cognitive-diagnostic platform immediately

Adopt BKT/PFA/DAS3H/DCM or a neural model from the start.

- Advantages: expressive and academically familiar.
- Failure: model sophistication cannot rescue invalid item mappings; arbitrary books and local sparse data do not supply stable parameters; harder to explain and validate.
- Verdict: use as later challenger models, not the initial production foundation.

## 10. Direct assessment of the current SourceMind model

The current implementation is structurally useful for a map prototype but not adequate for the requested claims:

- concepts have only slug/label/section identity;
- edges are untyped binary prerequisites;
- practice-generated concept slugs are exact identity keys with no reconciliation;
- quiz evidence is attributed from test scope to every concept in intersecting sections;
- SRS evidence averages latest card grades, ignoring time, repetitions, and item coverage;
- missing signals are renormalized, so one evidence channel can yield 100;
- fixed thresholds label struggle/solid and can block downstream nodes without calibration;
- the skills map currently aggregates practice mastery across learner keys;
- item-level quiz-to-concept tagging was explicitly deferred.

The first implementation prerequisite is therefore not a new scheduling algorithm. It is trustworthy learner scoping plus versioned item-to-concept evidence.

## 11. Recommended system in one flow

```text
Book + optional standards
        ↓
Candidate concepts and observable learning claims
        ↓ instructor review/versioning
Versioned curriculum graph + grounded source spans
        ↓
Claim-first question/card generation
        ↓ validation and explicit item→concept mapping
Learner response evidence ledger
        ↓
Separate quiz/application and review/recall estimates
        ↓ uncertainty-aware concept state
Concept map: estimate + confidence + evidence + trend
        ↓
Bounded concept-priority scheduler
        ↓
Varied, spaced retrieval and application practice
        ↓
Delayed retention + instructor-agreement validation
        ↺ curriculum/item/model refinement
```

## 12. Open empirical parameters, not user ambiguities

The following should be selected through pilot data, not asserted from general research:

- minimum effective evidence before showing `likely struggling`;
- probability/confidence thresholds;
- quiz versus retrieval observation parameters;
- decay/forgetting parameters by task and concept type;
- remediation workload cap and exploration budget;
- target retention level and review interval policy;
- instructor-agreement acceptance threshold;
- delayed-test intervals appropriate to the course.

These are research parameters within the approved decision boundaries, not unresolved product intent.

## Bottom line

The key product asset is not the visible percentage. It is the chain of validity underneath it. SourceMind should be able to answer:

1. What exactly is this concept/claim?
2. Which source and instructor decision established it?
3. Which items genuinely measure it?
4. Which learner events changed the estimate?
5. How uncertain is the estimate?
6. Why did the scheduler choose this review?
7. Did the intervention improve delayed performance?

If any link is missing, the product should show uncertainty rather than a confident mastery number.
