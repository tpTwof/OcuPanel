import { useState } from 'react'

/**
 * 引用校验结果条（第 7 个智能体 CitationVerifier 的产出）。
 *
 * 数据结构来自后端 verification 字段：
 *   { status, rounds, initial_issues, fixed: [{quote,new,citations}],
 *     remaining_issues: [{quote,verdict,reason}], reason }
 *
 * 设计上不隐藏失败：状态为「部分修正 / 未通过」时默认展开，让读者看见
 * 哪句话没能改成功——这比给一个绿色通过标更诚实。
 */
const STATUS = {
  pass: { tone: 'ok', label: '引用校验通过', hint: '所有引用均能被参考资料支持' },
  rewritten: { tone: 'ok', label: '已修正', hint: '无依据的句子已删除或改写' },
  rejected: { tone: 'bad', label: '校验未通过，报告已中止', hint: '存在无法被资料支持的结论，未生成报告' },
  error: { tone: 'bad', label: '校验故障，报告已中止', hint: '无法确认内容可靠性，未生成报告' },
  disabled: { tone: 'muted', label: '校验已关闭', hint: 'VERIFY_ENABLED=0，内容未经核查' },
  skipped: { tone: 'muted', label: '未校验', hint: '缺少正文或参考资料' },
  rewritten_unresolved: { tone: 'bad', label: '校验未通过', hint: '仍有无依据内容' },
  unresolved: { tone: 'bad', label: '校验未通过', hint: '无法自动修正' }
}

export default function VerificationResult({ data }) {
  const [open, setOpen] = useState(false)
  if (!data || !data.status) return null

  const meta = STATUS[data.status] || STATUS.skipped
  const fixed = data.fixed || []
  const remaining = data.remaining_issues || []
  const deleted = data.deleted || 0
  const total = fixed.length + remaining.length
  const expandable = total > 0
  const forceOpen = data.status === 'rejected' || data.status === 'error'
  const shown = open || forceOpen

  return (
    <div className={`verify verify-${meta.tone}`}>
      <div
        className={`verify-head${expandable ? ' clickable' : ''}`}
        onClick={() => expandable && setOpen((v) => !v)}
      >
        <span className="verify-dot" />
        <span className="verify-label">{meta.label}</span>
        <span className="verify-hint">
          {meta.hint}
          {fixed.length > 0 && ` · 改写 ${fixed.length - deleted} 句`}
          {deleted > 0 && ` · 删除 ${deleted} 句`}
          {data.regenerated && ' · 已重新生成'}
          {remaining.length > 0 && ` · 遗留 ${remaining.length} 处`}
        </span>
        {expandable && <span className="verify-caret">{shown ? '收起' : '查看'}</span>}
      </div>

      {shown && (
        <div className="verify-body">
          {fixed.map((it, i) => (
            <div className="verify-item" key={`f${i}`}>
              <div className={`verify-tag${it.new ? '' : ' tag-bad'}`}>
                {it.new ? '改写' : '删除'}
              </div>
              <div className="verify-text">
                <div className="verify-old">{it.quote}</div>
                <div className="verify-new">{it.new || '（无依据，整句已删除）'}</div>
              </div>
            </div>
          ))}
          {remaining.map((it, i) => (
            <div className="verify-item" key={`r${i}`}>
              <div className="verify-tag tag-bad">{it.verdict === 'uncited' ? '无引用' : '不支撑'}</div>
              <div className="verify-text">
                <div className="verify-old">{it.quote}</div>
                <div className="verify-reason">{it.reason}</div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
