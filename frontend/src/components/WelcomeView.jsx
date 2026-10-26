const SUGGESTIONS = [
  '请帮我分析这份影像检查结果',
  '这张眼底图有什么异常？',
  '关于青光眼的治疗方案有哪些？',
  '你可以帮我生成一份临床报告吗？'
]

export default function WelcomeView({ user, onPick }) {
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
        <p className="welcome-sub">
          我是你的 AI 助手，可以帮你解答医学问题、分析报告、
          <br />
          提供专业建议。请在下方输入你的问题吧！
        </p>
        <div className="welcome-cards">
          {SUGGESTIONS.map((s) => (
            <button key={s} type="button" className="suggestion-card" onClick={() => onPick(s)}>
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
