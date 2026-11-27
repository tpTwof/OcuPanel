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

// 正文里带〔未获资料支持〕标记时，提示读者这些句子没有出处
const ANNOTATED_HINT = '部分句子的资料出处未能确认，已在正文就地标注〔未获资料支持〕'

const BASIS = {
  case_fact: '病例输入', medical_knowledge: '参考资料', case_inference: '病例与资料共同支持',
  general_advice: '一般性建议', recommendation: '具体处置依据', software_limit: '软件能力边界', scope_limit: '资料边界'
}

// v2 检索记录里的缺口原因，直接展示给读者，避免只看到「未通过校验」。
const GAP_REASON = {
  no_result: '未检索到相关条款',
  material_type: '材料类型不足以支撑这个问题',
  applicability: '条款适用条件与本病例矛盾',
  applicability_unknown: '条款适用条件未核实（报告需写明前提）',
  topic_mismatch: '条款主题与问题不一致',
  disease_scope: '条款属于其他病种',
  tool_error: '检索工具故障',
  budget_exhausted: '达到检索预算，保留缺口',
  duplicate_query: '重复查询已跳过'
}

const MATERIAL = {
  guideline: '指南条款', consensus: '共识条款', expert_consensus: '专家共识',
  systematic_review: '系统综述', case_report: '病例资料',
  patient_education: '患者教育材料', reference_text: '参考资料', unknown: '类型未登记'
}

const REVIEW = {
  verified: '已核对', pending: '待复核', draft: '草稿', unknown: '未登记'
}

const LIMITED_HINT = {
  retrieval_failed: '知识库检索故障，未生成诊疗结论；诊断 PDF 暂不可用',
  no_evidence: '未检索到可核查的依据，仅保留输入资料',
  no_retrieval_requested: '本次只整理输入资料，未引入外部依据',
  retrieval_disabled: '知识检索未启用，正文无法引用外部依据'
}

export default function VerificationResult({ data, isChat }) {
  const [open, setOpen] = useState(false)
  if (!data || !data.status) return null

  const annotations = data.annotations || []
  const baseMeta = isChat && data.status === 'rejected'
    ? { tone: 'bad', label: '具体建议未通过核查', hint: '可补充病例信息或适用地区后再问' }
    : isChat && data.status === 'error'
    ? { tone: 'bad', label: '引用校验暂不可用', hint: '请稍后重试' }
    : data.status === 'limited' && LIMITED_HINT[data.reason]
    ? { ...STATUS.limited, hint: LIMITED_HINT[data.reason] }
    : STATUS[data.status] || STATUS.skipped
  // 正文里有就地标注时，任务条要说明哪些句子没出处，不能只显示「通过」
  const meta = annotations.length
    ? { ...baseMeta, hint: ANNOTATED_HINT }
    : baseMeta
  const fixed = data.fixed || []
  const remaining = data.remaining_issues || []
  const grounding = data.grounding || []
  const retrieval = data.retrieval || null
  const questions = retrieval?.questions || []
  const gaps = data.knowledge_gaps || []
  const failures = retrieval?.failures || []
  const review = data.applicability?.review_status || {}
  const reviewText = Object.entries(review)
    .map(([key, value]) => `${REVIEW[key] || key} ${value} 条`)
    .join('、')
  const deleted = data.deleted || 0
  const total = fixed.length + remaining.length + annotations.length
  const expandable = total > 0 || grounding.length > 0 || data.review_log?.length > 0
    || questions.length > 0 || gaps.length > 0
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
          {annotations.length > 0 && ` · 已标注 ${annotations.length} 处`}
          {grounding.length > 0 && ` · ${grounding.length} 条来源对照`}
          {questions.length > 0 && ` · 检索 ${questions.length} 问 / ${retrieval.evidence_count ?? 0} 条证据`}
          {gaps.length > 0 && ` · 知识缺口 ${gaps.length} 处`}
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
          {annotations.map((it, i) => (
            <div className="verify-item" key={`a${i}`}>
              <div className="verify-tag">已标注</div>
              <div className="verify-text">
                <div className="verify-old">{it.quote}</div>
                <div className="verify-reason">
                  资料未覆盖该表述，正文已就地标注〔未获资料支持〕
                  {it.reason && `：${it.reason}`}
                </div>
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
          {(retrieval || gaps.length > 0) && (
            <details>
              <summary>检索与覆盖（{questions.length} 个问题 · {gaps.length} 处缺口）</summary>
              {retrieval?.plan?.reason && (
                <div className="verify-reason">规划依据：{retrieval.plan.reason}</div>
              )}
              {questions.map((item, i) => (
                <div className="verify-item" key={`q${i}`}>
                  <div className={`verify-tag${item.answered ? '' : ' tag-bad'}`}>
                    {item.answered ? '已有依据' : '缺口'}
                  </div>
                  <div className="verify-text">
                    <div>{item.question}</div>
                    <div className="verify-reason">
                      {(item.gaps || []).map((gap) => GAP_REASON[gap] || gap).join('；')
                        || '已取得可用于核查的依据'}
                      {item.excluded?.length
                        ? `；排除 ${item.excluded.length} 条（${GAP_REASON[item.excluded[0].reason] || item.excluded[0].reason}）`
                        : ''}
                    </div>
                  </div>
                </div>
              ))}
              {retrieval?.budget_exhausted && <p>已达检索预算，剩余缺口保留，未继续搜索。</p>}
              {failures.length > 0 && (
                <p className="verify-reason">
                  检索故障 {failures.length} 次：{failures.map((item) => item.detail || item.kind).join('、')}。
                  故障不等同于没有相关证据。
                </p>
              )}
              {reviewText && (
                <p className="verify-reason">
                  来源审核状态：{reviewText}；引用校验通过不等于条款已通过临床审核。
                </p>
              )}
            </details>
          )}
          {gaps.length > 0 && (
            <details>
              <summary>知识缺口（{gaps.length} 处）</summary>
              {gaps.map((gap, i) => (
                <div className="verify-item" key={`gap${i}`}>
                  <div className="verify-tag">
                    {gap.kind === 'case_fact' ? '病例缺失'
                      : gap.kind === 'planner' ? '待补信息' : '语料缺口'}
                  </div>
                  <div className="verify-text">
                    <div>{gap.text || gap.question || '（未记录）'}</div>
                    {gap.reasons?.length > 0 && (
                      <div className="verify-reason">
                        {gap.reasons.map((reason) => GAP_REASON[reason] || reason).join('；')}
                      </div>
                    )}
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
