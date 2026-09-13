import asyncio
import hashlib
import hmac
import os
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import storage
from app.agents import ExamExecutor
from app.contracts import AgentJob, ApprovalInput, RunInput, SlotInput
from app.models import mode
from app.tools_client import hospital_tools

RUNS = {}
ACTIVE = {}
LOCKS = {}
RATE = {}
SECRET = os.getenv("INTERNAL_SECRET", secrets.token_hex(32))
TERMINAL = {
    "needs_input",
    "no_slots",
    "awaiting_approval",
    "confirmation_unknown",
    "confirmed",
    "conflict",
    "failed",
    "cancelled",
}
PORT = os.getenv("PORT", "8080")


@asynccontextmanager
async def lifespan(app):
    yield
    tasks = list(ACTIVE.values())
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(title="ExamFlow", lifespan=lifespan, docs_url=None, redoc_url=None)


def sign(sid):
    return sid + "." + hmac.new(SECRET.encode(), sid.encode(), hashlib.sha256).hexdigest()


@app.middleware("http")
async def boundary(request: Request, call_next):
    if request.url.path.startswith("/a2a/") and not request.url.path.endswith("agent-card.json"):
        if not hmac.compare_digest(request.headers.get("x-internal-secret", ""), SECRET):
            return JSONResponse({"detail": "내부 에이전트 통신 전용"}, status_code=403)
    if request.method in {"POST", "PUT", "DELETE"} and not request.url.path.startswith("/a2a/"):
        origin = request.headers.get("origin")
        if origin:
            from urllib.parse import urlparse

            if urlparse(origin).netloc != request.headers.get("host"):
                return JSONResponse({"detail": "다른 출처의 요청 차단"}, status_code=403)
        try:
            if int(request.headers.get("content-length", "0")) > 8192:
                return JSONResponse({"detail": "요청 크기 초과"}, status_code=413)
        except ValueError:
            return JSONResponse({"detail": "잘못된 요청"}, status_code=400)
    cookie = request.cookies.get("examflow_session", "")
    sid = cookie.split(".")[0]
    if len(sid) != 32 or not hmac.compare_digest(cookie, sign(sid)):
        sid = secrets.token_hex(16)
    request.state.session_id = sid
    response = await call_next(request)
    if cookie != sign(sid):
        response.set_cookie(
            "examflow_session",
            sign(sid),
            httponly=True,
            samesite="lax",
            secure=os.getenv("COOKIE_SECURE", "false") == "true",
            max_age=86400,
        )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
    )
    return response


def event_sink(run_id, agent):
    def emit(kind, label, data):
        run = RUNS.get(run_id)
        if run and run["state"] != "cancelled":
            run["events"].append(
                {
                    "seq": len(run["events"]) + 1,
                    "at_ms": round((time.monotonic() - run["started"]) * 1000),
                    "kind": kind,
                    "agent": agent,
                    "label": label,
                    "data": data,
                }
            )

    return emit


def card(name):
    return AgentCard(
        name=f"ExamFlow {name}",
        description="합성 검사 예약 행정 담당 에이전트",
        url=f"{os.getenv('PUBLIC_BASE_URL', f'http://127.0.0.1:{PORT}')}/a2a/{name}/",
        version="1.0.0",
        capabilities=AgentCapabilities(streaming=False),
        default_input_modes=["text"],
        default_output_modes=["application/json"],
        skills=[
            AgentSkill(
                id=name,
                name=name,
                description="준비 확인" if name == "readiness" else "일정 조정",
                tags=["hospital", "synthetic"],
            )
        ],
    )


class BoundedTaskStore(InMemoryTaskStore):
    """SDK Task 보관도 제한해 장시간 공개 데모의 메모리 증가를 막는다."""

    async def save(self, task, context=None):
        async with self.lock:
            if task.id not in self.tasks and len(self.tasks) >= 512:
                for task_id, previous in list(self.tasks.items()):
                    if previous.status.state.value in {
                        "completed",
                        "failed",
                        "canceled",
                        "input-required",
                    }:
                        del self.tasks[task_id]
                        break
            self.tasks[task.id] = task


for agent_name in ("readiness", "scheduling"):
    handler = DefaultRequestHandler(ExamExecutor(agent_name, event_sink), BoundedTaskStore())
    app.mount(
        f"/a2a/{agent_name}",
        A2AStarletteApplication(card(agent_name), handler, max_content_length=8192).build(),
    )


async def call_agent(name, job):
    emit = event_sink(job.run_id, "orchestrator")
    emit(
        "a2a.send",
        name,
        {"method": "message/send", "protocol": "A2A 0.3", "order_id": job.order_id},
    )
    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "message/send",
        "params": {
            "message": {
                "messageId": str(uuid.uuid4()),
                "role": "user",
                "parts": [{"kind": "text", "text": job.model_dump_json()}],
            }
        },
    }
    async with httpx.AsyncClient(timeout=100) as client:
        response = await client.post(
            f"http://127.0.0.1:{PORT}/a2a/{name}/",
            json=payload,
            headers={"x-internal-secret": SECRET},
        )
        response.raise_for_status()
        envelope = response.json()
    if "error" in envelope:
        raise RuntimeError("A2A 프로토콜 오류")
    result = envelope["result"]
    state = result["status"]["state"]
    emit("a2a.receive", name, {"task_id": result["id"], "state": state})
    if state not in {"completed", "input-required"}:
        raise RuntimeError("에이전트 처리 실패")
    return result["artifacts"][0]["parts"][0]["data"]


async def execute_run(run_id):
    run = RUNS[run_id]
    job = AgentJob(run_id=run_id, session_id=run["owner"], **run["input"])
    try:
        async with asyncio.timeout(180):
            run["state"] = "checking"
            prepared = await call_agent("readiness", job)
            if run["state"] == "cancelled":
                return
            run["readiness"] = prepared
            if not prepared["decision"]["ready"]:
                run["state"] = "needs_input"
                return
            run["state"] = "scheduling"
            job.preference = prepared["decision"]["preference"]
            scheduled = await call_agent("scheduling", job)
            if run["state"] == "cancelled":
                return
            run["schedule"] = scheduled
            run["state"] = "awaiting_approval" if scheduled["selected"] else "no_slots"
    except asyncio.CancelledError:
        run["state"] = "cancelled"
    except Exception as exc:
        if run["state"] != "cancelled":
            run["state"] = "failed"
            run["error"] = (
                "도구 또는 모델 요청을 완료하지 못했습니다. 연결·할당량을 확인한 뒤 새 요청으로 재시도하세요."
            )
            event_sink(run_id, "orchestrator")(
                "run.failed", "처리 실패", {"error_type": type(exc).__name__}
            )
    finally:
        ACTIVE.pop(run_id, None)


def owned(run_id, request):
    run = RUNS.get(run_id)
    if not run or run["owner"] != request.state.session_id:
        raise HTTPException(
            404, "실행을 찾을 수 없습니다. 세션이 만료되었으면 새 요청을 시작하세요."
        )
    if storage.is_reservation_cancelled(request.state.session_id, run_id):
        run["state"] = "cancelled"
        run["reservation"] = {"status": "cancelled", "reason": "예약 현황에서 취소한 예약입니다."}
    return run


def public(run):
    return {k: v for k, v in run.items() if k not in {"owner", "started"}}


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "model_mode": mode(),
        "synthetic_data": True,
        "version": "1.0.0",
    }


@app.get("/api/workspace")
def get_workspace(request: Request):
    return storage.workspace(request.state.session_id)


@app.post("/api/slots", status_code=201)
def create_slot(body: SlotInput, request: Request):
    try:
        storage.edit_slot(request.state.session_id, body.model_dump(exclude={"version"}))
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return storage.workspace(request.state.session_id)


@app.put("/api/slots/{slot_id}")
def update_slot(slot_id: str, body: SlotInput, request: Request):
    try:
        storage.edit_slot(
            request.state.session_id, body.model_dump(exclude={"version"}), slot_id, body.version
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return storage.workspace(request.state.session_id)


@app.post("/api/reservations/{run_id}/cancel")
async def cancel_booking(run_id: str, request: Request):
    # 승인과 관리 화면의 취소도 같은 실행 잠금을 사용한다.
    lock = LOCKS.get(run_id, asyncio.Lock())
    async with lock:
        try:
            storage.cancel_reservation(request.state.session_id, run_id)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
    return storage.workspace(request.state.session_id)


@app.post("/api/runs", status_code=202)
async def create_run(body: RunInput, request: Request):
    now = time.monotonic()
    for rid, run in list(RUNS.items()):
        if now - run["started"] > 3600 and rid not in ACTIVE:
            RUNS.pop(rid, None)
            LOCKS.pop(rid, None)
    sid = request.state.session_id
    for old_sid, timestamps in list(RATE.items()):
        if not timestamps or now - timestamps[-1] >= 3600:
            RATE.pop(old_sid, None)
    RATE[sid] = [t for t in RATE.get(sid, []) if now - t < 3600]
    if len(RATE[sid]) >= 20 or len(ACTIVE) >= 4 or len(RUNS) >= 200:
        raise HTTPException(429, "실행 한도에 도달했습니다. 잠시 후 다시 시도하세요.")
    RATE[sid].append(now)
    rid = str(uuid.uuid4())
    RUNS[rid] = {
        "id": rid,
        "owner": sid,
        "input": body.model_dump(),
        "state": "queued",
        "events": [],
        "started": now,
        "version": 1,
        "model_mode": mode(),
    }
    LOCKS[rid] = asyncio.Lock()
    ACTIVE[rid] = asyncio.create_task(execute_run(rid))
    return public(RUNS[rid])


@app.get("/api/runs/{run_id}")
def get_run(run_id: str, request: Request):
    return public(owned(run_id, request))


@app.post("/api/runs/{run_id}/approve")
async def approve(run_id: str, body: ApprovalInput, request: Request):
    run = owned(run_id, request)
    async with LOCKS[run_id]:
        if run["state"] == "confirmed":
            return public(run)
        if (
            run["state"] not in {"awaiting_approval", "confirmation_unknown"}
            or body.version != run["version"]
        ):
            raise HTTPException(409, "현재 상태에서는 확정할 수 없습니다.")
        if run["state"] == "awaiting_approval" and time.monotonic() - run["started"] > 900:
            raise HTTPException(409, "예약안이 만료되었습니다. 새 요청으로 시간을 조회하세요.")
        run["state"] = "confirming"
        emit = event_sink(run_id, "approval")
        emit("approval.received", "사용자 승인", {"version": body.version})
        try:
            async with hospital_tools(emit) as call:
                result = await call(
                    "reserve_demo_slot",
                    {
                        "session_id": run["owner"],
                        "order_id": run["input"]["order_id"],
                        "slot_id": run["schedule"]["selected"]["id"],
                        "run_id": run_id,
                        "expected_version": run["schedule"]["selected"].get("version", 1),
                    },
                )
            run["reservation"] = result
            run["state"] = result["status"]
            run.pop("error", None)
        except Exception:
            run["state"] = "confirmation_unknown"
            run["error"] = (
                "확정 응답을 확인하지 못했습니다. '확정 결과 재확인'을 누르면 같은 실행 번호로 중복 없이 재확인합니다."
            )
        return public(run)


@app.post("/api/runs/{run_id}/cancel")
async def cancel(run_id: str, request: Request):
    run = owned(run_id, request)
    async with LOCKS[run_id]:
        if run["state"] in {"confirmed", "confirming", "confirmation_unknown"}:
            raise HTTPException(409, "확정된 예약은 예약 현황에서 취소하세요.")
        event_sink(run_id, "user")("run.cancelled", "사용자 취소", {})
        run["state"] = "cancelled"
    return public(run)


app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(Path(__file__).parent / "static/index.html")
