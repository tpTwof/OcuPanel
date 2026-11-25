import { useEffect, useState } from 'react'
import { getCaseImage, getReportImage, getReportOriginal } from '../../api.js'
import { diseaseName, eyeName, formatTime } from '../../screening/caseForm.js'

export const VERIFICATION = { pass: '引用校验通过', rewritten: '引用修订后通过', rejected: '引用校验拒答', disabled: '引用校验关闭', error: '引用校验出错' }

export function ArchivedImage({ reportId, imgName, onAuthError, record }) {
  const [url, setUrl] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => () => { if (url) URL.revokeObjectURL(url) }, [url])
  return <div className="screening-archived-image">
    <button type="button" disabled={busy} onClick={async () => {
      if (url) { setUrl(null); return }
      setBusy(true); setError('')
      try {
        const download = record
          ? getCaseImage(record.id, record.revision, reportId, imgName ? 'overlay' : 'original')
          : imgName ? getReportImage(imgName) : getReportOriginal(reportId)
        const blob = await download
        setUrl(URL.createObjectURL(blob))
      }
      catch (failure) { if (!onAuthError?.(failure)) setError('图片不可用或原图校验失败。') }
      finally { setBusy(false) }
    }}>{busy ? '载入中…' : url ? '收起图片' : imgName ? '查看叠加图（非原图）' : '查看归档原图'}</button>
    {error && <p role="alert">{error}</p>}
    {url && <img src={url} alt={imgName ? '分割叠加图，非原图' : '归档眼底原图'} />}
  </div>
}

export function ResearchFindings({ report }) {
  return <div className="screening-research-findings">
    {Object.entries(report.visual_findings || {}).map(([disease, finding]) => <div key={disease}>
      <strong>{diseaseName(disease)}</strong>
      {finding.probability != null && <p>研究分类概率：{finding.probability}</p>}
      {finding.prompt_similarity_margin != null && <p>FLAIR 研究匹配分数：{finding.prompt_similarity_margin}（不表示有病或无病）</p>}
      {Object.entries(finding.measurements || {}).map(([name, value]) => <p key={name}>{name === 'area_equivalent_cdr' ? '面积等效杯盘比' : name}：{value}</p>)}
      {Object.entries(finding.model_sources || {}).map(([name, value]) => <p className="screening-source" key={name}>{name}：{value}</p>)}
    </div>)}
    {!Object.keys(report.visual_findings || {}).length && report.cup_to_disc != null && <p>历史面积等效杯盘比：{report.cup_to_disc}</p>}
  </div>
}

export default function AnalysisSources({ sources = [], onAuthError, record }) {
  if (!sources.length) return null
  return <details className="screening-disclosure">
    <summary>研究分析来源（{sources.length}）</summary>
    <p className="screening-muted">模型结果与人工评估分别保存，不自动转为诊断或处置计划。</p>
    {sources.map((source) => <article className="screening-source-card" key={source.report_id}>
      <h4>{eyeName(source.laterality)} · {source.report.source_metadata.filename || '历史分析'}</h4>
      <p>{VERIFICATION[source.report.verification?.status] || '无引用校验记录'}{source.report.rejected ? ' · 正文已拒答' : ''}</p>
      <p>采集：{source.captured_at ? formatTime(source.captured_at) : '时间缺失'} · {source.device || '设备缺失'}</p>
      <p>{source.original.status === 'available' ? '原图已归档，查看时校验完整性' : '原图缺失或完整性异常，待补齐'}</p>
      <ResearchFindings report={source.report} />
      {source.original.status === 'available' && <ArchivedImage reportId={source.report_id} onAuthError={onAuthError} record={record} />}
      {source.report.img_name && <ArchivedImage reportId={source.report_id} imgName={source.report.img_name} onAuthError={onAuthError} record={record} />}
      <details className="screening-disclosure"><summary>原报告与证据</summary>
        <p className="screening-plain-text">{source.report.summary}</p>
        <p className="screening-source">报告 {source.report_id} · {formatTime(source.report.created_at)}<br />来源哈希：{source.report_hash}</p>
        {source.report.evidence.map((item, index) => <p key={index}>[{item.index || index + 1}] {item.title || item.source}<br />{item.text}</p>)}
      </details>
    </article>)}
  </details>
}
