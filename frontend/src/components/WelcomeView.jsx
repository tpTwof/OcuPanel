import ChatModeSwitcher from './ChatModeSwitcher.jsx'

const GENERAL_SUGGESTIONS = ['帮我制定一份学习计划', '帮我修改一段文字', '解释一个我不熟悉的概念', '一起讨论一个想法']
const OPHTHALMIC_SUGGESTIONS = ['杯盘比是什么意思？', '眼底图分析还需要什么资料？', '如何理解眼压检查结果？', '解释报告中的 OCT 和 RNFL']

export default function WelcomeView({ user, onPick, mode, onModeChange, busy, onOpenAnalysis }) {
  const name = user.display_name || user.username
  return (
    <div className="welcome">
      <div className="welcome-hero">
        <div className="welcome-robot" aria-hidden="true">
          <svg width="86" height="86" viewBox="0 0 96 96" fill="none">
            <ellipse cx="48" cy="86" rx="26" ry="5" fill="#dbeafe" />
            <rect x="18" y="26" width="60" height="48" rx="18" fill="#eff6ff" stroke="#bfdbfe" strokeWidth="1.5" />
            <rect x="30" y="38" width="36" height="24" rx="10" fill="#ffffff" stroke="#93c5fd" strokeWidth="1.5" />
            <circle cx="41" cy="50" r="3.4" fill="#3b82f6" />
            <circle cx="55" cy="50" r="3.4" fill="#3b82f6" />
            <path d="M48 26V16" stroke="#bfdbfe" strokeWidth="2" strokeLinecap="round" />
            <circle cx="48" cy="13" r="3.2" fill="#93c5fd" />
            <path d="M28 74v8M68 74v8" stroke="#bfdbfe" strokeWidth="2" strokeLinecap="round" />
          </svg>
        </div>
        <h1 className="welcome-title">你好，{name}！</h1>
        <ChatModeSwitcher
          mode={mode}
          onChange={onModeChange}
          busy={busy}
          onOpenAnalysis={onOpenAnalysis}
        />
        <p className="welcome-sub">
          {mode === 'ophthalmic'
            ? '眼科助手可以解释检查结果，也可以结合眼底图片与临床记录进行分析。'
            : '从一个问题开始，可以写作、学习、规划，也可以切换为眼科助手。'}
        </p>
        <div className="welcome-cards">
          {(mode === 'ophthalmic' ? OPHTHALMIC_SUGGESTIONS : GENERAL_SUGGESTIONS).map((s) => (
            <button key={s} type="button" className="suggestion-card" disabled={busy} onClick={() => onPick(s)}>
              <span className="suggestion-icon" aria-hidden="true">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                  <path
                    d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v7a2.5 2.5 0 0 1-2.5 2.5H9l-4 3v-3.2A2.5 2.5 0 0 1 4 12.5z"
                    stroke="currentColor"
                    strokeWidth="1.6"
                    strokeLinejoin="round"
                  />
                </svg>
              </span>
              <span className="suggestion-text">{s}</span>
              <span className="suggestion-arrow">›</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
