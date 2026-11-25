"""Operator-provisioned memberships for the explicitly shared rehearsal workspace."""
import sqlite3
import json

from utils.errors import ApplicationError


def check_endpoint(conn: sqlite3.Connection, user_id: str, base_url: str | None) -> None:
    row = conn.execute("SELECT p.endpoints FROM screening_members m LEFT JOIN screening_site_policy p "
                       "USING(organization) WHERE m.user_id=?", (user_id,)).fetchone()
    if row and (not base_url or base_url.strip().rstrip("/") not in json.loads(row["endpoints"] or "[]")):
        raise ApplicationError(403, "此模型端点未列入机构配置")


def analysis_site(conn: sqlite3.Connection, user_id: str) -> str | None:
    row = conn.execute("SELECT m.organization,p.paused FROM screening_members m LEFT JOIN screening_site_policy p "
                       "USING(organization) WHERE user_id=?", (user_id,)).fetchone()
    if row and row["paused"] != 0:
        raise ApplicationError(409, "机构研究分析已暂停，请转人工复核")
    return row["organization"] if row else None

ROLE_ACTIONS = {
    "capture": {"create", "revise", "import_analysis", "handoff"},
    "reader": {"review", "sign", "revoke", "refer", "handoff", "revise", "create", "import_analysis", "followup"},
    "coordinator": {"receipt", "handoff", "followup"},
}


def scope(conn: sqlite3.Connection, user_id: str, case_id: str, action: str = "read") -> str:
    case = conn.execute("SELECT user_id,organization FROM screening_cases WHERE id=?", (case_id,)).fetchone()
    if case is None:
        raise ApplicationError(404, "病例不存在")
    if case["organization"] is None:
        if case["user_id"] != user_id:
            raise ApplicationError(404, "病例不存在")
    else:
        member = conn.execute("SELECT role FROM screening_members WHERE user_id=? AND organization=?",
                              (user_id, case["organization"])).fetchone()
        if member is None:
            raise ApplicationError(404, "病例不存在")
        if action != "read" and action not in ROLE_ACTIONS[member["role"]]:
            raise ApplicationError(403, "当前机构角色不能执行此操作")
    return case["user_id"]


def creation_scope(conn: sqlite3.Connection, user_id: str, institution: str) -> str | None:
    member = conn.execute("SELECT organization,role FROM screening_members WHERE user_id=?", (user_id,)).fetchone()
    if member is None:
        return None
    if member["organization"] != institution or "create" not in ROLE_ACTIONS[member["role"]]:
        raise ApplicationError(403, "请核对机构名称及采集权限")
    return institution
