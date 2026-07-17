from lead_cleaner.rag.bge_embedding_provider import BgeM3EmbeddingProvider


def main() -> None:
    provider = BgeM3EmbeddingProvider()

    text = "Is Yunnan good for families with children?"
    vector = provider.embed_text(text)

    print(f"Model: {provider.model_name}")
    print(f"Vector dimension: {len(vector)}")
    print(f"First 5 values: {vector[:5]}")


if __name__ == "__main__":
    main()
