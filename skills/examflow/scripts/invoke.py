import argparse
import json
import sys
import time

import httpx


def main():
    parser = argparse.ArgumentParser(description="ExamFlow 합성 예약 에이전트 호출")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--order", choices=["EX-1001", "EX-1002", "EX-1003"], default="EX-1001")
    parser.add_argument("--request", default="가능한 검사 예약 시간을 찾아주세요.")
    parser.add_argument("--approve", action="store_true", help="명시적으로 승인된 데모 예약안 확정")
    args = parser.parse_args()
    with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=45) as c:
        health = c.get("/api/health")
        health.raise_for_status()
        print(json.dumps({"environment": health.json()}, ensure_ascii=False), flush=True)
        r = c.post("/api/runs", json={"order_id": args.order, "request": args.request})
        r.raise_for_status()
        rid = r.json()["id"]
        for _ in range(190):
            r = c.get("/api/runs/" + rid)
            r.raise_for_status()
            run = r.json()
            if run["state"] not in {"queued", "checking", "scheduling"}:
                break
            time.sleep(1)
        else:
            raise TimeoutError("처리 시간 초과. 서버에서 실행 상태를 확인하세요.")
        print(json.dumps(run, ensure_ascii=False, indent=2), flush=True)
        if args.approve and run["state"] == "awaiting_approval":
            r = c.post("/api/runs/" + rid + "/approve", json={"version": run["version"]})
            r.raise_for_status()
            run = r.json()
            print(json.dumps({"approval": run}, ensure_ascii=False, indent=2))
        return 1 if run["state"] in {"failed", "conflict", "confirmation_unknown"} else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (httpx.HTTPError, ValueError, TimeoutError) as exc:
        print(f"실행 실패: {exc}", file=sys.stderr)
        sys.exit(1)
