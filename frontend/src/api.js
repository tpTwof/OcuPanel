// 统一封装后端接口：带 token、调试记录、错误可读化。
//
// token 存在 localStorage，每个请求自动加 Authorization 头。
// 任何 401 都会抛 AuthError，由 App 统一弹回登录页——不让用户看到"请求失败"却不知道为什么。
import { DEBUG_ENABLED, finishEntry, startEntry, summarize } from './debug.js'

const envBase = import.meta.env.VITE_API_BASE_URL
export const API_BASE_URL =
  envBase === undefined || envBase === '' ? '' : envBase.replace(/\/$/, '')

const TOKEN_KEY = 'ocupanel.token'

export class AuthError extends Error {}

export function getToken() {
  try {
    return localStorage.getItem(TOKEN_KEY) || ''
  } catch {
    return ''
  }
}

export function setToken(token) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token)
    else localStorage.removeItem(TOKEN_KEY)
  } catch {
    /* ignore */
  }
}

function authHeaders(extra = {}) {
  const token = getToken()
  return token ? { ...extra, Authorization: `Bearer ${token}` } : { ...extra }
}

async function callApi({ name, url, init = {}, request, read }) {
  const id = DEBUG_ENABLED
    ? startEntry({ name, url, method: init.method || 'GET', request })
    : null

  try {
    const res = await fetch(url, { ...init, headers: authHeaders(init.headers) })

    if (!res.ok) {
      const text = await res.text().catch(() => '')
      if (id) {
        finishEntry(id, { status: res.status, ok: false, response: text.slice(0, 4000) || res.statusText })
      }
      // FastAPI 把可读原因放在 {"detail": "..."} 里；422 拒答时这就是全部信息
      let message = text
      try {
        const body = JSON.parse(text)
        if (body?.detail) {
          message = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
        }
      } catch {
        /* 非 JSON，保持原文 */
      }
      if (res.status === 401) {
        setToken('')
        throw new AuthError(message || '登录已过期')
      }
      // 5xx 且没有可读原因：要么请求根本没到后端（开发模式下 Vite 代理
      // 在后端未启动时直接回 500），要么后端抛了未捕获异常、FastAPI 只回了
      // 一句 "Internal Server Error"。两种情况都只能靠后端控制台定位，
      // 所以这里必须明确告诉用户去哪儿看，而不是把状态文本甩给他。
      if (res.status >= 500 && (!text.trim() || /^internal server error$/i.test(text.trim()))) {
        throw new Error(
          `后端返回 ${res.status}，但没有给出具体原因。` +
            '常见原因是 FastAPI 没启动（开发模式下页面在 5500、接口要转发到 8000）' +
            '或后端抛了未捕获异常。请在 backend 目录下确认服务在运行，' +
            '并查看它的控制台 traceback。'
        )
      }
      // 把状态码挂在错误上，调用方才能按状态区分处理（如删除时 404 视为已删）
      const error = new Error(message || res.statusText)
      error.status = res.status
      throw error
    }

    const value = await read(res)
    if (id) finishEntry(id, { status: res.status, ok: true, response: summarize(value) })
    return value
  } catch (err) {
    if (id && !(err instanceof AuthError)) {
      finishEntry(id, { status: 'ERR', ok: false, response: String(err?.message || err) })
    }
    throw err
  }
}

const json = (res) => res.json()

// ---------------------------------------------------------------------------
// 账号
// ---------------------------------------------------------------------------
export const register = (username, password, displayName) =>
  callApi({
    name: '注册',
    url: `${API_BASE_URL}/api/account/register`,
    init: { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username, password, display_name: displayName }) },
    request: { username },
    read: json
  })

export const login = (username, password) =>
  callApi({
    name: '登录',
    url: `${API_BASE_URL}/api/account/login`,
    init: { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username, password }) },
    request: { username },
    read: json
  })

export const logout = () =>
  callApi({ name: '登出', url: `${API_BASE_URL}/api/account/logout`, init: { method: 'POST' }, read: json })

export const fetchMe = () => callApi({ name: '当前用户', url: `${API_BASE_URL}/api/account/me`, read: json })

export const fetchLlmPresets = () =>
  callApi({ name: '预设', url: `${API_BASE_URL}/api/account/llm-presets`, read: json })

export const saveLlmConfig = (body) =>
  callApi({
    name: '保存 LLM 配置',
    url: `${API_BASE_URL}/api/account/llm`,
    init: { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) },
    request: { model: body.model, base_url: body.base_url, api_key: body.api_key ? '已填写' : '(沿用)' },
    read: json
  })

export const clearLlmConfig = () =>
  callApi({ name: '清除 LLM 配置', url: `${API_BASE_URL}/api/account/llm`, init: { method: 'DELETE' }, read: json })

export const testLlmConfig = (body) =>
  callApi({
    name: '测试 LLM 配置',
    url: `${API_BASE_URL}/api/account/llm/test`,
    init: { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) },
    request: { model: body.model, base_url: body.base_url },
    read: json
  })

export const fetchUsage = () =>
  callApi({ name: '用量概览', url: `${API_BASE_URL}/api/account/usage`, read: json })

// ---------------------------------------------------------------------------
// 会话
// ---------------------------------------------------------------------------
export const listConversations = () =>
  callApi({ name: '会话列表', url: `${API_BASE_URL}/api/chat/conversations`, read: json })

export const createConversation = (title = '新对话') =>
  callApi({
    name: '新建会话',
    url: `${API_BASE_URL}/api/chat/conversations`,
    init: { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title }) },
    read: json
  })

export const getConversation = (id) =>
  callApi({ name: '会话详情', url: `${API_BASE_URL}/api/chat/conversations/${id}`, read: json })

export const renameConversation = (id, title) =>
  callApi({
    name: '重命名会话',
    url: `${API_BASE_URL}/api/chat/conversations/${id}`,
    init: { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title }) },
    read: json
  })

export const deleteConversation = async (id) => {
  try {
    return await callApi({
      name: '删除会话',
      url: `${API_BASE_URL}/api/chat/conversations/${id}`,
      init: { method: 'DELETE' },
      read: json
    })
  } catch (err) {
    // 404 说明它已经不在了（另一个标签页删过、或重复点击）。
    // 目的已达成，按成功处理，别给用户弹一个"会话不存在"的报错。
    if (err.status === 404) return { ok: true }
    throw err
  }
}

export const sendMessage = (conversationId, message) =>
  callApi({
    name: '提问',
    url: `${API_BASE_URL}/api/chat/conversations/${conversationId}/messages`,
    init: { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message }) },
    request: { message: message.slice(0, 80) },
    read: json
  })

// ---------------------------------------------------------------------------
// 报告
// ---------------------------------------------------------------------------
export const generateReportContent = (file, note, conversationId) => {
  const form = new FormData()
  form.append('file', file)
  form.append('note', note)
  if (conversationId) form.append('conversation_id', conversationId)
  return callApi({
    name: '生成报告',
    url: `${API_BASE_URL}/api/generate-report-content/`,
    init: { method: 'POST', body: form },
    request: { file: `${file.name} · ${Math.round(file.size / 1024)} KB`, note: note ? `${note.length} 字` : '(空)' },
    read: json
  })
}

export const getReportImage = (imgName) =>
  callApi({
    name: '取回分割图',
    url: `${API_BASE_URL}/api/get-report-image/${imgName}`,
    read: (res) => res.blob()
  })

export const downloadReportPdf = (file, note, conversationId) => {
  const form = new FormData()
  form.append('file', file)
  form.append('note', note)
  if (conversationId) form.append('conversation_id', conversationId)
  return callApi({
    name: '下载 PDF',
    url: `${API_BASE_URL}/api/generate-report/`,
    init: { method: 'POST', body: form },
    request: { file: file?.name },
    read: (res) => res.blob()
  })
}
