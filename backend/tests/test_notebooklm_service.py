from SourceMind.backend.services.notebooklm_service import NotebookLMService


def test_quote_candidates_chunk_selectable_text_without_sentence_punctuation() -> None:
    service = NotebookLMService()
    text = (
        "Place value helps students understand how digits represent different quantities in a number "
        "Regrouping connects addition procedures to the structure of tens and ones "
        "Students should explain each step before applying the procedure to larger numbers"
    )

    candidates = service._quote_candidates([(1, text)])

    assert candidates
    assert candidates[0]["page"] == 1
    assert "Place value helps students" in candidates[0]["text"]


def test_fallback_competencies_do_not_create_ungrounded_extra_competencies() -> None:
    service = NotebookLMService()

    one_quote = service._fallback_competencies(["addition"], 1)
    two_quotes = service._fallback_competencies(["addition"], 2)
    three_quotes = service._fallback_competencies(["addition"], 3)

    assert [item.id for item in one_quote] == ["L1_1"]
    assert [item.id for item in two_quotes] == ["L1_1", "L2_1"]
    assert [item.id for item in three_quotes] == ["L1_1", "L1_2", "L2_1"]


def test_quote_candidates_filter_pdf_front_matter_and_keep_source_refs() -> None:
    service = NotebookLMService()

    candidates = service._quote_candidates(
        [
            (
                "wallace.pdf",
                1,
                "Beginning and Intermediate Algebra An open source textbook Available for free download at: http://wallace.ccfaculty.org/book/book.html",
            ),
            (
                "wallace.pdf",
                8,
                "An equation is a mathematical statement that two expressions are equal.",
            ),
        ]
    )

    assert candidates
    assert candidates[0]["text"] == "An equation is a mathematical statement that two expressions are equal."
    assert candidates[0]["source_ref"] == "wallace.pdf p. 8"
    assert all("free download" not in candidate["text"].lower() for candidate in candidates)
    assert service._is_low_value_text(
        "Where the work or any of its elements is in the p ublic domain under applicable law."
    )


def test_fallback_competency_titles_are_instructional_not_filename_noise() -> None:
    service = NotebookLMService()

    competencies = service._fallback_competencies(["rights", "wallace", "algebra"], 3)

    assert [item.name for item in competencies] == [
        "Core Algebra Concepts",
        "Algebra Procedures and Examples",
        "Apply Algebra to New Problems",
    ]
