import { useState } from 'react'

/**
 * 引用校验结果条（第 7 个智能体 CitationVerifier 的产出）。
 *
 * 数据结构来自后端 verification 字段：
 *   { status, rounds, initial_issues, fixed: [{quote,new,citations}],
 *     remaining_issues: [{quote,verdict,reason}], reason }
 *
 * 拒答和错误默认展开；通过后的删改按需查看，局部删除须经全文复核。
 */
const STATUS = {
  pass: { tone: 'ok', label: '引用校验通过', hint: '自动核查未发现正文引用问题' },
  rewritten: { tone: 'ok', label: '引用校验通过（已修订）', hint: '交付正文已重新核查，删改记录可展开查看' },
  rejected: { tone: 'bad', label: '校验未通过，报告已中止', hint: '存在无法被资料支持的结论，未生成报告' },
  error: { tone: 'bad', label: '校验故障，报告已中止', hint: '无法确认内容可靠性，未生成报告' },
  limited: { tone: 'muted', label: '仅提供病例资料摘要', hint: '诊疗结论未完成核查，诊断 PDF 暂不可用' },
  disabled: { tone: 'muted', label: '校验已关闭', hint: 'VERIFY_ENABLED=0，内容未经核查' },
  skipped: { tone: 'muted', label: '未校验', hint: '缺少正文或参考资料' },
  no_claims: { tone: 'muted', label: '本轮未引用知识库', hint: '未发现需要依据的具体建议' },
  rewritten_unresolved: { tone: 'bad', label: '校验未通过', hint: '仍有无依据内容' },
  unresolved: { tone: 'bad', label: '校验未通过', hint: '无法自动修正' }
}

const BASIS = {
  case_fact: '病例输入', medical_knowledge: '参考资料', case_inference: '病例与资料共同支持',
  general_advice: '一般性建议', recommendation: '具体处置依据', software_limit: '软件能力边界', scope_limit: '资料边界'
}

export default function VerificationResult({ data, isChat }) {
  const [open, setOpen] = useState(false)
  if (!data || !data.status) return null

  const meta = isChat && data.status === 'rejected'
    ? { tone: 'bad', label: '具体建议未通过核查', hint: '可补充病例信息或适用地区后再问' }
    : isChat && data.status === 'error'
    ? { tone: 'bad', label: '引用校验暂不可用', hint: '请稍后重试' }
    : STATUS[data.status] || STATUS.skipped
  const fixed = data.fixed || []
  const remaining = data.remaining_issues || []
  const grounding = data.grounding || []
  const deleted = data.deleted || 0
  const total = fixed.length + remaining.length
  const expandable = total > 0 || grounding.length > 0 || data.review_log?.length > 0
  const forceOpen = ['rejected', 'error', 'limited'].includes(data.status)
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
          {data.adjudicated && ' · 来源归类已复核'}
          {data.local_cleanup && ' · 已移除非核心说明'}
          {remaining.length > 0 && ` · 遗留 ${remaining.length} 处`}
          {grounding.length > 0 && ` · ${grounding.length} 条来源对照`}
        </span>
        {expandable && <span className="verify-caret">{shown ? '收起' : '查看'}</span>}
      </div>

      {shown && (
        <div className="verify-body">
          {data.status === 'limited' && <p>以下为未交付诊疗草稿的核查记录，当前正文仅保留输入资料。</p>}
          {fixed.map((it, i) => (
            <div className="verify-item" key={`f${i}`}>
              <div className={`verify-tag${it.new ? '' : ' tag-bad'}`}>
                {it.new ? '改写' : it.method === 'local_omission' ? '局部删减' : '删除'}
              </div>
              <div className="verify-text">
                <div className="verify-old">{it.quote}</div>
                <div className="verify-new">{it.new || '（无依据，整句已删除）'}</div>
                {it.reason && <div className="verify-reason">{BASIS[it.basis] && `${BASIS[it.basis]}：`}{it.reason}</div>}
              </div>
            </div>
          ))}
          {remaining.map((it, i) => (
            <div className="verify-item" key={`r${i}`}>
              <div className="verify-tag tag-bad">{it.origin === 'citation_control' ? '引用待修正' : it.impact === 'local' ? '局部问题' : '核心待核实'}</div>
              <div className="verify-text">
                <div className="verify-old">{it.quote}</div>
                <div className="verify-reason">{it.reason}</div>
              </div>
            </div>
          ))}
          {grounding.length > 0 && (
            <details>
              <summary>通过内容的来源对照（{grounding.length} 条）</summary>
              {grounding.map((it, i) => (
                <div className="verify-item" key={`g${i}`}>
                  <div className="verify-tag">{BASIS[it.basis] || '来源对照'}</div>
                  <div className="verify-text">
                    <div>{it.quote}</div>
                    {it.reason && <div className="verify-reason">{it.reason}</div>}
                    {(it.sources || []).map((source, j) => (
                      <div className="verify-reason" key={`s${j}`}>
                        {source.kind === 'evidence' ? `资料 [${source.index}]` : source.kind === 'case' ? '原始病例输入' : '软件能力声明'}：{source.quote}
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </details>
          )}
          {data.review_log?.length > 0 && (
            <details>
              <summary>校验过程（{data.review_log.length} 次记录）</summary>
              <p>病例输入与参考资料已关联本次校验版本；病例来源核对不等于验证原始记录的真实性。</p>
              {data.review_log.map((review, i) => (
                <div className="verify-reason" key={`v${i}`}>
                  第 {i + 1} 次：{review.issue_count == null ? '校验响应未完成' : `发现 ${review.issue_count} 处问题`}
                </div>
              ))}
            </details>
          )}
        </div>
      )}
    </div>
  )
}
