from __future__ import annotations

from app.db.identity import card_id_for, content_hash_for, normalize_text, section_id_for


def test_section_id_is_stable_across_calls():
    text = normalize_text("# Heading\n\nSome body text.\n")
    id1 = section_id_for("course-1", text, occurrence=0)
    id2 = section_id_for("course-1", text, occurrence=0)
    assert id1 == id2
    assert len(id1) == 24


def test_section_id_occurrence_disambiguates_duplicates():
    text = normalize_text("Exercises\n")
    first = section_id_for("course-1", text, occurrence=0)
    second = section_id_for("course-1", text, occurrence=1)
    assert first != second


def test_normalize_text_ignores_whitespace_only_edits():
    a = normalize_text("Line one.   \nLine two.\n\n\n\nLine three.\n")
    b = normalize_text("Line one.\nLine two.\n\nLine three.")
    assert a == b
    assert section_id_for("course-1", a, occurrence=0) == section_id_for("course-1", b, occurrence=0)


def test_content_hash_is_pure_sha256_of_normalized_body():
    text = normalize_text("Body text.\n")
    assert content_hash_for(text) == content_hash_for(text)
    assert len(content_hash_for(text)) == 64
    # Pure hash of the text only — no course/occurrence mixed in like section ids.
    assert content_hash_for(text) != section_id_for("course-1", text, occurrence=0)


def test_card_id_is_stable_and_distinguishes_front_back():
    section_id = "abc123"
    id1 = card_id_for(section_id, "Front?", "Back.")
    id2 = card_id_for(section_id, "Front?", "Back.")
    assert id1 == id2
    assert len(id1) == 24
    assert card_id_for(section_id, "Front?", "Different back.") != id1
