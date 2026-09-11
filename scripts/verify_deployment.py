"""공개 데모의 합성 사례와 프로토콜 경계를 검증한다."""

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--output", default=".tmp/deployment-verification.json")
    args = parser.parse_args()
    results = []
    with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=60) as client:
        health = client.get("/api/health")
        health.raise_for_status()
        assert health.json()["model_mode"] == "gemini", health.text
        for agent in ("readiness", "scheduling"):
            response = client.get(f"/a2a/{agent}/.well-known/agent-card.json")
            response.raise_for_status()
            assert response.json()["protocolVersion"] == "0.3.0"
            assert response.json()["url"].startswith(args.base_url)
        for order, expected in (
            ("EX-1001", "awaiting_approval"),
            ("EX-1002", "needs_input"),
            ("EX-1003", "no_slots"),
        ):
            response = client.post(
                "/api/runs", json={"order_id": order, "request": "오후 검사 예약"}
            )
            response.raise_for_status()
            rid = response.json()["id"]
            for _ in range(190):
                response = client.get(f"/api/runs/{rid}")
                response.raise_for_status()
                run = response.json()
                if run["state"] not in {"queued", "checking", "scheduling"}:
                    break
                time.sleep(1)
            assert run["state"] == expected, run
            assert run["model_mode"] == "gemini"
            receives = [e for e in run["events"] if e["kind"] == "a2a.receive"]
            assert len(receives) == (1 if order == "EX-1002" else 2)
            with httpx.Client(base_url=args.base_url, timeout=60) as stranger:
                assert stranger.get(f"/api/runs/{rid}").status_code == 404
            result = {
                "order_id": order,
                "expected": expected,
                "actual": run["state"],
                "a2a_responses": len(receives),
                "session_isolation": "passed",
            }
            if order == "EX-1001":
                assert run["schedule"]["selected"]["id"] == "CT-PM"
                approved = client.post(f"/api/runs/{rid}/approve", json={"version": run["version"]})
                approved.raise_for_status()
                repeated = client.post(f"/api/runs/{rid}/approve", json={"version": run["version"]})
                repeated.raise_for_status()
                assert approved.json()["state"] == "confirmed"
                assert approved.json()["reservation"] == repeated.json()["reservation"]
                result.update(approval="confirmed", idempotency="passed")
            results.append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
        assert client.post("/a2a/readiness", json={}).status_code == 403
    evidence = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "base_url": args.base_url,
        "model_mode": "gemini",
        "agent_cards": "passed",
        "internal_endpoint_protection": "passed",
        "scenarios": results,
    }
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
