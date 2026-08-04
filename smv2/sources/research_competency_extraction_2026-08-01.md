# Research notes: extracting competencies and prerequisite structure from books

Date: 2026-08-01

## Research question

How can SourceMind extract useful competencies from books, represent how they build on one another, and turn the result into an implementable, evidence-backed learning system?

## Search method

The local `research-lookup` CLI was unavailable and its optional API keys were not configured. Research was therefore performed with web search, prioritizing standards bodies, peer-reviewed papers, major academic publishers, ACL/AAAI proceedings, ETS, ERIC, and university teaching centers. The searches covered:

- competency interchange standards and relationship types;
- evidence-centered assessment design;
- textbook concept extraction and prerequisite-relation learning;
- learning progressions and empirical map validation;
- Q-matrices, cognitive diagnosis, knowledge tracing, and knowledge-component discovery;
- measurable learning-objective generation with LLMs.

## Main findings

### 1. A topic label is not yet a competency

Learning objectives are normally expressed as observable, measurable performances. A useful minimum representation is an action plus an object, with optional context, constraints, and success criteria. Bloom's revised taxonomy is useful as a vocabulary for cognitive demand, but verb labels alone do not establish assessment validity.

Implication: `tokenization` is a topic/concept; `estimate token usage for a prompt within an error tolerance` is a competency that can be assessed.

### 2. Separate the domain, evidence, learner, and pedagogical models

Evidence-Centered Design distinguishes what the domain contains, what claims will be made about a learner, what observable evidence supports those claims, and what tasks elicit that evidence. Modern adaptive-learning reviews make a similar distinction between domain, student, and pedagogical models.

Implication: book extraction should create a versioned domain hypothesis. It should not directly set learner mastery. Questions, responses, and rubrics provide evidence to a separate learner-state model; a pedagogical policy chooses the next reading or practice activity.

### 3. Textbook structure is a useful signal, not proof of prerequisites

Research has successfully used textbook content, table-of-contents structure, concept occurrence, semantic features, and presentation order to predict prerequisite relations. However, prerequisite edges have different meanings: strictly necessary, merely helpful, or conventional sequencing. Order alone is not sufficient.

Implication: candidate edges should carry a typed meaning, confidence, source rationale, and review state. A strict `requires` edge should be rarer than a `recommended-before` or `related-to` edge.

### 4. Automated extraction is best treated as candidate generation

Textbook annotation research reports that unsupervised keyphrase extraction is not accurate enough for reliable concept annotation and favors expert-produced gold data. Recent LLM and weak-supervision work shows that automation can reduce authoring effort, but precision and recall vary by chunk size and discipline. LLM-generated learning objectives can be sensible and measurable, yet still lack focus and show only fair inter-rater agreement at detailed Bloom levels.

Implication: use schema-constrained extraction with exact source spans and a human review queue. Save accepted, rejected, merged, and edited candidates as training/evaluation data.

### 5. Competency granularity must be validated against tasks and learner data

Knowledge-component research treats a useful skill as one that helps explain and predict performance across a coherent set of tasks and exhibits learning/transfer patterns. Very coarse skills hide actionable differences; very fine skills create sparse evidence, maintenance costs, and confusing learner interfaces.

Implication: begin with instructor-usable granularity, then split or merge nodes when item responses and transfer patterns justify it. Maintain aliases and version history rather than using generated slugs as semantic identity.

### 6. Item-to-competency mapping is load-bearing

A Q-matrix maps each assessment item to the skills required to answer it. Cognitive-diagnosis literature repeatedly warns that misspecified mappings invalidate learner classifications. Multi-skill questions also create a credit-assignment problem: a wrong answer does not reveal which required skill failed.

Implication: every practice or homework item should have explicit competency links, role (`primary`, `supporting`, or `prerequisite`), and evidence type. Prefer diagnostic items that isolate one target competency; use step-level scoring or rubrics for complex tasks.

### 7. Learning progressions are hypotheses that need two kinds of validation

The learning-progression literature distinguishes procedural evidence (research review, educator input, examples of student work, external review) from empirical evidence (item difficulty, response patterns, model comparison, external outcomes). Neither is sufficient alone.

Implication: a released graph needs provenance and expert approval first, then telemetry that tests whether supposed advanced skills are actually harder, whether forbidden mastery profiles occur, and whether remediation improves later performance.

### 8. There is a useful interchange standard, but it is not the whole internal model

1EdTech CASE 1.1 represents machine-readable competency frameworks with stable identifiers, items, rubrics, and association types such as `isChildOf`, `isPartOf`, `exactMatchOf`, `precedes`, `isRelatedTo`, and `hasSkillLevel`. CASE is designed for interoperability and does not prescribe internal learner modeling.

Implication: use CASE concepts as an export/import boundary and naming guide. Keep SourceMind-specific provenance, confidence, evidence mappings, and learner-state calculations in the internal model.

## Recommended implementable architecture

Use a two-layer, human-reviewed competency model:

1. **Concept layer:** canonical topics/entities appearing in the book, with aliases, definitions, and grounded source spans.
2. **Competency layer:** observable statements of what a learner can do with one or more concepts. Store action, object, context/constraints, success criteria, cognitive demand, source evidence, confidence, version, and review status.
3. **Typed relations:** `is-part-of`, `requires`, `recommended-before`, `develops-into`, `related-to`, and `equivalent-to`. Only `requires` participates in hard prerequisite logic, and no hard gating should ship until validated.
4. **Resource alignment:** sections, examples, cards, and questions link to competencies with a role and relevance.
5. **Evidence model:** each assessment item declares the competency evidence it can provide and how the response is scored. Evidence is stored as events, not directly as an unqualified mastery percentage.
6. **Learner model:** maintain per-learner estimates with evidence count, recency, uncertainty/confidence, and model version. Start with a transparent Beta-Binomial or simple BKT/PFA-style model before considering black-box tracing.
7. **Validation loop:** expert review before publishing; later compare candidate graphs and item mappings against response data, learning curves, item difficulty, teacher ratings, and remediation outcomes.

## Suggested extraction pipeline

1. Parse the book into structural sections and preserve page/paragraph identifiers.
2. Extract high-recall candidate concepts from paragraphs and high-precision candidates from sections/headings/exercises.
3. Normalize aliases and merge candidates into canonical concepts; never use model-generated slugs as the only identity.
4. Generate measurable competency candidates from explanations, worked examples, exercises, summaries, and stated objectives.
5. Require each candidate to cite supporting source spans and classify it as declarative, procedural, strategic, or dispositional.
6. Generate candidate relations pairwise using multiple signals: definitional dependency, worked-example steps, exercise requirements, textbook order, semantic/context features, and existing standards.
7. Enforce graph invariants, but retain edge type, confidence, evidence, and dissent rather than collapsing immediately to a binary DAG.
8. Send uncertain/high-impact nodes and edges to a reviewer; use active-learning priority for cases where reviewer input most reduces uncertainty.
9. Generate or extract assessment items and build an explicit item-competency Q-matrix.
10. Publish a versioned graph, collect learner evidence, and periodically propose graph refinements for human approval.

## Sources

- 1EdTech Consortium. CASE v1.1 specification and information model (final, 2025-01-24): https://www.imsglobal.org/spec/case/v1p1/ and https://standards.1edtech.org/case/specifications/standards/v1p1/im
- 1EdTech Consortium. CASE 1.1 best-practice guide and association examples: https://standards.1edtech.org/case/guides/standards/v1p1/impl
- De Kuthy, Girrbach, and Meurers (2025). Automatic concept extraction for learning domain modeling: https://aclanthology.org/2025.bea-1.13/
- Han and Choi (2025). Beyond Linear Digital Reading: An LLM-Powered Concept Mapping Approach: https://aclanthology.org/2025.bea-1.58/
- Lu, Zhou, Yu, and Jia (2019). Concept Extraction and Prerequisite Relation Learning from Educational Data: https://doi.org/10.1609/aaai.v33i01.33019678
- Pan, Li, Li, and Tang (2017). Prerequisite Relation Learning for Concepts in MOOCs: https://aclanthology.org/P17-1133/
- Pal, Arora, and Goyal (2020). Finding Prerequisite Relations between Concepts using Textbook: https://arxiv.org/abs/2011.10337
- Roy, Madhyastha, Lawrence, and Rajan (2018). Inferring Concept Prerequisite Relations from Online Educational Resources: https://arxiv.org/abs/1811.12640
- Wang, Chau, Thaker, Brusilovsky, and He (2020). Concept Annotation for Intelligent Textbooks: https://arxiv.org/abs/2005.11422
- Sridhar et al. (2023). Harnessing LLMs in Curricular Design: https://arxiv.org/abs/2306.17459
- Mislevy/Haertel evidence-centered design, summarized and applied by Grover et al. (2021): https://www.frontiersin.org/journals/education/articles/10.3389/feduc.2021.695376/full
- Thompson and Nash (2022). A Diagnostic Framework for the Empirical Evaluation of Learning Maps: https://www.frontiersin.org/journals/education/articles/10.3389/feduc.2021.714736/full
- Attali and Attali (2019). Validating Classifications From Learning Progressions: https://www.ets.org/research/policy_research_reports/publications/report/2019/kabr.html
- Li and Suen (2013). Constructing and Validating a Q-Matrix for Cognitive Diagnostic Analyses of a Reading Test: https://eric.ed.gov/?id=EJ994673
- Pelanek (2024). Adaptive Learning is Hard: Challenges, Nuances, and Trade-offs in Modeling: https://link.springer.com/article/10.1007/s40593-024-00400-6
- Shi et al. (2023). KC-Finder: Automated Knowledge Component Discovery for Programming Problems: https://educationaldatamining.org/edm2023/proceedings/2023.EDM-long-papers.3/
- Pavlik, Cen, and Koedinger (2009). Performance Factors Analysis: https://doi.org/10.3233/978-1-60750-028-5-531
- Vu et al. (2025). A Bayesian Approach to Inferring Prerequisite Structures and Topic Difficulty in Language Learning: https://aclanthology.org/2025.bea-1.53/
- Columbia Business School. Learning Objectives and Bloom's Taxonomy: https://business.columbia.edu/samberg/teaching-strategies/learning-objectives-blooms-taxonomy

## Limits

- The strongest evidence supports hybrid authoring and validation, not universal zero-shot extraction of trustworthy competencies from arbitrary books.
- Results from one discipline or small evaluation should not be treated as domain-general accuracy guarantees.
- A book captures its author's instructional presentation, not necessarily all tacit procedural knowledge, misconceptions, alternative pathways, or authentic performance criteria in the domain.
- Psychometric validation requires enough learners, enough well-targeted items, and stable item-to-competency mappings; it cannot be completed at cold start.
