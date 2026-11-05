export default function ChatModeSwitcher({ mode, onChange, busy, onOpenAnalysis }) {
  const ophthalmic = mode === 'ophthalmic'

  return (
    <div className="chat-mode-controls">
      <button
        type="button"
        className={`btn-secondary chat-mode-analysis${ophthalmic ? '' : ' is-hidden'}`}
        disabled={busy || !ophthalmic}
        aria-hidden={!ophthalmic}
        tabIndex={ophthalmic ? 0 : -1}
        onClick={onOpenAnalysis}
      >
        影像与报告分析
      </button>
      <div className="chat-mode-switcher" role="group" aria-label="会话形态">
        {[
          { value: 'ophthalmic', label: '眼科助手' },
          { value: 'general', label: '普通聊天' }
        ].map((item) => (
          <button
            key={item.value}
            type="button"
            disabled={busy}
            aria-pressed={mode === item.value}
            className={mode === item.value ? 'is-selected' : ''}
            onClick={() => onChange(item.value)}
          >
            {item.label}
          </button>
        ))}
      </div>
    </div>
  )
}
