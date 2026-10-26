import { useEffect, useState } from 'react'
import { DEBUG_ENABLED, clearDebug, subscribeDebug } from '../debug.js'

function statusStyle(entry) {
  if (entry.status === 'pending') return { label: '进行中', color: '#B7791F', bg: '#FFF8E1' }
  if (entry.ok) return { label: String(entry.status), color: '#1B8A5A', bg: '#E7F6EE' }
  return { label: String(entry.status), color: '#C0392B', bg: '#FDECEA' }
}

function pretty(value) {
  if (value === undefined || value === null) return '—'
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

export default function DebugDrawer() {
  const [entries, setEntries] = useState([])
  const [open, setOpen] = useState(false)
  const [expanded, setExpanded] = useState(null)

  useEffect(() => subscribeDebug(setEntries), [])

  if (!DEBUG_ENABLED) return null

  const copyAll = async () => {
    const text = JSON.stringify(
      entries.map(({ name, url, method, status, ok, duration, at, request, response }) => ({
        at, name, method, url, status, ok, duration, request, response
      })),
      null,
      2
    )
    try {
      await navigator.clipboard.writeText(text)
      alert('已复制全部调试记录')
    } catch {
      alert(text.slice(0, 2000))
    }
  }

  const failureCount = entries.filter((e) => e.ok === false).length

  return (
    <>
      <button
        type="button"
        className="debug-fab"
        onClick={() => setOpen((v) => !v)}
        title="调试面板"
      >
        调试{entries.length ? ` ${entries.length}` : ''}
        {failureCount > 0 && <span className="debug-fab-badge">{failureCount}</span>}
      </button>

      {open && (
        <div className="debug-panel">
          <div className="debug-head">
            <strong>请求调试</strong>
            <span className="debug-env">真实后端</span>
            <span className="debug-actions">
              <button type="button" onClick={copyAll}>复制</button>
              <button type="button" onClick={() => { clearDebug(); setExpanded(null) }}>清空</button>
              <button type="button" onClick={() => setOpen(false)}>收起</button>
            </span>
          </div>

          <div className="debug-list">
            {entries.length === 0 && (
              <p className="debug-empty">还没有请求。上传图像或提问后会出现在这里。</p>
            )}
            {entries.map((entry) => {
              const s = statusStyle(entry)
              const isOpen = expanded === entry.id
              return (
                <div key={entry.id} className="debug-entry">
                  <button
                    type="button"
                    className="debug-entry-head"
                    onClick={() => setExpanded(isOpen ? null : entry.id)}
                  >
                    <span className="debug-name">{entry.name}</span>
                    <span className="debug-status" style={{ color: s.color, background: s.bg }}>
                      {s.label}
                    </span>
                    <span className="debug-duration">
                      {entry.duration === null ? '…' : `${entry.duration} ms`}
                    </span>
                    <span className="debug-time">{entry.at}</span>
                    <span className="debug-caret">{isOpen ? '收起' : '展开'}</span>
                  </button>

                  {isOpen && (
                    <div className="debug-body">
                      <div className="debug-label">
                        请求 · {entry.method} {entry.url}
                      </div>
                      <pre className="debug-pre">{pretty(entry.request)}</pre>
                      <div className="debug-label">响应</div>
                      <pre className="debug-pre">{pretty(entry.response)}</pre>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}
    </>
  )
}
