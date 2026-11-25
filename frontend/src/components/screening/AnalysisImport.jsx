import { useEffect, useRef, useState } from 'react'
import { confirmAnalysisImport, getSavedReport, listSavedReports, previewAnalysisImport } from '../../api.js'
import { diseaseName, eyeName, formatTime, importExamination, STATUS } from '../../screening/caseForm.js'
import { ArchivedImage, ResearchFindings, VERIFICATION } from './AnalysisSources.jsx'

function localTime(value) {
  if (!value) return ''
  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return ''
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16)
}

export default function AnalysisImport({ record, examination, initialReportId, preserveTasks, onSaved, onClose, onAuthError, onDirtyChange }) {
  const [reports, setReports] = useState([])
  const [bindings, setBindings] = useState([])
  const [preview, setPreview] = useState(null)
  const [notePolicy, setNotePolicy] = useState(examination.note.trim() ? 'keep' : 'append')
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const [eyesConfirmed, setEyesConfirmed] = useState(false)
  const lock = useRef(false)
  const requestKey = useRef(null)
  const dialogRef = useRef(null)
  const edited = bindings.length > 0
  useEffect(() => { onDirtyChange?.('analysis-import', edited); return () => onDirtyChange?.('analysis-import', false) }, [edited, onDirtyChange])
  useEffect(() => { dialogRef.current?.focus() }, [])

  useEffect(() => {
    let active = true
    async function load() {
      try {
        const items = await listSavedReports()
        if (!active) return
        setReports(items)
        if (initialReportId) {
          const report = await getSavedReport(initialReportId)
          if (active) setBindings([makeBinding(report)])
        }
      } catch (failure) { if (active && !onAuthError(failure)) setError(failure.message) }
      finally { if (active) setBusy(false) }
    }
    load()
    return () => { active = false }
  }, [initialReportId, onAuthError])

  function makeBinding(report) {
    const previous = record?.analysis_sources?.find((source) => source.report_id === report.id)
    return { report, laterality: previous?.laterality || report.source_metadata.laterality || '',
      captured_at: localTime(previous?.captured_at || report.source_metadata.captured_at), device: previous?.device || report.source_metadata.device || '' }
  }

  async function run(operation) {
    if (lock.current) return
    lock.current = true; setBusy(true); setError('')
    try { await operation() }
    catch (failure) { if (!onAuthError(failure)) setError(failure instanceof TypeError ? '连接失败，选择已保留。请恢复连接后重试。' : failure.message) }
    finally { lock.current = false; setBusy(false) }
  }

  function update(index, patch) {
    setBindings((items) => items.map((item, position) => position === index ? { ...item, ...patch } : item))
  }

  return <div className="screening-dialog-backdrop">
    <section ref={dialogRef} tabIndex={-1} role="dialog" aria-modal="true" aria-labelledby="analysis-import-title" className="screening-dialog screening-import-dialog"
      onKeyDown={(event) => {
        if (event.key === 'Escape' && !busy) onClose()
        if (event.key === 'Tab') {
          const controls = [...event.currentTarget.querySelectorAll('button:not(:disabled), input:not(:disabled), select:not(:disabled)')].filter((element) => element.getClientRects().length)
          if (!controls.length) event.preventDefault()
          if (controls.length && event.target === (event.shiftKey ? controls[0] : controls[controls.length - 1])) {
            event.preventDefault(); (event.shiftKey ? controls[controls.length - 1] : controls[0]).focus()
          }
        }
      }}>
      <header className="screening-case-header"><div><h2 id="analysis-import-title">{preview ? '确认导入预览' : '从已保存分析导入'}</h2>
        <p className="screening-muted">{record ? `补充 ${examination.encounter_id} · 基于 v${record.revision}` : `创建草稿 ${examination.encounter_id}`}</p></div>
        <button type="button" disabled={busy} onClick={onClose} autoFocus>关闭</button>
      </header>
      {error && <p role="alert" className="screening-error">{error}</p>}
      {busy && <p role="status">正在处理…</p>}
      {!preview ? <>
        <label>选择分析（最多两份）<select disabled={busy || bindings.length >= 2} value="" onChange={(event) => {
          const id = event.target.value
          if (id) run(async () => {
            const report = await getSavedReport(id)
            setBindings((items) => [...items, makeBinding(report)])
          })
        }}><option value="">选择当前账号的分析存档</option>
          {reports.filter((item) => !bindings.some((binding) => binding.report.id === item.id)).map((item) => <option value={item.id} key={item.id}>
            {item.source_metadata.filename || '历史分析'} · {formatTime(item.created_at)} · {item.rejected ? '已拒答' : VERIFICATION[item.verification.status] || '校验未知'}
          </option>)}
        </select></label>
        {!busy && !reports.length && <p>暂无分析存档，请先在眼科分析中生成报告。</p>}
        {bindings.map((binding, index) => <article className="screening-source-card" key={binding.report.id}>
          <header className="screening-case-header"><strong>{binding.report.source_metadata.filename || '历史分析'}</strong>
            <button disabled={busy} onClick={() => setBindings((items) => items.filter((_, position) => position !== index))}>移除选择</button></header>
          <label>绑定眼别<select disabled={busy} value={binding.laterality} onChange={(event) => update(index, { laterality: event.target.value })}>
            <option value="">请明确选择眼别</option><option value="right">右眼</option><option value="left">左眼</option>
          </select></label>
          <div className="screening-fields">
            <label>采集时间（缺失可留空）<input type="datetime-local" disabled={busy} value={binding.captured_at} onChange={(event) => update(index, { captured_at: event.target.value })} /></label>
            <label>采集设备（缺失可留空）<input disabled={busy} maxLength={500} value={binding.device} onChange={(event) => update(index, { device: event.target.value })} /></label>
          </div>
          <p className="screening-muted">{binding.report.original.status === 'available' ? '原图已归档' : '原图缺失，仅保留研究信息'} · {VERIFICATION[binding.report.verification.status] || '无校验记录'}</p>
          <details className="screening-disclosure"><summary>查看研究结果</summary><ResearchFindings report={binding.report} />
            {binding.report.original.status === 'available' && <ArchivedImage reportId={binding.report.id} onAuthError={onAuthError} />}
          </details>
        </article>)}
        <label>病例备注如何合并<select disabled={busy} value={notePolicy} onChange={(event) => setNotePolicy(event.target.value)}>
          <option value="keep">保留当前备注</option><option value="append">追加分析中的临床记录</option><option value="replace">使用分析中的临床记录替换</option>
        </select></label>
        <p className="screening-muted">人工评估与所见保持原样；新增任务保持待评估。导入不会签发或自动转诊。</p>
        <button className="screening-primary" disabled={busy || !bindings.length} onClick={() => run(async () => {
          if (bindings.some((binding) => !binding.laterality)) throw new Error('请为每份分析明确选择左右眼。')
          if (new Set(bindings.map((binding) => binding.laterality)).size !== bindings.length) throw new Error('每只眼本次只能绑定一份分析。')
          const payload = { examination: importExamination(examination, bindings.map((binding) => binding.report), preserveTasks), note_policy: notePolicy, bindings: bindings.map((binding) => ({ report_id: binding.report.id, laterality: binding.laterality,
            captured_at: binding.captured_at ? new Date(binding.captured_at).toISOString() : null, device: binding.device })) }
          if (record) { payload.case_id = record.id; payload.expected_revision = record.revision }
          setPreview(await previewAnalysisImport(payload)); setConfirmed(false); setEyesConfirmed(false); requestKey.current = crypto.randomUUID()
        })}>预览合并结果</button>
      </> : <>
        {preview.warnings.length > 0 && <div className="screening-notice">{preview.warnings.map((warning) => <p key={warning}>{warning}</p>)}</div>}
        <div className="screening-eyes">{preview.candidate.examination.eyes.map((eye) => <article className="screening-eye" key={eye.laterality}>
          <h3>{eyeName(eye.laterality)}</h3>{eye.tasks.map((task) => <p key={task.disease}>{diseaseName(task.disease)} · {STATUS[task.status]}<br />下一步：{task.next_step}</p>)}
        </article>)}</div>
        <p className="screening-plain-text">合并后备注：{preview.candidate.examination.note || '空'}</p>
        <p>{preview.no_changes ? '来源已存在，本次确认不会新增版本。' : '确认后保存为新的待复核草稿；旧签发与转诊历史保留。'}</p>
        <label className="screening-check"><input type="checkbox" disabled={busy} checked={eyesConfirmed} onChange={(event) => setEyesConfirmed(event.target.checked)} />已核对所选分析与左右眼对应关系</label>
        <label className="screening-check"><input type="checkbox" disabled={busy} checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />确认来源为合成/演示数据，仅用于流程演练</label>
        <div className="screening-actions">
          <button disabled={busy} onClick={() => setPreview(null)}>返回调整</button>
          <button className="screening-primary" disabled={busy || !confirmed || !eyesConfirmed} onClick={() => run(async () => {
            const saved = await confirmAnalysisImport(preview.preview_id, { idempotency_key: requestKey.current, synthetic_rehearsal_confirmed: confirmed, laterality_confirmed: eyesConfirmed })
            await onSaved(saved, preview.no_changes)
          })}>确认导入草稿</button>
        </div>
      </>}
    </section>
  </div>
}
