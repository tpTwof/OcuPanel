import { useState } from 'react'
import { login, register } from '../api.js'

/** 登录 / 注册。同一张卡片切换，避免两个页面来回跳。 */
export default function LoginPage({ onAuthed }) {
  const [mode, setMode] = useState('login')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const isRegister = mode === 'register'

  const submit = async (e) => {
    e.preventDefault()
    setError('')
    if (!username.trim() || !password) {
      setError('请填写用户名和密码')
      return
    }
    setBusy(true)
    try {
      const data = isRegister
        ? await register(username.trim(), password, displayName.trim() || username.trim())
        : await login(username.trim(), password)
      onAuthed(data)
    } catch (err) {
      setError(err?.message || String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="auth-brand">
          <span className="auth-logo">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <rect x="2" y="4" width="20" height="14" rx="4" stroke="currentColor" strokeWidth="1.6" />
              <circle cx="9" cy="11" r="1.6" fill="currentColor" />
              <circle cx="15" cy="11" r="1.6" fill="currentColor" />
              <path d="M9 18v3M15 18v3" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
            </svg>
          </span>
          <span className="auth-brand-name">OcuPanel</span>
        </div>

        <h1 className="auth-title">{isRegister ? '创建个人账户' : '登录你的账户'}</h1>
        <p className="auth-sub">
          {isRegister
            ? '账户用于隔离你的对话记录与报告，仅你本人可见。'
            : '登录后可继续之前的对话与报告。'}
        </p>

        <form onSubmit={submit} className="auth-form">
          <label className="field">
            <span className="field-label">用户名</span>
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="至少 3 个字符"
              autoComplete="username"
              autoFocus
            />
          </label>

          {isRegister && (
            <label className="field">
              <span className="field-label">显示名称（可选）</span>
              <input
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                placeholder="界面上怎么称呼你"
              />
            </label>
          )}

          <label className="field">
            <span className="field-label">密码</span>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="至少 6 位"
              autoComplete={isRegister ? 'new-password' : 'current-password'}
            />
          </label>

          {error && <div className="auth-error">{error}</div>}

          <button type="submit" className="btn-primary auth-submit" disabled={busy}>
            {busy ? '处理中…' : isRegister ? '注册并登录' : '登录'}
          </button>
        </form>

        <div className="auth-switch">
          {isRegister ? '已有账户？' : '还没有账户？'}
          <button
            type="button"
            className="link-btn"
            onClick={() => {
              setMode(isRegister ? 'login' : 'register')
              setError('')
            }}
          >
            {isRegister ? '去登录' : '注册一个'}
          </button>
        </div>
      </div>
    </div>
  )
}
