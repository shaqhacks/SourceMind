from __future__ import annotations

import uuid

from fastapi import Request, Response
from sqlalchemy.orm import Session

from app.db.models import CourseLearningProfile, LearnerProfile

LEARNER_COOKIE = "smv2_learner"
LEGACY_LOCAL_LEARNER_ID = "00000000-0000-0000-0000-000000000001"


def existing_learner_key(request: Request) -> str | None:
    raw_value = request.cookies.get(LEARNER_COOKIE)
    if raw_value is None:
        return None
    try:
        return str(uuid.UUID(raw_value))
    except (ValueError, AttributeError):
        return None


def ensure_learner_key(request: Request, response: Response) -> str:
    learner_key = existing_learner_key(request)
    if learner_key is not None:
        return learner_key

    learner_key = str(uuid.uuid4())
    response.set_cookie(
        LEARNER_COOKIE,
        learner_key,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
    )
    return learner_key


def ensure_course_learning_profile(
    session: Session, learner_id: str, course_id: str
) -> CourseLearningProfile:
    learner = session.get(LearnerProfile, learner_id)
    if learner is None:
        learner = LearnerProfile(id=learner_id)
        session.add(learner)
        session.flush()

    profile = (
        session.query(CourseLearningProfile)
        .filter_by(learner_id=learner_id, course_id=course_id)
        .one_or_none()
    )
    if profile is None:
        profile = CourseLearningProfile(learner_id=learner_id, course_id=course_id)
        session.add(profile)
        session.flush()
    return profile
