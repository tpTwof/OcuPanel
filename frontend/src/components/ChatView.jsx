import { useEffect, useRef, useState } from 'react'
import Markdown from './Markdown.jsx'
import EvidenceList from './EvidenceList.jsx'
import VerificationResult from './VerificationResult.jsx'

/** 一条消息。meta 里可能带报告相关字段（分割图、证据、校验结果）。 */
function MessageItem({ m, imageUrls }) {
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
          <span className="dots" />
        ) : (
          <>
            <Markdown text={m.content} />
            {meta.kind === 'report' && (
              <div className="msg-report-meta">
                {meta.cup_to_disc_ratio != null && (
                  <span className="chip">杯盘比 {Number(meta.cup_to_disc_ratio).toFixed(2)}</span>
                )}
                {imgUrl && <img className="ai-image" src={imgUrl} alt="视盘分割结果" />}
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
  busy,
  title,
  notConfigured,
  onOpenSettings
}) {
  const [input, setInput] = useState('')
  const listRef = useRef(null)
  const pinnedRef = useRef(true)

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
          <MessageItem key={m.id} m={m} imageUrls={imageUrls} />
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
          placeholder="请输入您的问题..."
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
            {busy ? '思考中…' : '发送'}
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path d="M4 12l16-8-6 8 6 8z" fill="currentColor" />
            </svg>
          </button>
        </div>
      </div>
    </div>
  )
}
