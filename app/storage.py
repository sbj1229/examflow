import os
import sqlite3
from pathlib import Path
from app.catalog import SLOTS


def connect():
    path = Path(os.getenv("EXAMFLOW_DB", ".tmp/examflow.db"))
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE IF NOT EXISTS reservations (session TEXT, slot TEXT, run TEXT UNIQUE, order_id TEXT, PRIMARY KEY(session, slot), UNIQUE(session, order_id))")
    db.execute("CREATE TABLE IF NOT EXISTS model_budget (day TEXT PRIMARY KEY, calls INTEGER)")
    return db


def available_slots(session_id, exam):
    with connect() as db:
        used = {r[0] for r in db.execute("SELECT slot FROM reservations WHERE session=?", (session_id,))}
    return [s for s in SLOTS if s["exam"] == exam and s["id"] not in used]


def reserve(session_id, slot_id, run_id, order_id):
    with connect() as db:
        existing = db.execute("SELECT * FROM reservations WHERE run=?", (run_id,)).fetchone()
        if existing:
            if existing["session"] != session_id or existing["slot"] != slot_id or existing["order_id"] != order_id:
                return {"status": "conflict", "reason": "실행 식별자 불일치"}
            return {"status": "confirmed", "reservation_id": run_id, "idempotent": True}
        try:
            db.execute("INSERT INTO reservations VALUES (?,?,?,?)", (session_id, slot_id, run_id, order_id))
        except sqlite3.IntegrityError:
            return {"status": "conflict", "reason": "해당 시간 또는 의뢰의 예약이 이미 존재합니다. 새 요청으로 조회하세요."}
    return {"status": "confirmed", "reservation_id": run_id, "idempotent": False}


def claim_model_call():
    """단일 인스턴스 데모의 일별 호출 한도. 클라우드 비용의 절대 상한은 아님."""
    from datetime import datetime, timezone
    day = datetime.now(timezone.utc).date().isoformat()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("INSERT OR IGNORE INTO model_budget VALUES (?,0)", (day,))
        changed = db.execute("UPDATE model_budget SET calls=calls+1 WHERE day=? AND calls<?", (day, int(os.getenv("DAILY_MODEL_CALL_LIMIT", "120")))).rowcount
        if not changed:
            raise RuntimeError("일일 모델 호출 한도에 도달했습니다.")
