"""공개 서비스의 예약 풀 편집과 실제 모델 연동을 검증한다."""

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--output", default=".tmp/operations-verification.json")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    checks = []
    with httpx.Client(base_url=base, timeout=60) as client:

        def call(method, path, **kwargs):
            response = client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()

        assert call("GET", "/api/health")["model_mode"] == "gemini"
        workspace = call("GET", "/api/workspace")
        slot = next(s for s in workspace["slots"] if s["id"] == "CT-PM")
        body = {k: slot[k] for k in ("exam", "day", "time", "room", "enabled", "version")}
        body["time"] = "14:30"
        call("PUT", "/api/slots/CT-PM", json=body)
        checks.append("시간표 14:30 편집")
        run = call("POST", "/api/runs", json={"order_id": "EX-1001", "request": "오후 검사 예약"})
        rid = run["id"]
        for _ in range(190):
            run = call("GET", f"/api/runs/{rid}")
            if run["state"] not in {"queued", "checking", "scheduling"}:
                break
            time.sleep(1)
        assert run["state"] == "awaiting_approval", run["state"]
        assert run["schedule"]["selected"]["time"] == "14:30"
        assert len([e for e in run["events"] if e["kind"] == "a2a.receive"]) == 2
        checks.append("실제 Gemini + A2A + MCP로 변경 시간 제안")
        approved = call("POST", f"/api/runs/{rid}/approve", json={"version": run["version"]})
        assert approved["state"] == "confirmed"
        workspace = call("GET", "/api/workspace")
        assert any(r["id"] == rid and r["status"] == "confirmed" for r in workspace["reservations"])
        assert next(s for s in workspace["slots"] if s["id"] == "CT-PM")["status"] == "booked"
        checks.append("확정 예약과 점유 시간 조회")
        body["version"] += 1
        assert client.put("/api/slots/CT-PM", json=body).status_code == 409
        with httpx.Client(base_url=base, timeout=60) as other:
            assert other.post(f"/api/reservations/{rid}/cancel").status_code == 404
            assert not other.get("/api/workspace").json()["reservations"]
        checks.append("예약된 시간 편집 차단과 세션 격리")
        call("POST", f"/api/reservations/{rid}/cancel")
        call("POST", f"/api/reservations/{rid}/cancel")
        workspace = call("GET", "/api/workspace")
        assert next(s for s in workspace["slots"] if s["id"] == "CT-PM")["status"] == "available"
        assert any(r["id"] == rid and r["status"] == "cancelled" for r in workspace["reservations"])
        assert call("GET", f"/api/runs/{rid}")["state"] == "cancelled"
        assert (
            client.post(f"/api/runs/{rid}/approve", json={"version": run["version"]}).status_code
            == 409
        )
        checks.append("취소 멱등·시간 재개방·과거 승인 차단")
        body["time"] = "14:45"
        call("PUT", "/api/slots/CT-PM", json=body)
        workspace = call("GET", "/api/workspace")
        assert (
            next(r for r in workspace["reservations"] if r["id"] == rid)["slot"]["time"] == "14:30"
        )
        checks.append("시간 재편집 이후 취소 당시 시간 보존")
    result = {
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base,
        "model_mode": "gemini",
        "result": "passed",
        "checks": checks,
    }
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
