"""变更历史。"""
from __future__ import annotations

import time

from fastapi import APIRouter, Header, HTTPException

from auth import current_user
from db import connect, row_to_dict, rows_to_list

router = APIRouter(prefix="/api/history", tags=["history"])


def record_history(conn, entity_kind: str, entity_id: int, action: str, detail: str, actor: str) -> None:
    """事务内落痕：复用调用方连接，随同事务一并提交或回滚（不自行 commit）。"""
    conn.execute(
        "INSERT INTO change_history(entity_kind,entity_id,action,detail,actor,created_at) VALUES(?,?,?,?,?,?)",
        (entity_kind, entity_id, action, detail, actor, time.time()),
    )


@router.get("")
def list_history(limit: int = 100, authorization: str | None = Header(default=None)):
    current_user(authorization)
    with connect() as conn:
        rows = rows_to_list(
            conn.execute(
                "SELECT * FROM change_history ORDER BY id DESC LIMIT ?",
                (max(1, min(limit, 300)),),
            ).fetchall()
        )
    return {"items": rows}


@router.get("/panic/{panic_id}")
def panic_consistency(panic_id: int, authorization: str | None = Header(default=None)):
    """联查跨表账实：撤屏事件 ↔ 同票双痕 ↔ 覆盖正式行现状。"""
    current_user(authorization)
    ticket = f"panic#{panic_id}"
    with connect() as conn:
        event = row_to_dict(
            conn.execute(
                "SELECT * FROM panic_events WHERE id=? AND official=1", (panic_id,)
            ).fetchone()
        )
        if not event:
            raise HTTPException(404, "撤屏事件不存在")
        traces = rows_to_list(
            conn.execute(
                """
                SELECT * FROM change_history
                WHERE (entity_kind='panic' AND entity_id=?)
                   OR (entity_kind='override' AND action='panic_cascade_off' AND detail LIKE ?)
                ORDER BY id
                """,
                (panic_id, f"%票{ticket}%"),
            ).fetchall()
        )
        panic_traces = [t for t in traces if t["entity_kind"] == "panic"]
        override_traces = [t for t in traces if t["entity_kind"] == "override"]
        override_rows = []
        if override_traces:
            marks = ",".join("?" for _ in override_traces)
            override_rows = rows_to_list(
                conn.execute(
                    f"SELECT * FROM overrides WHERE id IN ({marks})",
                    tuple(t["entity_id"] for t in override_traces),
                ).fetchall()
            )
    consistent = (
        len(panic_traces) == 1
        and len(override_rows) == len(override_traces)
        and all(r["active"] == 0 for r in override_rows)
    )
    return {
        "event": event,
        "ticket": ticket,
        "panic_traces": panic_traces,
        "override_traces": override_traces,
        "override_rows": override_rows,
        "consistent": consistent,
    }
