import { useEffect, useState } from 'react'
import { clearLlmConfig, fetchLlmPresets, fetchUsage, saveLlmConfig, testLlmConfig } from '../api.js'

/**
 * 个人设置：管理自己的 LLM API。
 *
 * 两条产品规则：
 * 1. 已保存的 key 不在界面上回显明文，只给首尾片段；留空保存 = 沿用旧 key。
 * 2. 先「测试连通」再保存。配置错了如果直接存下来，每次生成都要失败一遍才知道。
 */
export default function SettingsView({ user, llm, onSaved, onClose, onLogout }) {
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState(llm?.base_url || '')
  const [model, setModel] = useState(llm?.model || '')
  const [presets, setPresets] = useState([])
  const [defaults, setDefaults] = useState({ base_url: '', model: '' })
  const [usage, setUsage] = useState(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)

  useEffect(() => {
    fetchLlmPresets()
      .then((d) => {
        setPresets(d.presets || [])
        setDefaults(d.defaults || {})
        // 没填过就用服务器默认值预填，省一次手打
        if (!llm?.base_url && d.defaults?.base_url) setBaseUrl(d.defaults.base_url)
        if (!llm?.model && d.defaults?.model) setModel(d.defaults.model)
      })
      .catch(() => {})
    fetchUsage().then(setUsage).catch(() => {})
  }, [llm])

  const body = () => ({ api_key: apiKey.trim(), base_url: baseUrl.trim(), model: model.trim() })

  const doTest = async () => {
    setBusy(true)
    setMsg(null)
    try {
      const r = await testLlmConfig(body())
      setMsg({
        kind: 'ok',
        text: `连通成功，模型回复「${r.reply || 'OK'}」${
          r.prompt_tokens != null ? `（本次消耗 ${r.prompt_tokens + (r.completion_tokens || 0)} tokens）` : ''
        }`
      })
    } catch (err) {
      setMsg({ kind: 'err', text: err?.message || String(err) })
    } finally {
      setBusy(false)
    }
  }

  const doSave = async () => {
    setBusy(true)
    setMsg(null)
    try {
      const saved = await saveLlmConfig(body())
      setApiKey('')
      setMsg({ kind: 'ok', text: '已保存。之后的生成与追问都会使用这套配置。' })
      onSaved(saved)
    } catch (err) {
      setMsg({ kind: 'err', text: err?.message || String(err) })
    } finally {
      setBusy(false)
    }
  }

  const doClear = async () => {
    if (!confirm('确定清除已保存的 API 配置？清除后需要重新填写才能生成报告。')) return
    setBusy(true)
    try {
      await clearLlmConfig()
      setApiKey('')
      setMsg({ kind: 'ok', text: '已清除。' })
      onSaved(null)
    } catch (err) {
      setMsg({ kind: 'err', text: err?.message || String(err) })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="settings-page">
      <div className="chat-head">
        <h2>个人设置</h2>
        {onClose && (
          <button type="button" className="btn-ghost" onClick={onClose}>
            返回对话
          </button>
        )}
      </div>

      <div className="settings-scroll">
        <section className="settings-card">
          <h3>账户</h3>
          <div className="kv">
            <span className="kv-key">用户名</span>
            <span className="kv-val">{user.username}</span>
          </div>
          <div className="kv">
            <span className="kv-key">显示名称</span>
            <span className="kv-val">{user.display_name || '—'}</span>
          </div>
          {usage && (
            <div className="kv">
              <span className="kv-key">使用情况</span>
              <span className="kv-val">
                {usage.conversations} 个对话 · {usage.reports} 份报告
                {usage.rejected > 0 ? `（其中 ${usage.rejected} 次因校验未通过被拒答）` : ''}
              </span>
            </div>
          )}

          {onLogout && (
            <div className="settings-logout">
              <p className="settings-logout-hint">
                退出只清除本机登录态，对话与报告仍保存在服务端，重新登录后还在。
              </p>
              <button type="button" className="btn-danger-ghost" onClick={onLogout}>
                退出登录
              </button>
            </div>
          )}
        </section>

        <section className="settings-card">
          <h3>LLM API 配置</h3>
          <p className="settings-hint">
            你自己的 API Key 只用于你的报告与问答，服务端加密存储，界面不会回显明文。
            {llm?.has_key && (
              <>
                {' '}
                当前已配置：<code>{llm.api_key_masked}</code>（{llm.model}）
              </>
            )}
          </p>

          <label className="field">
            <span className="field-label">
              API Key {llm?.has_key && <em className="field-em">留空则沿用已保存的 key</em>}
            </span>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={llm?.has_key ? llm.api_key_masked : 'sk-...'}
              autoComplete="off"
            />
          </label>

          <label className="field">
            <span className="field-label">接口地址（Base URL）</span>
            <input
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder="https://api.deepseek.com"
            />
          </label>

          {presets.length > 0 && (
            <div className="preset-row">
              {presets.map((p) => (
                <button
                  key={p.label}
                  type="button"
                  className="chip-btn"
                  onClick={() => {
                    setBaseUrl(p.base_url)
                    if (p.models?.[0]) setModel(p.models[0])
                  }}
                >
                  {p.label}
                </button>
              ))}
            </div>
          )}

          <label className="field">
            <span className="field-label">模型</span>
            <input
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="deepseek-chat"
              list="model-options"
            />
            <datalist id="model-options">
              {presets.flatMap((p) => (p.models || []).map((m) => <option key={m} value={m} />))}
            </datalist>
          </label>

          {msg && <div className={`settings-msg ${msg.kind}`}>{msg.text}</div>}

          <div className="settings-actions">
            <button type="button" className="btn-secondary" onClick={doTest} disabled={busy}>
              {busy ? '请稍候…' : '测试连通'}
            </button>
            <button type="button" className="btn-primary" onClick={doSave} disabled={busy}>
              保存
            </button>
            {llm?.has_key && (
              <button type="button" className="btn-danger-ghost" onClick={doClear} disabled={busy}>
                清除配置
              </button>
            )}
          </div>

          {defaults.base_url && (
            <p className="settings-foot">
              服务端默认：{defaults.base_url} / {defaults.model || '未指定'}。不填时可点上方预设快速填。
            </p>
          )}
        </section>
      </div>
    </div>
  )
}
