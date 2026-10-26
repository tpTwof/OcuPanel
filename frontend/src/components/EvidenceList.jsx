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
  'bm25,vector': '混合'
}

export default function EvidenceList({ items }) {
  const [openId, setOpenId] = useState(null)
  if (!items || items.length === 0) return null

  return (
    <div className="evidence">
      <div className="evidence-head">
        参考资料 <span className="evidence-count">{items.length}</span>
        <span className="evidence-hint">来自本地知识库，点击展开原文</span>
      </div>

      {items.map((item, index) => {
        const isOpen = openId === item.id
        const scores = []
        if (typeof item.vector === 'number') scores.push(`语义 ${item.vector.toFixed(2)}`)
        if (typeof item.bm25 === 'number') scores.push(`词面 ${item.bm25.toFixed(1)}`)
        if (typeof item.rrf === 'number') scores.push(`融合 ${item.rrf.toFixed(3)}`)
        return (
          <div className="evidence-item" key={item.id || index}>
            <button
              type="button"
              className="evidence-row"
              onClick={() => setOpenId(isOpen ? null : item.id)}
            >
              <span className="evidence-index">[{item.index ?? index + 1}]</span>
              {item.lang && (
                <span className={`evidence-lang lang-${item.lang}`}>
                  {item.lang === 'en' ? 'EN' : '中'}
                </span>
              )}
              <span className="evidence-title">
                {item.title}
                {item.section ? ` §${item.section}` : ''}
              </span>
              {item.sources ? (
                <span className="evidence-source-tag">{SOURCE_LABEL[item.sources] || item.sources}</span>
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
                <pre className="evidence-text">{item.text}</pre>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
