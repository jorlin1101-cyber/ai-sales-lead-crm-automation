class KeywordEmbeddingProvider:
    """
    Demo-only embedding provider.

    This provider is deterministic and keyword-based.
    It validates the hybrid retrieval pipeline on real chunks,
    but it does not prove real semantic retrieval quality.
    """

    model_name = "keyword-demo-embedding-provider"

    def embed_text(self, text: str) -> list[float]:
        normalized_text = text.lower()

        return [
            self._contains_any(normalized_text, ["tibet", "tibetan", "西藏", "藏区"]),
            self._contains_any(normalized_text, ["yunnan", "云南"]),
            self._contains_any(
                normalized_text,
                ["western_sichuan", "western sichuan", "川西"],
            ),
            self._contains_any(
                normalized_text,
                [
                    "pricing",
                    "quotation",
                    "payment",
                    "price",
                    "cost",
                    "costs",
                    "quote",
                    "budget",
                    "deposit",
                    "balance",
                    "报价",
                    "付款",
                    "价格",
                 ],
            ),
            self._contains_any(
                normalized_text,
                [
                    "family",
                    "families",
                    "children",
                    "child",
                    "kids",
                    "kid",
                    "家庭",
                    "亲子",
                ],
            ),
            self._contains_any(
                normalized_text,
                [
                    "culture",
                    "cultural",
                    "monastery",
                    "local",
                    "experience",
                    "experiences",
                    "meaningful",
                    "文化",
                    "寺院",
                    "当地",
                ],
            ),
            self._contains_any(
                normalized_text,
                [
                    "private",
                    "custom",
                    "customized",
                    "customised",
                    "tailor-made",
                    "bespoke",
                    "定制",
                    "私人",
                ],
            ),
        ]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_text(text) for text in texts]

    @staticmethod
    def _contains_any(text: str, keywords: list[str]) -> float:
        return 1.0 if any(keyword in text for keyword in keywords) else 0.0
