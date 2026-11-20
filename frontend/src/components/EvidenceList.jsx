import { useState } from 'react'

/**
 * 证据卡片：展示检索到的知识片段（标题 / 小节 / 来源 / 命中方式 / 原文）。
 * 数据结构由后端 /api/generate-report-content/ 的 evidence 字段给出。
 *
 * 注意 score 的语义随检索模式变化：hybrid 下是 RRF 融合相对分，不是余弦，
 * 直接当"相关度"显示会误导（实测某条真实余弦 0.81 却显示 0.37）。
 * 所以头部只标命中方式，三个原始分数放到展开后的明细里。
 */
const SOURCE_LABEL = {
  'bm25': '词面',
  vector: '语义',
  'bm25,vector': '混合',
  graph: '图检索'
}

// Older conversations may contain graph labels saved before the display change.
const formatGraphLabel = (label) => label.replace(/\s*\u00a7\s*/g, ' · ')

export default function EvidenceList({ items, evidencePrefix }) {
  const [openId, setOpenId] = useState(null)
  if (!items || items.length === 0) return null

  return (
    <div className="evidence">
      <div className="evidence-head">
        参考资料 <span className="evidence-count">{items.length}</span>
        <span className="evidence-hint">点击展开证据与出处</span>
      </div>

      {items.map((item, index) => {
        const number = item.index ?? index + 1
        const isOpen = openId === number
        const scores = []
        if (typeof item.vector === 'number') scores.push(`语义 ${item.vector.toFixed(2)}`)
        if (typeof item.bm25 === 'number') scores.push(`词面 ${item.bm25.toFixed(1)}`)
        if (typeof item.rrf === 'number') scores.push(`融合 ${item.rrf.toFixed(3)}`)
        return (
          <div className="evidence-item" key={item.id || index}
               id={evidencePrefix ? `${evidencePrefix}-${item.index ?? index + 1}` : undefined}>
            <button
              type="button"
              className="evidence-row"
              aria-expanded={isOpen}
              onClick={() => setOpenId(isOpen ? null : number)}
            >
              <span className="evidence-index">[{item.index ?? index + 1}]</span>
              {item.lang && (
                <span className={`evidence-lang lang-${item.lang}`}>
                  {item.lang === 'en' ? 'EN' : '中'}
                </span>
              )}
              <span className="evidence-title">
                {item.title}
                {item.section ? ` · ${item.section}` : ''}
              </span>
              {item.sources ? (
                <span className="evidence-source-tag">
                  {SOURCE_LABEL[item.sources] || item.sources.split(',').map(source => SOURCE_LABEL[source] || source).join(' + ')}
                </span>
              ) : (
                typeof item.score === 'number' && (
                  <span className="evidence-score">{item.score.toFixed(2)}</span>
                )
              )}
              <span className="evidence-caret">{isOpen ? '收起' : '展开'}</span>
            </button>

            {isOpen && (
              <div className="evidence-body">
                <div className="evidence-source">
                  来源：{item.source}
                  {scores.length > 0 && <span className="evidence-scores"> · {scores.join(' · ')}</span>}
                </div>
                {(item.scope || item.version || item.jurisdiction || item.url?.startsWith('https://')) && (
                  <div className="evidence-source">
                    {[item.jurisdiction, item.version, item.scope].filter(Boolean).join(' · ')}
                    {item.url?.startsWith('https://') && (
                      <> · <a href={item.url} target="_blank" rel="noopener noreferrer">查看原始出处</a></>
                    )}
                  </div>
                )}
                {item.graph_path?.length > 0 && (
                  <div className="evidence-source">
                    检索路径：{formatGraphLabel(item.graph_path[0].source)}
                    {item.graph_path.map((step, i) => (
                      <span key={i}> → {step.relation} → {formatGraphLabel(step.target)}</span>
                    ))}
                  </div>
                )}
                <pre className="evidence-text">{item.text}</pre>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
