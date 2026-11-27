"""紧急撤屏（大堂撤屏级联案 · signboard-05）。

说明（当班锁死）：正式撤屏必须同事务将该屏活跃覆盖全部停用，
撤屏痕与覆盖停用痕同票双痕（票 = panic#事件ID），任一步失败整笔回滚。
甲路径 /official 直写正式区；乙路径 /shadow→/promote 草案期正式区零改、
升正时原子级联。两路不得混用。

占锁名「同屏撤屏级联互斥」：两路并发抢同一把锁，败方零正式行、只记争用。
"""
from __future__ import annotations

import time
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException

from audit_svc import write_audit, write_history
from auth import current_user, require_writer
from db import connect, rows_to_list
from history_svc import record_history
from overrides_svc import cascade_deactivate_overrides
from validators import require_positive_int, require_title

router = APIRouter(prefix="/api/panic", tags=["panic"])

# 占锁名（题面钉死）：同屏撤屏级联互斥
PANIC_CASCADE_LOCK = "同屏撤屏级联互斥"
LOCK_TTL_SEC = 20


def _lock_key(screen_id: int) -> str:
    return f"{PANIC_CASCADE_LOCK}:{screen_id}"


def _try_acquire_cascade_lock(lock_key: str, holder: str, ttl_sec: int = LOCK_TTL_SEC) -> str | None:
    """原子占锁（单句 CAS 落写锁表，免 check-then-act 窗口）。

    返回 None 表示占锁成功；否则返回当前持锁人，调用方只记争用。
    """
    now = time.time()
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO write_locks(lock_key,holder,expires_at) VALUES(?,?,?) "
            "ON CONFLICT(lock_key) DO UPDATE SET holder=excluded.holder, expires_at=excluded.expires_at "
            "WHERE write_locks.expires_at<=? OR write_locks.holder=?",
            (lock_key, holder, now + ttl_sec, now, holder),
        )
        conn.commit()
        if cur.rowcount:
            return None
        row = conn.execute("SELECT holder FROM write_locks WHERE lock_key=?", (lock_key,)).fetchone()
        return row["holder"] if row else "未知持锁方"


def _release_cascade_lock(lock_key: str, holder: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM write_locks WHERE lock_key=? AND holder=?", (lock_key, holder))
        conn.commit()


def _record_contention(screen_id: int, reason: str, actor: str, lock_key: str, holder: str) -> None:
    """败方只记争用：不落任何正式行。"""
    detail = f"{lock_key} 争用：撤屏「{reason}」未落正式行；持锁方 {holder}"
    with connect() as conn:
        record_history(conn, "screen", screen_id, "panic_cascade_contention", detail, actor)
        conn.commit()
    write_audit(actor, "panic.contention", {"screen_id": screen_id, "lock_key": lock_key, "holder": holder})


def _recent_panic_holder(screen_id: int, since: float) -> str | None:
    """同屏是否已落成不早于 since 的正式撤屏（并发胜方），有则返回其操作者。"""
    with connect() as conn:
        row = conn.execute(
            "SELECT created_by FROM panic_events WHERE screen_id=? AND official=1 AND created_at>=? "
            "ORDER BY id DESC LIMIT 1",
            (screen_id, since),
        ).fetchone()
        return row["created_by"] if row else None


def _acquire_or_contend(screen_id: int, reason: str, actor: str, started: float) -> str:
    """争用闸：占锁失败，或占锁成功但同屏已有并发胜方落成正式撤屏 → 只记争用并 409。

    放行时返回本次持锁人，供 finally 释放。
    """
    lock_key = _lock_key(screen_id)
    holder = f"{actor}#{uuid4().hex[:8]}"
    current = _try_acquire_cascade_lock(lock_key, holder)
    if current is None:
        recent = _recent_panic_holder(screen_id, started)
        if recent is None:
            return holder  # 占锁成功且无并发胜方，放行
        _release_cascade_lock(lock_key, holder)
        current = f"{recent}（并发胜方已落成）"
    _record_contention(screen_id, reason, actor, lock_key, current)
    raise HTTPException(409, f"{PANIC_CASCADE_LOCK}争用：{current} 持锁中，本次仅记争用未落正式行")


def _panic_tx(screen_id: int, reason: str, actor: str, action: str, shadow_id: int | None = None) -> dict:
    """撤屏级联同事务：清正式发布 → 落撤屏事件（发票号）→ 级联停用覆盖同票落痕。

    任一步失败整笔回滚；甲乙两路各自入口调用，口径不混用。
    """
    with connect() as conn:
        screen = conn.execute("SELECT * FROM screens WHERE id=?", (screen_id,)).fetchone()
        if not screen:
            raise HTTPException(404, "屏幕不存在")
        if shadow_id is not None:
            sh = conn.execute("SELECT * FROM panic_shadows WHERE id=?", (shadow_id,)).fetchone()
            if not sh or sh["status"] != "open":
                raise HTTPException(409, "影子不可升正")
        conn.execute("DELETE FROM publications WHERE screen_id=? AND official=1", (screen_id,))
        cur = conn.execute(
            "INSERT INTO panic_events(screen_id,reason,official,created_at,created_by) VALUES(?,?,?,?,?)",
            (screen_id, reason, 1, time.time(), actor),
        )
        eid = cur.lastrowid
        ticket = f"panic#{eid}"
        cascaded = cascade_deactivate_overrides(conn, screen_id, ticket, actor)
        if shadow_id is not None:
            conn.execute("UPDATE panic_shadows SET status='promoted' WHERE id=?", (shadow_id,))
        record_history(
            conn, "panic", eid, action,
            f"{reason}｜票{ticket}｜级联停用覆盖{len(cascaded)}条", actor,
        )
        conn.commit()
    return {"id": eid, "ticket": ticket, "cascaded": cascaded}


@router.get("/events")
def list_events(authorization: str | None = Header(default=None)):
    current_user(authorization)
    with connect() as conn:
        rows = rows_to_list(
            conn.execute(
                """
                SELECT e.*, s.code screen_code, s.title screen_title
                FROM panic_events e JOIN screens s ON s.id=e.screen_id
                ORDER BY e.id DESC
                """
            ).fetchall()
        )
    return {"items": rows}


@router.get("/shadows")
def list_shadows(authorization: str | None = Header(default=None)):
    current_user(authorization)
    with connect() as conn:
        rows = rows_to_list(
            conn.execute(
                """
                SELECT sh.*, s.code screen_code
                FROM panic_shadows sh JOIN screens s ON s.id=sh.screen_id
                ORDER BY sh.id DESC
                """
            ).fetchall()
        )
    return {"items": rows}


@router.post("/official")
def panic_official(body: dict, authorization: str | None = Header(default=None)):
    """甲：同事务清空正式发布、级联停用覆盖并同票双痕。"""
    user = current_user(authorization)
    require_writer(user)
    screen_id = require_positive_int(body.get("screen_id"), "屏幕编号")
    reason = require_title(body.get("reason") or "紧急撤屏", "原因")
    started = time.time()
    holder = _acquire_or_contend(screen_id, reason, user["username"], started)
    try:
        result = _panic_tx(screen_id, reason, user["username"], "official")
    finally:
        _release_cascade_lock(_lock_key(screen_id), holder)
    write_audit(
        user["username"], "panic.official",
        {"id": result["id"], "screen_id": screen_id, "ticket": result["ticket"]},
    )
    return {
        "id": result["id"],
        "path": "official",
        "ticket": result["ticket"],
        "cascaded_overrides": len(result["cascaded"]),
    }


@router.post("/shadow")
def panic_shadow(body: dict, authorization: str | None = Header(default=None)):
    """乙第一步：只写影子撤屏草案，覆盖正式表零改。"""
    user = current_user(authorization)
    require_writer(user)
    screen_id = require_positive_int(body.get("screen_id"), "屏幕编号")
    reason = require_title(body.get("reason") or "影子撤屏草案", "原因")
    with connect() as conn:
        screen = conn.execute("SELECT * FROM screens WHERE id=?", (screen_id,)).fetchone()
        if not screen:
            raise HTTPException(404, "屏幕不存在")
        cur = conn.execute(
            "INSERT INTO panic_shadows(screen_id,reason,status,created_at,created_by) VALUES(?,?,?,?,?)",
            (screen_id, reason, "open", time.time(), user["username"]),
        )
        sid = cur.lastrowid
        conn.commit()
    write_history("panic_shadow", sid, "create", reason, user["username"])
    return {"id": sid, "path": "shadow"}


@router.post("/shadow/{shadow_id}/promote")
def promote_panic(shadow_id: int, authorization: str | None = Header(default=None)):
    """乙升正：原子落正式撤屏，同事务级联停用覆盖并同票双痕。"""
    user = current_user(authorization)
    require_writer(user)
    with connect() as conn:
        sh = conn.execute("SELECT * FROM panic_shadows WHERE id=?", (shadow_id,)).fetchone()
        if not sh or sh["status"] != "open":
            raise HTTPException(409, "影子不可升正")
        screen_id = sh["screen_id"]
        reason = sh["reason"]
    started = time.time()
    holder = _acquire_or_contend(screen_id, reason, user["username"], started)
    try:
        result = _panic_tx(screen_id, reason, user["username"], "promote_shadow", shadow_id=shadow_id)
    finally:
        _release_cascade_lock(_lock_key(screen_id), holder)
    write_audit(
        user["username"], "panic.promote",
        {"shadow_id": shadow_id, "id": result["id"], "ticket": result["ticket"]},
    )
    return {
        "id": result["id"],
        "path": "shadow_promote",
        "ticket": result["ticket"],
        "cascaded_overrides": len(result["cascaded"]),
    }
