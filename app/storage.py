import json
import os
import sqlite3
import uuid
from pathlib import Path

from app.catalog import SLOTS


def connect():
    path = Path(os.getenv("EXAMFLOW_DB", ".tmp/examflow.db"))
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute(
        "CREATE TABLE IF NOT EXISTS reservations (session TEXT, slot TEXT, run TEXT UNIQUE, order_id TEXT, PRIMARY KEY(session, slot), UNIQUE(session, order_id))"
    )
    db.execute("CREATE TABLE IF NOT EXISTS model_budget (day TEXT PRIMARY KEY, calls INTEGER)")
    db.execute(
        "CREATE TABLE IF NOT EXISTS slot_settings (session TEXT, slot TEXT, data TEXT, version INTEGER, PRIMARY KEY(session, slot))"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS cancelled_reservations (run TEXT PRIMARY KEY, session TEXT, slot TEXT, order_id TEXT)"
    )
    if "slot_data" not in {r[1] for r in db.execute("PRAGMA table_info(cancelled_reservations)")}:
        try:
            db.execute("ALTER TABLE cancelled_reservations ADD COLUMN slot_data TEXT")
        except sqlite3.OperationalError:
            # 동시에 시작한 다른 프로세스가 마이그레이션을 끝낸 경우만 허용한다.
            if "slot_data" not in {
                r[1] for r in db.execute("PRAGMA table_info(cancelled_reservations)")
            }:
                raise
    return db


def pool(db, session_id):
    slots = {s["id"]: dict(s, enabled=True, version=1) for s in SLOTS}
    for row in db.execute("SELECT * FROM slot_settings WHERE session=?", (session_id,)):
        slots[row["slot"]] = dict(json.loads(row["data"]), id=row["slot"], version=row["version"])
    return list(slots.values())


def workspace(session_id):
    from app.catalog import ORDERS

    with connect() as db:
        slots = pool(db, session_id)
        rows = [
            dict(r, status="confirmed")
            for r in db.execute("SELECT * FROM reservations WHERE session=?", (session_id,))
        ]
        rows += [
            dict(r, status="cancelled")
            for r in db.execute(
                "SELECT * FROM cancelled_reservations WHERE session=?", (session_id,)
            )
        ]
    occupied = {r["slot"] for r in rows if r["status"] == "confirmed"}
    for s in slots:
        s["status"] = "booked" if s["id"] in occupied else "available" if s["enabled"] else "closed"
    lookup = {s["id"]: s for s in slots}
    return {
        "slots": slots,
        "reservations": [
            {
                "id": r["run"],
                "order_id": r["order_id"],
                "alias": ORDERS[r["order_id"]]["alias"],
                "status": r["status"],
                "slot": json.loads(r["slot_data"]) if r.get("slot_data") else lookup[r["slot"]],
            }
            for r in rows
        ],
    }


def edit_slot(session_id, data, slot_id=None, version=None):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        slots = {s["id"]: s for s in pool(db, session_id)}
        if slot_id:
            if slot_id not in slots:
                raise LookupError("시간을 찾을 수 없습니다.")
            if slots[slot_id]["version"] != version:
                raise ValueError("다른 변경이 반영됐습니다. 새로고침 후 다시 저장하세요.")
            if db.execute(
                "SELECT 1 FROM reservations WHERE session=? AND slot=?", (session_id, slot_id)
            ).fetchone():
                raise ValueError("예약된 시간은 변경할 수 없습니다. 예약 취소 후 수정하세요.")
        else:
            if len(slots) >= 200:
                raise ValueError("관리 가능한 시간은 200개까지입니다.")
            slot_id = "SLOT-" + uuid.uuid4().hex[:12]
            version = 0
        data = dict(
            data, id=slot_id, period="morning" if int(data["time"][:2]) < 12 else "afternoon"
        )
        # 같은 검사실·운영일·시각의 중복 시간표는 만들지 않는다.
        if any(
            s["id"] != slot_id and all(s[k] == data[k] for k in ("day", "time", "room"))
            for s in slots.values()
        ):
            raise ValueError("같은 검사실에 동일한 시간이 이미 있습니다.")
        db.execute(
            "INSERT OR REPLACE INTO slot_settings VALUES (?,?,?,?)",
            (session_id, slot_id, json.dumps(data, ensure_ascii=False), version + 1),
        )
    return slot_id


def cancel_reservation(session_id, run_id):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT * FROM reservations WHERE session=? AND run=?", (session_id, run_id)
        ).fetchone()
        if not row:
            if db.execute(
                "SELECT 1 FROM cancelled_reservations WHERE session=? AND run=?",
                (session_id, run_id),
            ).fetchone():
                return
            raise LookupError("예약을 찾을 수 없습니다.")
        snapshot = next(s for s in pool(db, session_id) if s["id"] == row["slot"])
        db.execute(
            "INSERT INTO cancelled_reservations (run,session,slot,order_id,slot_data) VALUES (?,?,?,?,?)",
            (
                run_id,
                session_id,
                row["slot"],
                row["order_id"],
                json.dumps(snapshot, ensure_ascii=False),
            ),
        )
        db.execute("DELETE FROM reservations WHERE session=? AND run=?", (session_id, run_id))


def is_reservation_cancelled(session_id, run_id):
    with connect() as db:
        return bool(
            db.execute(
                "SELECT 1 FROM cancelled_reservations WHERE session=? AND run=?",
                (session_id, run_id),
            ).fetchone()
        )


def available_slots(session_id, exam):
    with connect() as db:
        used = {
            r[0] for r in db.execute("SELECT slot FROM reservations WHERE session=?", (session_id,))
        }
        return [
            s
            for s in pool(db, session_id)
            if s["enabled"] and s["exam"] == exam and s["id"] not in used
        ]


def reserve(session_id, slot_id, run_id, order_id, expected_version=None):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute(
            "SELECT 1 FROM cancelled_reservations WHERE session=? AND run=?", (session_id, run_id)
        ).fetchone():
            return {
                "status": "cancelled",
                "reservation_id": run_id,
                "reason": "담당자가 취소한 예약입니다.",
            }
        existing = db.execute("SELECT * FROM reservations WHERE run=?", (run_id,)).fetchone()
        if existing:
            if (
                existing["session"] != session_id
                or existing["slot"] != slot_id
                or existing["order_id"] != order_id
            ):
                return {"status": "conflict", "reason": "실행 식별자 불일치"}
            return {"status": "confirmed", "reservation_id": run_id, "idempotent": True}
        slot = next((s for s in pool(db, session_id) if s["id"] == slot_id), None)
        if not slot or not slot["enabled"]:
            return {
                "status": "conflict",
                "reason": "시간표가 변경되어 현재 예약할 수 없습니다. 다시 조회하세요.",
            }
        if expected_version is not None and slot["version"] != expected_version:
            return {
                "status": "conflict",
                "reason": "조회 후 시간표가 수정됐습니다. 변경된 시간으로 다시 조회하세요.",
            }
        try:
            db.execute(
                "INSERT INTO reservations VALUES (?,?,?,?)",
                (session_id, slot_id, run_id, order_id),
            )
        except sqlite3.IntegrityError:
            return {
                "status": "conflict",
                "reason": "해당 시간 또는 의뢰의 예약이 이미 존재합니다. 새 요청으로 조회하세요.",
            }
    return {"status": "confirmed", "reservation_id": run_id, "idempotent": False}


def claim_model_call():
    """단일 인스턴스 데모의 일별 호출 한도. 클라우드 비용의 절대 상한은 아님."""
    from datetime import datetime, timezone

    day = datetime.now(timezone.utc).date().isoformat()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("INSERT OR IGNORE INTO model_budget VALUES (?,0)", (day,))
        changed = db.execute(
            "UPDATE model_budget SET calls=calls+1 WHERE day=? AND calls<?",
            (day, int(os.getenv("DAILY_MODEL_CALL_LIMIT", "120"))),
        ).rowcount
        if not changed:
            raise RuntimeError("일일 모델 호출 한도에 도달했습니다.")
