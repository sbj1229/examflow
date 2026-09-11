from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import DataPart, Part, TaskState
from a2a.utils import new_agent_text_message, new_task

from app.catalog import FIELD_LABELS
from app.contracts import AgentJob, ReadinessDecision, ScheduleDecision
from app.models import READINESS_PROMPT, SCHEDULE_PROMPT, decide
from app.tools_client import hospital_tools


async def readiness(job, emit):
    async with hospital_tools(emit) as call:
        order = await call("get_order", {"order_id": job.order_id})
        policy = await call("get_preparation_policy", {})
    missing = [k for k in policy["required"] if order["order"].get(k) is not True]
    preference = (
        "afternoon" if "오후" in job.request else "morning" if "오전" in job.request else "any"
    )
    fixture = {
        "ready": not missing,
        "missing_fields": missing,
        "preference": preference,
        "explanation": "필수 행정 서류 접수를 확인했습니다."
        if not missing
        else "미완료 항목: " + ", ".join(FIELD_LABELS[k] for k in missing),
    }
    decision = await decide(
        ReadinessDecision,
        READINESS_PROMPT,
        {
            "request": job.request,
            "evidence": {"order": order["order"], "policy": policy},
        },
        fixture,
        emit,
    )
    if set(decision.missing_fields) != set(missing) or decision.ready != (not missing):
        emit(
            "guard.rejected",
            "준비 상태 대조",
            {"reason": "모델 결과가 원본 접수 상태와 다름"},
        )
        raise ValueError("모델의 준비 상태 판단이 원본과 일치하지 않습니다.")
    return {
        "decision": decision.model_dump(),
        "order": order["order"],
        "policy": policy,
        "missing_labels": [FIELD_LABELS[k] for k in missing],
        "sources": [order["source"], policy["id"]],
    }


async def scheduling(job, emit):
    async with hospital_tools(emit) as call:
        order = await call("get_order", {"order_id": job.order_id})
        policy = await call("get_preparation_policy", {})
        if not all(order["order"].get(k) is True for k in policy["required"]):
            raise ValueError("미완료 의뢰에 대한 일정 요청 차단")
        result = await call(
            "find_slots", {"session_id": job.session_id, "exam": order["order"]["exam"]}
        )
    candidates = [
        s for s in result["slots"] if job.preference == "any" or s["period"] == job.preference
    ]
    fixture = {
        "slot_id": candidates[0]["id"] if candidates else None,
        "explanation": "선호 조건에 맞는 가용 시간입니다."
        if candidates
        else "현재 선호 조건에 맞는 시간이 없습니다. 조건을 바꾸어 다시 조회하세요.",
    }
    decision = await decide(
        ScheduleDecision,
        SCHEDULE_PROMPT,
        {
            "request": job.request,
            "preference": job.preference,
            "eligible_slots": candidates,
        },
        fixture,
        emit,
    )
    valid = {s["id"] for s in candidates}
    if (candidates and decision.slot_id not in valid) or (
        not candidates and decision.slot_id is not None
    ):
        emit("guard.rejected", "가용 시간 대조", {"reason": "허용 후보 밖의 시간"})
        raise ValueError("모델이 조회 후보에 없는 시간을 선택했습니다.")
    selected = next((s for s in candidates if s["id"] == decision.slot_id), None)
    return {
        "decision": decision.model_dump(),
        "selected": selected,
        "candidates": candidates,
        "sources": [result["source"]],
    }


class ExamExecutor(AgentExecutor):
    def __init__(self, name, event_sink):
        self.name, self.event_sink = name, event_sink

    async def execute(self, context: RequestContext, event_queue: EventQueue):
        task = context.current_task or new_task(context.message)
        await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)
        await updater.update_status(TaskState.working)
        try:
            job = AgentJob.model_validate_json(context.get_user_input())
            emit = self.event_sink(job.run_id, self.name)
            emit("agent.started", self.name, {"a2a_task_id": task.id})
            result = await (
                readiness(job, emit) if self.name == "readiness" else scheduling(job, emit)
            )
            await updater.add_artifact([Part(root=DataPart(data=result))], name=self.name)
            state = (
                TaskState.input_required
                if self.name == "readiness" and not result["decision"]["ready"]
                else TaskState.completed
            )
            emit("agent.finished", self.name, {"state": state.value})
            await updater.update_status(state, final=True)
        except Exception as exc:
            if "job" in locals():
                self.event_sink(job.run_id, self.name)(
                    "agent.failed", self.name, {"error_type": type(exc).__name__}
                )
            await updater.update_status(
                TaskState.failed,
                new_agent_text_message(
                    "처리를 완료하지 못했습니다. 도구·모델 연결 또는 입력 조건을 확인한 뒤 새 요청으로 재시도하세요.",
                    task.context_id,
                    task.id,
                ),
                final=True,
            )

    async def cancel(self, context: RequestContext, event_queue: EventQueue):
        from a2a.types import UnsupportedOperationError
        from a2a.utils.errors import ServerError

        raise ServerError(error=UnsupportedOperationError(message="UI 실행 취소를 사용하세요."))
