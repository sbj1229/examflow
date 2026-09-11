"""독립 프로세스로 실행하는 공식 MCP stdio 서버."""

from mcp.server.fastmcp import FastMCP

from app.catalog import ORDERS, POLICY, SLOTS
from app.storage import available_slots, reserve

mcp = FastMCP("ExamFlow Hospital Tools", instructions="합성 병원 데이터만 취급하는 행정 업무 도구")


@mcp.tool()
def get_order(order_id: str) -> dict:
    """합성 검사 의뢰의 행정 접수 상태를 조회한다."""
    if order_id not in ORDERS:
        raise ValueError("존재하지 않는 의뢰")
    return {"order": ORDERS[order_id], "source": f"synthetic-orders/{order_id}"}


@mcp.tool()
def get_preparation_policy() -> dict:
    """병원에서 정한 합성 행정 서류 접수 규칙을 조회한다."""
    return POLICY


@mcp.tool()
def find_slots(session_id: str, exam: str) -> dict:
    """현재 데모 세션에서 예약 가능한 검사 시간을 조회한다."""
    return {
        "slots": available_slots(session_id, exam),
        "source": "synthetic-scheduling/v1",
    }


@mcp.tool()
def reserve_demo_slot(session_id: str, order_id: str, slot_id: str, run_id: str) -> dict:
    """신뢰된 서버가 승인 후 호출하는 데모 예약. 실제 병원에는 연결되지 않는다."""
    order = ORDERS.get(order_id)
    slot = next((s for s in SLOTS if s["id"] == slot_id), None)
    if not order or not slot or slot["exam"] != order["exam"]:
        raise ValueError("의뢰와 검사 시간 불일치")
    if not all(order.get(key) is True for key in POLICY["required"]):
        raise ValueError("필수 서류 접수 미완료")
    return reserve(session_id, slot_id, run_id, order_id)


if __name__ == "__main__":
    mcp.run(transport="stdio")
