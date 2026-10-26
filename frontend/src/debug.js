/**
 * 调试总线：把每次 API 调用的 名称/URL/状态码/耗时/请求摘要/响应体 收进一个
 * 环形缓冲，供 DebugDrawer 展示。
 *
 * 开关（可用 URL 参数临时覆盖，不用重新构建）：
 *   ?debug=0        关闭调试抽屉（默认开启）
 * 也可以写进 frontend/.env：VITE_DEBUG=0
 *
 * 注：离线 mock 模式已移除——现在数据都在 SQLite 里、且需要登录态，
 * 用一个假的 mock 层只会制造"看起来能用其实没通"的错觉。
 */
const query = new URLSearchParams(window.location.search)

export const DEBUG_ENABLED =
  import.meta.env.VITE_DEBUG !== '0' && query.get('debug') !== '0'

const MAX_ENTRIES = 50
let entries = []
const listeners = new Set()

function emit() {
  const snapshot = entries
  listeners.forEach((fn) => fn(snapshot))
}

export function subscribeDebug(fn) {
  listeners.add(fn)
  fn(entries)
  return () => listeners.delete(fn)
}

export function clearDebug() {
  entries = []
  emit()
}

export function startEntry(meta) {
  const entry = {
    id: `${Date.now()}-${Math.random().toString(16).slice(2, 6)}`,
    at: new Date().toLocaleTimeString('zh-CN', { hour12: false }),
    status: 'pending',
    ok: null,
    duration: null,
    ...meta,
    _t0: performance.now()
  }
  entries = [entry, ...entries].slice(0, MAX_ENTRIES)
  emit()
  return entry.id
}

/** 只更新仍在 pending 的条目，重复调用不会覆盖已结束的记录。 */
export function finishEntry(id, patch) {
  let changed = false
  entries = entries.map((e) => {
    if (e.id !== id || e.status !== 'pending') return e
    changed = true
    const { _t0, ...rest } = e
    return {
      ...rest,
      ...patch,
      duration: patch.duration ?? Math.round(performance.now() - _t0)
    }
  })
  if (changed) emit()
}

export function summarize(value) {
  if (value instanceof Blob) return `<Blob ${value.size} bytes · ${value.type || '未知类型'}>`
  try {
    return JSON.stringify(value, null, 2).slice(0, 4000)
  } catch {
    return String(value)
  }
}
