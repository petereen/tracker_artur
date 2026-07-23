from app.services.knowledge_service import rank_knowledge, tokenize_search_terms


ENTRIES = [
    {
        "id": 1,
        "title": "Annual leave policy",
        "category": "HR",
        "content": "Employees request annual leave through their manager.",
        "is_active": True,
    },
    {
        "id": 2,
        "title": "Security",
        "category": "IT",
        "content": "Never share a password. Use the approved password manager.",
        "is_active": True,
    },
    {
        "id": 3,
        "title": "Old leave policy",
        "category": "HR",
        "content": "This entry is inactive.",
        "is_active": False,
    },
]


def test_rank_knowledge_prefers_title_matches_and_excludes_inactive():
    result = rank_knowledge(ENTRIES, ["leave policy"])
    assert [entry["id"] for entry in result] == [1]


def test_rank_knowledge_returns_only_relevant_entries():
    result = rank_knowledge(ENTRIES, ["password"])
    assert [entry["id"] for entry in result] == [2]


def test_rank_knowledge_handles_mongolian_word_suffixes():
    entries = [
        {
            "id": 4,
            "title": "Амралт",
            "category": "HR",
            "content": "Жилийн амралтын журам.",
            "is_active": True,
        }
    ]
    assert [entry["id"] for entry in rank_knowledge(entries, ["амралтын"])] == [4]


def test_rank_knowledge_respects_context_budget():
    entries = [
        {
            "id": 1,
            "title": "Policy",
            "category": None,
            "content": "policy " * 100,
            "is_active": True,
        }
    ]
    result = rank_knowledge(entries, ["policy"], max_chars=25)
    assert len(result[0]["content"]) == 25


def test_tokenize_search_terms_deduplicates_and_removes_stop_words():
    assert tokenize_search_terms(["What is the leave leave policy?"]) == ["leave", "policy"]


def test_no_terms_does_not_leak_unrelated_knowledge():
    assert rank_knowledge(ENTRIES, []) == []
