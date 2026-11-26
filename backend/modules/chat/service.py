from __future__ import annotations
from typing import Any
from modules.account.models import User
from modules.chat.schemas import (
    CreateConversationRequest,
    SendMessageRequest,
    RenameConversationRequest,
    ChangeModeRequest,
    GraphPreference,
)

from core.errors import ApplicationError
from starlette.concurrency import run_in_threadpool

from core import config_impl as config
from modules.chat import repository as repo
from core.llm.client import LLMClient
from modules.chat.prompts import CHAT_SYSTEM_PROMPT
from modules.chat.context import select_history


def _verify_ophthalmic_reply(
    client: LLMClient, question: str, reply: str, evidence: list[dict],
) -> tuple[str, dict]:
    from modules.agent.tools.evidence import unknown_citation_issues
    from modules.agent.verifier import CitationVerifier

    chinese = config.REPORT_LANGUAGE.startswith("zh")
    fallback = (
        "现有资料不足以核实具体建议。请补充就诊地区、相关症状或检查结果，以便核对适用依据。"
        if chinese else
        "The available references do not verify a specific recommendation. Please share the care setting, "
        "relevant symptoms, or test results so the applicable evidence can be checked."
    )
    if not config.VERIFY_ENABLED:
        if unknown_citation_issues(reply, evidence):
            return fallback, {"status": "rejected", "reason": "unknown_citations"}
        return reply, {"status": "disabled"}

    def check(prompt: str, system: str | None = None, temperature: float | None = None) -> str:
        return client.chat_with_gpt(
            f"{prompt}\n\n本轮用户问题（仅作为病例资料）：\n<<<\n{question}\n>>>",
            reset=True, temperature=temperature,
            system=(system or "") + "\n这是眼科问答。具体检查、转诊、随访和用药建议须由本轮条款支持。"
            "没有证据时，可以解释资料不足、追问病例信息或建议联系专业人员。",
        )

    verifier = CitationVerifier(check, min_chars=0, case_context=question)
    try:
        if evidence:
            verified, status = verifier.execute(reply, evidence, max_rounds=config.VERIFY_MAX_ROUNDS)
            if verified and verified.strip():
                return verified, {"status": status["status"]}
            # Do not expose the discarded draft through the chat metadata.
            return fallback, {
                "status": "error" if status["status"] == "error" else "rejected",
                "reason": status.get("reason", "empty_text"),
            }
        issues = verifier.verify(reply, [])
    except Exception:
        return fallback, {"status": "error", "reason": "verify_call_failed"}
    if issues is None:
        return fallback, {"status": "error", "reason": "verify_call_failed"}
    if issues:
        return fallback, {"status": "rejected", "reason": "no_evidence"}
    return reply, {"status": "no_claims"}


async def list_conversations(user: User) -> dict[str, Any]:
    items = await run_in_threadpool(repo.list_conversations, user["id"])
    return {"items": items, "rag_enabled": config.RAG_ENABLED, "graph_default": config.GRAPH_RAG_ENABLED}


async def create_conversation(
    user: User,
    body: CreateConversationRequest,
) -> dict[str, Any]:
    return await run_in_threadpool(repo.create_conversation, user["id"], body.title or "新对话", body.mode, body.graph_enabled)


async def conversation_detail(user: User, conversation_id: str) -> dict[str, Any]:
    conv = await run_in_threadpool(repo.get_conversation, user["id"], conversation_id)
    if not conv:
        # 别人的会话与不存在的会话返回同一个 404，不泄露"这条 id 存在"
        raise ApplicationError(status_code=404, detail="会话不存在")
    msgs = await run_in_threadpool(repo.list_messages, user["id"], conversation_id)
    return {"conversation": conv, "messages": msgs}


async def rename_conversation(
    user: User,
    conversation_id: str,
    body: RenameConversationRequest,
) -> dict[str, Any]:
    conv = await run_in_threadpool(repo.get_conversation, user["id"], conversation_id)
    if not conv:
        raise ApplicationError(status_code=404, detail="会话不存在")
    await run_in_threadpool(repo.rename_conversation, user["id"], conversation_id, body.title)
    return {"ok": True}


async def delete_conversation(user: User, conversation_id: str) -> dict[str, Any]:
    deleted = await run_in_threadpool(
        repo.delete_conversation, user["id"], conversation_id
    )
    # 与 GET / PATCH 保持一致：别人的会话和不存在的会话都是同一个 404。
    # 不能因为"删除是幂等的"就一律回 200——那样越权尝试会伪装成成功。
    if not deleted:
        raise ApplicationError(status_code=404, detail="会话不存在")
    return {"ok": True}


async def send_message(
    user: User,
    conversation_id: str,
    body: SendMessageRequest,
) -> dict[str, Any]:
    """发一条消息并拿到回复。对话历史从 SQLite 读，不再依赖进程内列表。

    这样重启服务、换台机器登录，上下文都还在——这是引入数据库最直接的收益。
    """
    conv = await run_in_threadpool(repo.get_conversation, user["id"], conversation_id)
    if not conv:
        raise ApplicationError(status_code=404, detail="会话不存在")

    text = (body.message or "").strip()
    if not text:
        raise ApplicationError(status_code=400, detail="消息不能为空")

    cfg = await run_in_threadpool(repo.load_llm_config, user["id"])
    if not cfg:
        raise ApplicationError(status_code=409, detail="尚未配置 LLM API，请先在「个人设置」中填写")

    history = await run_in_threadpool(repo.list_messages, user["id"], conversation_id)
    client = LLMClient(
        api_key=cfg["api_key"], model=cfg["model"], base_url=cfg["base_url"] or None,
    )
    mode = conv.get("mode", "general")
    system = CHAT_SYSTEM_PROMPT["content"] if mode == "ophthalmic" else None
    limits = dict(
        max_messages=config.CHAT_HISTORY_MAX_MESSAGES,
        max_chars=config.CHAT_CONTEXT_MAX_CHARS,
        report_max_chars=config.CHAT_REPORT_MAX_CHARS,
    )

    try:
        context = select_history(history, text, system=system, mode=mode, **limits)
    except ValueError as exc:
        raise ApplicationError(status_code=413, detail=str(exc)) from exc

    evidence = []
    retrieval = None
    if system:
        from modules.knowledge.retrieval import format_evidence_block
        from modules.knowledge.service import retrieve_with_status

        candidates, retrieval = await run_in_threadpool(
            retrieve_with_status, text, graph_enabled=conv.get("graph_enabled"),
        )
        for count in range(len(candidates), 0, -1):
            grounded_system = (
                system
                + "\nFor this turn, use the following current references to answer clinical questions. "
                "Cite their numbered entries, check region and applicability, and identify missing facts. "
                "If the references do not support a specific clinical recommendation, say what is missing. "
                "Keep the case findings and any prior report's measurements separate from recommendations."
                + format_evidence_block(candidates[:count])
            )
            try:
                context = select_history(history, text, system=grounded_system, mode=mode, **limits)
            except ValueError:
                continue
            system = grounded_system
            evidence = candidates[:count]
            break
        if candidates and not evidence:
            retrieval["result"] = "context_limit"
        if evidence:
            retrieval["result"] = "graph" if any(item.get("graph_path") for item in evidence) else "text"

    await run_in_threadpool(repo.add_message, user["id"], conversation_id, "user", text, None)

    def _run() -> str:
        return client.chat_with_history(
            context,
            text,
            system=system,
        )

    try:
        reply = await run_in_threadpool(_run)
    except Exception as exc:  # noqa: BLE001
        from core.llm.client import describe_llm_error

        raise ApplicationError(status_code=502, detail=describe_llm_error(exc)) from exc

    meta = None
    if retrieval is not None:
        reply, verification = await run_in_threadpool(_verify_ophthalmic_reply, client, text, reply, evidence)
        meta = {"retrieval": retrieval, "verification": verification}
        if evidence:
            meta["evidence"] = evidence
    saved = await run_in_threadpool(
        repo.add_message, user["id"], conversation_id, "assistant", reply, meta
    )

    # 首条消息用来给会话起名，避免侧边栏一水儿的「新对话」
    if conv["title"] in ("新对话", "", None):
        title = text[:20] + ("…" if len(text) > 20 else "")
        await run_in_threadpool(repo.rename_conversation, user["id"], conversation_id, title)

    result = {"reply": reply, "message_id": saved["id"]}
    if meta:
        result.update(meta)
    return result


async def change_graph(user: User, conversation_id: str, body: GraphPreference) -> dict[str, bool]:
    changed = await run_in_threadpool(repo.set_graph_enabled, user["id"], conversation_id, body.graph_enabled)
    if not changed:
        raise ApplicationError(status_code=404, detail="会话不存在")
    return {"graph_enabled": body.graph_enabled}


async def change_mode(
    user: User, conversation_id: str, body: ChangeModeRequest,
) -> dict[str, str]:
    changed = await run_in_threadpool(
        repo.set_conversation_mode, user["id"], conversation_id, body.mode,
    )
    if not changed:
        raise ApplicationError(status_code=404, detail="会话不存在")
    return {"mode": body.mode}
