"""예약안을 저장하고 별도 승인 호출에서도 동일 세션과 실행을 유지한다."""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx


def save(path, state, *, exclusive=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | (os.O_EXCL if exclusive else os.O_TRUNC)
    with os.fdopen(os.open(path, flags, 0o600), "w", encoding="utf-8") as file:
        json.dump(state, file, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--order", choices=["EX-1001", "EX-1002", "EX-1003"], default="EX-1001")
    parser.add_argument("--request", default="가능한 검사 예약 시간을 찾아주세요.")
    parser.add_argument("--state-file", type=Path, default=Path(".tmp/examflow-session.json"))
    parser.add_argument("--resume", action="store_true", help="저장된 실행 조회; 새 요청 미생성")
    parser.add_argument("--approve", action="store_true", help="--resume과 함께 확인한 예약안 승인")
    args = parser.parse_args()
    if args.approve and not args.resume:
        parser.error("먼저 예약안을 조회한 뒤 --resume --approve로 동일 실행을 승인하세요.")
    base = args.base_url.rstrip("/")
    if args.resume:
        state = json.loads(args.state_file.read_text(encoding="utf-8"))
        if state["base_url"] != base:
            raise ValueError("저장된 서비스 URL과 다릅니다. 세션을 다른 서버로 전송하지 않습니다.")
    else:
        state = {"base_url": base}
        # 기존 예약안의 세션을 덮어쓰지 않는다. 파일 이름을 달리해 새 요청을 만든다.
        save(args.state_file, state, exclusive=True)
    with httpx.Client(base_url=base, timeout=45) as client:
        if args.resume:
            client.cookies.set("examflow_session", state["session_cookie"])
        health = client.get("/api/health")
        health.raise_for_status()
        print(json.dumps({"environment": health.json()}, ensure_ascii=False), flush=True)
        if not args.resume:
            response = client.post(
                "/api/runs", json={"order_id": args.order, "request": args.request}
            )
            response.raise_for_status()
            state.update(
                run_id=response.json()["id"], session_cookie=client.cookies.get("examflow_session")
            )
            save(args.state_file, state)
        rid = state["run_id"]
        deadline = time.monotonic() + 190
        while True:
            response = client.get("/api/runs/" + rid)
            response.raise_for_status()
            run = response.json()
            if run["state"] not in {"queued", "checking", "scheduling", "confirming"}:
                break
            if time.monotonic() >= deadline:
                raise TimeoutError("처리 시간 초과. 같은 상태 파일로 --resume 하세요.")
            time.sleep(1)
        print(json.dumps(run, ensure_ascii=False, indent=2), flush=True)
        if args.approve:
            if run["state"] not in {"awaiting_approval", "confirmation_unknown", "confirmed"}:
                raise ValueError("저장된 실행은 승인 가능한 상태가 아닙니다.")
            response = client.post(f"/api/runs/{rid}/approve", json={"version": run["version"]})
            response.raise_for_status()
            run = response.json()
            print(json.dumps({"approval": run}, ensure_ascii=False, indent=2))
        return 1 if run["state"] in {"failed", "conflict", "confirmation_unknown"} else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (httpx.HTTPError, ValueError, KeyError, OSError, TimeoutError) as exc:
        print(f"실행 실패: {exc}", file=sys.stderr)
        sys.exit(1)
