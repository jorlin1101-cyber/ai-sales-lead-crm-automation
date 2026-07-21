import json
import socket
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from lead_cleaner.api.main import create_app
from lead_cleaner.config import AppMode, RagBackend, Settings


SAFE_DEMO_PAYLOAD = {
    "external_lead_id": "sample-lead-001",
    "name": "Demo Lead",
    "email": "demo@example.com",
    "company_name": "Example Travel Agency",
    "message": "We need a private Chengdu tour in September.",
    "source": "Offline CI",
}
_ORIGINAL_SOCKET_CONNECT = socket.socket.connect


def _block_external_socket_connect(sock, address):
    host = address[0] if isinstance(address, tuple) and address else None
    if host in {"127.0.0.1", "::1", "localhost"}:
        return _ORIGINAL_SOCKET_CONNECT(sock, address)
    raise AssertionError(f"Offline smoke attempted an external socket connection to {host!r}.")


def run_offline_smoke() -> dict[str, object]:
    settings = Settings(
        _env_file=None,
        app_mode=AppMode.DEMO,
        allow_network=False,
        rag_backend=RagBackend.KEYWORD_RRF,
        rag_required=True,
        demo_feature_fixtures_path=Path("data/demo/lead_feature_fixtures.json"),
        knowledge_chunks_path=Path("data/knowledge_snapshot/knowledge_chunks.json"),
    )

    with patch.object(socket.socket, "connect", _block_external_socket_connect):
        with TestClient(create_app(settings=settings)) as client:
            response = client.post(
                "/process-lead",
                json=SAFE_DEMO_PAYLOAD,
                headers={"X-Request-ID": "ci-offline-smoke"},
            )

    if response.status_code != 200:
        raise RuntimeError(f"Offline smoke returned HTTP {response.status_code}.")
    payload = response.json()
    if payload["validation_result"]["is_valid"] is not True:
        raise RuntimeError("Offline smoke lead did not pass domain validation.")
    analysis = payload.get("analysis_result")
    if not isinstance(analysis, dict):
        raise RuntimeError("Offline smoke did not return an analysis result.")
    metadata = analysis.get("metadata", {})
    decision = analysis.get("decision", {})
    if metadata.get("execution_mode") != "demo":
        raise RuntimeError("Offline smoke did not use demo execution mode.")
    if metadata.get("analysis_method") != "demo_fixture":
        raise RuntimeError("Offline smoke did not use the deterministic fixture.")
    if metadata.get("retrieval_method") != "keyword_rrf":
        raise RuntimeError("Offline smoke did not use the keyword RAG backend.")
    if not decision.get("policy_version"):
        raise RuntimeError("Offline smoke did not return a policy version.")
    sources = payload.get("sources")
    if not isinstance(sources, list) or not sources:
        raise RuntimeError("Offline smoke did not return sanitized RAG sources.")
    if response.headers.get("X-Request-ID") != "ci-offline-smoke":
        raise RuntimeError("Offline smoke did not preserve its request ID.")

    return {
        "status": "ok",
        "execution_mode": metadata["execution_mode"],
        "analysis_method": metadata["analysis_method"],
        "retrieval_method": metadata["retrieval_method"],
        "policy_version": decision["policy_version"],
        "source_count": len(sources),
        "external_socket_connect_attempts": 0,
    }


def main() -> None:
    print(json.dumps(run_offline_smoke(), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
