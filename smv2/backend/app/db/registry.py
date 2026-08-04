"""Registry of which tables get wiped vs. remapped vs. kept on re-ingest.

Every ORM model with a foreign key to courses.id or sections.id must appear
in exactly one of REPLACED_ON_REINGEST, REMAPPED_ON_REINGEST, or
LEDGER_TABLES — enforced by test_derived_tables_registry_covers_all_fk_models
in tests/test_architecture.py. Forgetting to register a new FK-bearing table
here is exactly the "re-ingest silently orphans/duplicates rows" bug class
this project has been burned by before.
"""

from __future__ import annotations

from app.db.models import (
    Asset,
    Card,
    ChatTurn,
    Chunk,
    Concept,
    ConceptEdge,
    ConceptMastery,
    ConceptMasteryEvent,
    ConceptRelation,
    ConceptRevision,
    ConceptSectionLink,
    ConceptSourceLink,
    CourseLearningProfile,
    CurriculumVersion,
    DiagnosticJudgment,
    EvidenceItem,
    EvidenceItemConceptLink,
    Highlight,
    LlmCall,
    LearningClaim,
    LearningClaimRevision,
    LearnerConceptState,
    LearnerEvidenceEvent,
    Note,
    PracticeAnswer,
    PracticeExtractionRun,
    PracticeQuestion,
    ProgressState,
    ReviewLog,
    ReviewState,
    RetentionAssignment,
    RetentionProbe,
    RetentionStudy,
    Section,
    ShadowLearnerPrediction,
    Test,
    TestAttempt,
)

# Deleted and regenerated wholesale every time a course is re-ingested.
REPLACED_ON_REINGEST = [
    Asset,
    Section,
    Chunk,
    Card,
    ChatTurn,
    Highlight,
    Note,
    Test,
    TestAttempt,
    PracticeAnswer,
    ConceptMasteryEvent,
    ConceptMastery,
    PracticeQuestion,
    PracticeExtractionRun,
    ConceptEdge,
    ConceptSectionLink,
]

# Survive re-ingest by remapping onto the new content-addressed ids (spaced
# repetition history must not reset just because the PDF was re-uploaded).
REMAPPED_ON_REINGEST = [
    CourseLearningProfile,
    ReviewState,
    ReviewLog,
    ProgressState,
    Concept,
    CurriculumVersion,
    ConceptRevision,
    LearningClaim,
    LearningClaimRevision,
    ConceptRelation,
    ConceptSourceLink,
    EvidenceItem,
    EvidenceItemConceptLink,
    LearnerEvidenceEvent,
    LearnerConceptState,
    ShadowLearnerPrediction,
    DiagnosticJudgment,
    RetentionStudy,
    RetentionAssignment,
    RetentionProbe,
]

# Append-only audit log — neither wiped nor remapped, and course_id is
# nullable via ON DELETE SET NULL so a deleted course doesn't erase spend
# history.
LEDGER_TABLES = [LlmCall]
