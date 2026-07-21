from scripts.ci_offline_smoke import run_offline_smoke


def test_offline_smoke_exercises_demo_policy_and_keyword_rag() -> None:
    result = run_offline_smoke()

    assert result["status"] == "ok"
    assert result["execution_mode"] == "demo"
    assert result["analysis_method"] == "demo_fixture"
    assert result["retrieval_method"] == "keyword_rrf"
    assert result["source_count"] >= 1
    assert result["external_socket_connect_attempts"] == 0
