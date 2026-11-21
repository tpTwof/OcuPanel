import ChatModeSwitcher from './ChatModeSwitcher.jsx'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
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
  { at: 8, text: '检索并合并相关指南证据' },
  { at: 20, text: '专科分析，综合生成报告' },
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

const RETRIEVAL_LABELS = {
  graph: '图谱命中',
  text: '文本检索命中',
  empty: '未找到相关证据',
  error: '本轮检索失败',
  disabled: '知识检索已关闭',
  context_limit: '本轮上下文空间不足，未使用检索结果'
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
  const evidencePrefix = `evidence-${m.id}`

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
            {meta.kind === 'report' && meta.visual_findings_text && (
              <Markdown text={meta.visual_findings_text} />
            )}
            {meta.kind === 'report' && imgUrl && (
              <details className="report-measurement">
                <summary>查看视盘与视杯分割图</summary>
                {meta.visual_findings_text && (
                  <p>粉红色为视盘环，绿色为视杯。面积等效杯盘比为视杯面积占整个视盘面积比例的平方根。</p>
                )}
                <img src={imgUrl} alt="眼底图上的视盘环与视杯分割叠加结果" />
              </details>
            )}
            <Markdown text={m.content} evidence={meta.evidence} evidencePrefix={evidencePrefix} />
            {meta.kind === 'report' && (
              <div className="msg-report-meta">
                {!meta.visual_findings_text && meta.cup_to_disc_ratio != null && (
                  <span className="chip">杯盘比 {Number(meta.cup_to_disc_ratio).toFixed(2)}</span>
                )}
                {meta.report_id && !meta.rejected && ['pass', 'rewritten'].includes(meta.verification?.status) && (
                  <button
                    type="button"
                    className="chip-btn"
                    disabled={busy}
                    onClick={() => onDownloadPdf(meta.report_id)}
                  >
                    下载 PDF
                  </button>
                )}
              </div>
            )}
            {meta.retrieval && (
              <div className="msg-report-meta">
                <span className="chip">{RETRIEVAL_LABELS[meta.retrieval.result]}</span>
                {meta.retrieval.graph === 'unavailable' && <span className="chip">图谱加载失败</span>}
                {meta.retrieval.graph === 'disabled' && meta.retrieval.result !== 'disabled' && (
                  <span className="chip">图检索已关闭</span>
                )}
                {meta.retrieval.graph === 'ready' && ['text', 'empty'].includes(meta.retrieval.result) && (
                  <span className="chip">本轮未使用图谱证据</span>
                )}
              </div>
            )}
            <VerificationResult data={meta.verification} isChat={meta.kind !== 'report'} />
            <EvidenceList items={meta.evidence} evidencePrefix={evidencePrefix} />
          </>
        )}
      </div>
    </div>
  )
}

export default function ChatView({
  mode, onModeChange, onOpenAnalysis, graphEnabled, ragEnabled, onGraphChange,
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
  const inputRef = useRef(null)
  const toolsRef = useRef(null)
  const pinnedRef = useRef(true)

  // 报告生成和普通提问都会让 busy=true，按钮文案要能区分，否则都是"思考中…"
  const generatingReport = messages.some((m) => m.pending && m.meta?.pending_report)

  // 用户本来就在底部时才自动跟随，否则别抢滚动位置（正在往上翻旧内容）
  useEffect(() => {
    const el = listRef.current
    if (!el || !pinnedRef.current) return
    el.scrollTop = el.scrollHeight
  }, [messages])

  const resizeInput = () => {
    const el = inputRef.current
    if (!el) return
    // 先恢复自动高度才能测量删除内容后的高度；CSS 负责限制最大高度。
    el.style.overflowY = 'hidden'
    el.style.height = 'auto'
    const style = getComputedStyle(el)
    const border = parseFloat(style.borderTopWidth) + parseFloat(style.borderBottomWidth)
    el.style.height = `${el.scrollHeight + border}px`
    el.style.overflowY = el.scrollHeight > el.clientHeight ? 'auto' : 'hidden'
    if (pinnedRef.current && listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight
    }
  }

  useLayoutEffect(() => {
    resizeInput()
  }, [input])

  useEffect(() => {
    const container = inputRef.current?.parentElement
    if (!container) return
    let width = container.clientWidth
    const observer = new ResizeObserver(() => {
      if (container.clientWidth === width) return
      width = container.clientWidth
      resizeInput()
    })
    observer.observe(container)
    return () => observer.disconnect()
  }, [])

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
        <ChatModeSwitcher
          mode={mode}
          onChange={onModeChange}
          busy={busy}
        />
      </div>

      <div className="chat-scroll" ref={listRef} onScroll={handleScroll}>
        {messages.length === 0 && (
          <div className="chat-empty">
            <div className="chat-empty-title">有什么可以帮你？</div>
            <div className="chat-empty-sub">
              {mode === 'ophthalmic'
                ? '可以询问眼科问题，或通过下方「+」选择「眼科影像分析」上传图片和临床记录。'
                : '在下方输入问题，或通过「+」上传眼底影像进行分析。'}
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
        <div className="composer-panel">
          <textarea
            ref={inputRef}
            className="composer-input"
            placeholder={generatingReport ? '报告生成中，完成后可继续追问…' : '请输入您的问题...'}
            value={input}
            rows={1}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault()
                submit()
              }
            }}
          />
          <div className="composer-bar">
            <details className="composer-tools" ref={toolsRef}
              onBlur={(event) => {
                if (!event.currentTarget.contains(event.relatedTarget)) event.currentTarget.open = false
              }}
              onKeyDown={(event) => {
                if (event.key === 'Escape') {
                  toolsRef.current.open = false
                  toolsRef.current.querySelector('summary').focus()
                }
              }}
            >
              <summary aria-label="高级选项" title="高级选项">
                <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
                  <path d="M2 8h12M8 2v12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                </svg>
              </summary>
              <div className="composer-tools-panel">
                <button type="button" disabled={busy} onClick={onOpenAnalysis}>眼科影像分析</button>
                {mode === 'ophthalmic' && (
                  <label>
                    问答图谱检索
                    <input type="checkbox" checked={Boolean(ragEnabled && graphEnabled)}
                      disabled={busy || !ragEnabled} onChange={(e) => onGraphChange(e.target.checked)} />
                  </label>
                )}
                {mode === 'ophthalmic' && ragEnabled === false && <small>服务端已关闭知识检索</small>}
              </div>
            </details>
            <span className="composer-hint">
              {mode === 'ophthalmic' ? '眼科助手' : '普通聊天'} · Enter 发送 · Shift+Enter 换行
            </span>
            <button
              type="button"
              className="btn-send"
              onClick={submit}
              disabled={busy || !input.trim()}
              aria-label={busy ? (generatingReport ? '正在生成报告' : '正在回复') : '发送消息'}
              title={busy ? (generatingReport ? '正在生成报告' : '正在回复') : '发送消息'}
            >
              {busy ? (
                <span className="spinner send-spinner" aria-hidden="true" />
              ) : (
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                  <path d="M12 19V5m-6 6 6-6 6 6" stroke="currentColor" strokeWidth="2"
                    strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
