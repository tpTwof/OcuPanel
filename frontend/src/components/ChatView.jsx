import { useEffect, useRef, useState } from 'react'
import Markdown from './Markdown.jsx'
import EvidenceList from './EvidenceList.jsx'
import VerificationResult from './VerificationResult.jsx'

/**
 * 报告生成期间展示的阶段提示。
 * 后端是一次性返回结果的，没有进度流，所以这里只能按经过时间推测到第几步；
 * 仅用于让用户知道"还在跑、跑到哪了"，不承诺精确进度。
 */
const REPORT_STAGES = [
  { at: 0, text: '影像分析：分割视盘与视杯，计算杯盘比' },
  { at: 8, text: '证据检索：BM25 + 多语言向量，RRF 融合' },
  { at: 20, text: '六专科并发会诊，Director 综合成文' },
  { at: 45, text: '引用校验：逐句核对 [n] 出处，不合格会重写' }
]

function ReportPending({ startedAt }) {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [])

  const elapsed = Math.max(0, Math.round((now - (startedAt || now)) / 1000))
  let stage = 0
  REPORT_STAGES.forEach((item, i) => {
    if (elapsed >= item.at) stage = i
  })

  return (
    <div className="report-pending" role="status" aria-live="polite">
      <div className="report-pending-head">
        <span className="spinner spinner-sm" aria-hidden="true" />
        <span className="report-pending-title">正在生成诊断报告…</span>
        <span className="report-pending-timer">{elapsed}s</span>
      </div>

      <ol className="report-stages">
        {REPORT_STAGES.map((item, i) => (
          <li
            key={item.at}
            className={i < stage ? 'is-done' : i === stage ? 'is-active' : 'is-todo'}
          >
            <span className="report-stage-dot" aria-hidden="true" />
            <span>{item.text}</span>
          </li>
        ))}
      </ol>

      <div className="report-pending-hint">
        通常需要 30–90 秒，完成后报告会直接出现在这里，可以继续追问细节。
      </div>
    </div>
  )
}

/** 一条消息。meta 里可能带报告相关字段（分割图、证据、校验结果）。 */
function MessageItem({ m, imageUrls, onDownloadPdf, busy }) {
  if (m.role === 'user') {
    return (
      <div className="msg msg-user">
        <div className="msg-bubble">{m.content}</div>
      </div>
    )
  }

  const meta = m.meta || {}
  const imgName = meta.img_name
  const imgUrl = imgName ? imageUrls[imgName] : null

  return (
    <div className="msg msg-ai">
      <div className="msg-avatar" aria-hidden="true">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none">
          <rect x="2" y="4" width="20" height="14" rx="4" stroke="currentColor" strokeWidth="1.8" />
          <circle cx="9" cy="11" r="1.6" fill="currentColor" />
          <circle cx="15" cy="11" r="1.6" fill="currentColor" />
        </svg>
      </div>
      <div className="msg-body">
        {m.pending ? (
          meta.pending_report ? (
            <ReportPending startedAt={meta.started_at} />
          ) : (
            <span className="dots" />
          )
        ) : (
          <>
            <Markdown text={m.content} />
            {meta.kind === 'report' && (
              <div className="msg-report-meta">
                {meta.cup_to_disc_ratio != null && (
                  <span className="chip">杯盘比 {Number(meta.cup_to_disc_ratio).toFixed(2)}</span>
                )}
                {/* 只有本会话内生成、且没被拒答的报告才给下载入口：
                    切走再回来 / 刷新后 source_file 已不存在，PDF 接口需要原图，没法重建 */}
                {meta.source_file && !meta.rejected && (
                  <button
                    type="button"
                    className="chip-btn"
                    disabled={busy}
                    onClick={() => onDownloadPdf(meta.source_file, meta.source_note || '')}
                  >
                    下载 PDF
                  </button>
                )}
                {imgUrl && (
                  <div className="msg-report-image">
                    <img className="ai-image" src={imgUrl} alt="视盘分割结果" />
                  </div>
                )}
              </div>
            )}
            <VerificationResult data={meta.verification} />
            <EvidenceList items={meta.evidence} />
          </>
        )}
      </div>
    </div>
  )
}

export default function ChatView({
  messages,
  imageUrls,
  onSend,
  onDownloadPdf,
  busy,
  title,
  notConfigured,
  onOpenSettings
}) {
  const [input, setInput] = useState('')
  const listRef = useRef(null)
  const pinnedRef = useRef(true)

  // 报告生成和普通提问都会让 busy=true，按钮文案要能区分，否则都是"思考中…"
  const generatingReport = messages.some((m) => m.pending && m.meta?.pending_report)

  // 用户本来就在底部时才自动跟随，否则别抢滚动位置（正在往上翻旧内容）
  useEffect(() => {
    const el = listRef.current
    if (!el || !pinnedRef.current) return
    el.scrollTop = el.scrollHeight
  }, [messages])

  const handleScroll = () => {
    const el = listRef.current
    if (!el) return
    pinnedRef.current = el.scrollHeight - el.clientHeight <= el.scrollTop + 4
  }

  const submit = () => {
    const text = input.trim()
    if (!text || busy) return
    pinnedRef.current = true
    onSend(text)
    setInput('')
  }

  return (
    <div className="chat-view">
      <div className="chat-head">
        <h2>{title || '新对话'}</h2>
      </div>

      <div className="chat-scroll" ref={listRef} onScroll={handleScroll}>
        {messages.length === 0 && (
          <div className="chat-empty">
            <div className="chat-empty-title">有什么可以帮你？</div>
            <div className="chat-empty-sub">
              在下方输入问题开始对话，或点左侧「生成报告」上传眼底影像。
            </div>
          </div>
        )}
        {messages.map((m) => (
          <MessageItem
            key={m.id}
            m={m}
            imageUrls={imageUrls}
            onDownloadPdf={onDownloadPdf}
            busy={busy}
          />
        ))}
      </div>

      {notConfigured && (
        <div className="banner-warn">
          还没有配置 LLM API，无法发起提问。
          <button type="button" className="link-btn" onClick={onOpenSettings}>
            去个人设置填写
          </button>
        </div>
      )}

      <div className="composer">
        <textarea
          className="composer-input"
          placeholder={generatingReport ? '报告生成中，完成后可继续追问…' : '请输入您的问题...'}
          value={input}
          rows={1}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              submit()
            }
          }}
        />
        <div className="composer-bar">
          <span className="composer-hint">Enter 发送 · Shift+Enter 换行</span>
          <button type="button" className="btn-send" onClick={submit} disabled={busy || !input.trim()}>
            {busy ? (generatingReport ? '生成中…' : '思考中…') : '发送'}
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path d="M4 12l16-8-6 8 6 8z" fill="currentColor" />
            </svg>
          </button>
        </div>
      </div>
    </div>
  )
}
