function Icon({ name }) {
  const paths = {
    chat: 'M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v7a2.5 2.5 0 0 1-2.5 2.5H9l-4 3v-3.2A2.5 2.5 0 0 1 4 12.5z',
    report: 'M7 3h7l4 4v14H7zM14 3v4h4M10 12h5M10 16h5',
    plus: 'M12 5v14M5 12h14',
    user: 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21c0-3.3 3.6-6 8-6s8 2.7 8 6'
  }
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d={paths[name]} stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function formatTime(ts) {
  const d = new Date(ts * 1000)
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

export default function Sidebar({
  user,
  conversations,
  activeId,
  view,
  onNewChat,
  onOpenReport,
  onSelectConversation,
  onDeleteConversation,
  onOpenSettings,
  onLogout
}) {
  return (
    <aside className="sidebar-nav">
      <div className="nav-brand">
        <span className="nav-brand-logo">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <rect x="2" y="4" width="20" height="14" rx="4" stroke="currentColor" strokeWidth="1.6" />
            <circle cx="9" cy="11" r="1.6" fill="currentColor" />
            <circle cx="15" cy="11" r="1.6" fill="currentColor" />
            <path d="M9 18v3M15 18v3" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          </svg>
        </span>
        OcuPanel
      </div>

      <button
        type="button"
        className={`nav-action${view === 'chat' && !activeId ? ' active' : ''}`}
        onClick={onNewChat}
      >
        <Icon name="plus" />
        新建对话
      </button>

      <button
        type="button"
        className={`nav-action${view === 'report' ? ' active' : ''}`}
        onClick={onOpenReport}
      >
        <Icon name="report" />
        生成报告
      </button>

      <div className="nav-divider" />

      <div className="nav-section-title">最近对话</div>
      <div className="conversation-list">
        {conversations.length === 0 && <div className="conversation-empty">还没有对话</div>}
        {conversations.map((c) => (
          <div
            key={c.id}
            className={`conversation-item${c.id === activeId && view === 'chat' ? ' active' : ''}`}
            onClick={() => onSelectConversation(c.id)}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => e.key === 'Enter' && onSelectConversation(c.id)}
          >
            <Icon name="chat" />
            <div className="conversation-meta">
              <div className="conversation-title">{c.title}</div>
              <div className="conversation-time">{formatTime(c.updated_at)}</div>
            </div>
            <button
              type="button"
              className="conversation-delete"
              title="删除会话"
              onClick={(e) => {
                e.stopPropagation()
                onDeleteConversation(c.id)
              }}
            >
              ×
            </button>
          </div>
        ))}
      </div>

      <div className="nav-user">
        <button
          type="button"
          className="nav-user-main"
          onClick={onOpenSettings}
          title="个人设置"
        >
          <span className="nav-user-avatar">
            {(user.display_name || user.username || '?').slice(0, 1)}
          </span>
          <span className="nav-user-name">{user.display_name || user.username}</span>
        </button>
        <button
          type="button"
          className="nav-user-logout"
          onClick={onLogout}
          title="退出登录"
          aria-label="退出登录"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path
              d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3M10 8l-4 4 4 4M6 12h9"
              stroke="currentColor"
              strokeWidth="1.7"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </button>
      </div>
    </aside>
  )
}
