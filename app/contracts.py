from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RunInput(StrictModel):
    order_id: Literal["EX-1001", "EX-1002", "EX-1003"]
    request: str = Field(
        default="가능한 검사 예약 시간을 찾아주세요.", min_length=1, max_length=500
    )


class ReadinessDecision(StrictModel):
    ready: bool
    missing_fields: list[str]
    preference: Literal["morning", "afternoon", "any"]
    explanation: str = Field(min_length=1, max_length=700)


class ScheduleDecision(StrictModel):
    slot_id: str | None
    explanation: str = Field(min_length=1, max_length=700)


class AgentJob(StrictModel):
    run_id: str
    session_id: str
    order_id: Literal["EX-1001", "EX-1002", "EX-1003"]
    request: str = Field(max_length=500)
    preference: Literal["morning", "afternoon", "any"] = "any"


class ApprovalInput(StrictModel):
    version: int = Field(ge=1)


class SlotInput(StrictModel):
    exam: Literal["CT", "MRI", "US"]
    day: str = Field(min_length=1, max_length=40, pattern=r".*\S.*")
    time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    room: str = Field(min_length=1, max_length=40, pattern=r".*\S.*")
    enabled: bool = True
    version: int | None = Field(default=None, ge=1)
