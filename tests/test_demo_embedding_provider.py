from lead_cleaner.rag.demo_embedding_provider import KeywordEmbeddingProvider


def test_keyword_embedding_provider_returns_seven_dimensions() -> None:
    provider = KeywordEmbeddingProvider()

    vector = provider.embed_text("Yunnan family travel")

    assert len(vector) == 7


def test_keyword_embedding_provider_matches_yunnan_and_family() -> None:
    provider = KeywordEmbeddingProvider()

    vector = provider.embed_text("Yunnan family travel")

    assert vector == [0.0, 1.0, 0.0, 0.0, 1.0, 0.0, 0.0]


def test_keyword_embedding_provider_matches_tibet_pricing_and_private_intent() -> None:
    provider = KeywordEmbeddingProvider()

    vector = provider.embed_text("Tibet private customized tour cost")

    assert vector == [1.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0]


def test_keyword_embedding_provider_matches_private_custom_intent() -> None:
    provider = KeywordEmbeddingProvider()

    vector = provider.embed_text("private customized tour")

    assert vector == [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0]


def test_keyword_embedding_provider_matches_family_children_intent() -> None:
    provider = KeywordEmbeddingProvider()

    vector = provider.embed_text("families with children")

    assert vector == [0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0]


def test_keyword_embedding_provider_matches_cultural_experience_intent() -> None:
    provider = KeywordEmbeddingProvider()

    vector = provider.embed_text("meaningful cultural experiences with local monasteries")

    assert vector == [0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0]


def test_keyword_embedding_provider_embeds_multiple_texts() -> None:
    provider = KeywordEmbeddingProvider()

    vectors = provider.embed_texts(
        [
            "Tibet permit payment",
            "Western Sichuan private quotation",
        ]
    )

    assert len(vectors) == 2
    assert all(len(vector) == 7 for vector in vectors)
