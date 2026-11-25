import { useCallback, useEffect, useRef, useState } from 'react'
import {
  createScreeningCase, exportScreeningCase, exportScreeningPdf,
  getScreeningCase, getScreeningContext, getScreeningSite, listScreeningCases, mutateScreeningCase
} from '../api.js'
import { bilateralExample, createExamination, mergeCaseList, STAGE, upsertCase, validateExamination } from '../screening/caseForm.js'
import CaseForm from './screening/CaseForm.jsx'
import CaseActions, { ReferralCard } from './screening/CaseActions.jsx'
import { CaseHistory, EyeSummary, VersionExplanation } from './screening/CaseDetails.jsx'
import AnalysisImport from './screening/AnalysisImport.jsx'
import AnalysisSources from './screening/AnalysisSources.jsx'
import ExamGuide from './screening/ExamGuide.jsx'
import { followupCases } from '../screening/followup.js'

function readableError(error) {
  if (error instanceof TypeError) return '无法确认请求结果。请恢复连接后刷新查询，已填写的内容仍保留。'
  try {
    const details = JSON.parse(error.message)
    if (Array.isArray(details)) return details.map((item) => item.msg.replace(/^Value error, /, '')).join('；')
  } catch { /* Ordinary API errors already have a readable message. */ }
  return error.message || '操作失败，请稍后重试。'
}

export default function ScreeningView({ user, onAuthError, onRegisterLeaveGuard, initialReportId }) {
  const [cases, setCases] = useState([])
  const [selected, setSelected] = useState(null)
  const [currentRevision, setCurrentRevision] = useState(null)
  const [form, setForm] = useState(null)
  const [reason, setReason] = useState('')
  const [loading, setLoading] = useState(true)
  const [site, setSite] = useState(null)
  const [followupFilter, setFollowupFilter] = useState('all')
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [refreshAvailable, setRefreshAvailable] = useState(false)
  const [notice, setNotice] = useState('')
  const [context, setContext] = useState(null)
  const [explanationOpen, setExplanationOpen] = useState(false)
  const [pendingNavigation, setPendingNavigation] = useState(null)
  const [actionDrafts, setActionDrafts] = useState({})
  const [actionEpoch, setActionEpoch] = useState(0)
  const [importTarget, setImportTarget] = useState(null)
  const recordDraft = useCallback((key, value) => setActionDrafts((drafts) => drafts[key] === value ? drafts : { ...drafts, [key]: value }), [])
  const requestKeys = useRef(new Map())
  const operationLock = useRef(false)
  const formBaseline = useRef('')
  const feedbackRef = useRef(null)
  const historical = selected && selected.revision !== currentRevision
  const owner = user.display_name || user.username
  const dirty = Boolean(form && (JSON.stringify(form) !== formBaseline.current || reason.trim())) || Object.values(actionDrafts).some(Boolean)

  useEffect(() => {
    if (site && initialReportId) setImportTarget({ record: null, examination: newExam(), reportId: initialReportId })
  }, [initialReportId, site])

  useEffect(() => {
    let active = true
    Promise.all([listScreeningCases(), getScreeningSite()]).then(([items, profile]) => {
      if (active) {
        setSite(profile)
        setCases((current) => mergeCaseList(current, items))
      }
    }).catch((failure) => {
      if (active && !onAuthError(failure)) reportError(readableError(failure), true)
    }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [onAuthError])

  useEffect(() => {
    setContext(null)
    setExplanationOpen(false)
  }, [selected?.id, selected?.revision])

  useEffect(() => {
    if (notice || error) feedbackRef.current?.focus()
  }, [notice, error])

  useEffect(() => {
    if (!dirty) return
    const warn = (event) => { event.preventDefault(); event.returnValue = '' }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])

  useEffect(() => {
    onRegisterLeaveGuard?.(navigate)
    return () => onRegisterLeaveGuard?.(null)
  }, [dirty, onRegisterLeaveGuard])

  function navigate(action) {
    if (operationLock.current) return
    if (dirty) setPendingNavigation(() => action)
    else action()
  }

  function reportError(message, canRefresh = false) {
    setNotice('')
    setError(message)
    setRefreshAvailable(canRefresh)
  }

  function keyed(payload) {
    const signature = JSON.stringify(payload)
    if (!requestKeys.current.has(signature)) requestKeys.current.set(signature, crypto.randomUUID())
    return { ...payload, idempotency_key: requestKeys.current.get(signature) }
  }

  async function run(label, operation) {
    if (operationLock.current) return false
    operationLock.current = true
    setBusy(label); setError(''); setNotice(''); setRefreshAvailable(false)
    try {
      await operation()
      return true
    } catch (failure) {
      if (!onAuthError(failure)) reportError(readableError(failure), true)
      return false
    } finally {
      operationLock.current = false
      setBusy('')
    }
  }

  function display(record, latestRevision = record.revision) {
    setSelected(record)
    setCurrentRevision(latestRevision)
    setForm(null)
    setReason('')
  }

  async function acceptSaved(saved, message) {
    // A saved operation stays successful even when the following refresh fails.
    display(saved)
    setCases((items) => upsertCase(items, saved))
    setNotice(`${message}（记录 v${saved.revision}）`)
    try {
      const latest = await getScreeningCase(saved.id)
      display(latest)
      setCases((items) => upsertCase(items, latest))
    } catch (failure) {
      if (!onAuthError(failure)) {
        setError('操作已保存，但未能同步最新状态。请刷新病例确认，无需重复提交。')
        setRefreshAvailable(true)
      }
    }
  }

  async function selectCase(id) {
    await run('载入病例', async () => display(await getScreeningCase(id)))
  }

  function startForm(value) {
    setForm(value)
    setReason('')
    formBaseline.current = JSON.stringify(value)
    setNotice(''); setError('')
  }

  function newExam(example = false) {
    const exam = example ? bilateralExample(owner) : createExamination(owner)
    if (site?.organization) exam.institution = site.organization
    return exam
  }

  function newCase() {
    navigate(() => {
      setSelected(null); setCurrentRevision(null)
      requestKeys.current.clear()
      startForm(newExam())
    })
  }

  async function save(event) {
    event.preventDefault()
    const invalid = validateExamination(form)
    if (invalid) { reportError(invalid); return }
    if (selected) {
      if (!reason.trim()) { reportError('请填写修订原因。'); return }
      return mutate('revise', { examination: form, reason: reason.trim() }, '修订已保存，请重新复核')
    }
    await run('保存病例', async () => {
      const saved = await createScreeningCase(keyed({ examination: form }))
      await acceptSaved(saved, '病例已创建')
    })
  }

  function openImport() {
    const open = () => setImportTarget({ record: selected, preserveTasks: Boolean(form || selected), examination: structuredClone(form || selected?.examination || newExam()) })
    if (form) open()
    else navigate(open)
  }

  async function mutate(action, payload, message) {
    return run('保存操作', async () => {
      const saved = await mutateScreeningCase(selected.id, keyed({ action, expected_revision: selected.revision, ...payload }))
      await acceptSaved(saved, message)
    })
  }

  async function toggleExplanation() {
    if (explanationOpen) { setExplanationOpen(false); return }
    if (context) { setExplanationOpen(true); return }
    await run('载入逐眼释义', async () => {
      setContext(await getScreeningContext(selected.id, selected.revision))
      setExplanationOpen(true)
    })
  }

  async function download(pdf) {
    await run('准备下载', async () => {
      const blob = await (pdf ? exportScreeningPdf : exportScreeningCase)(selected.id, selected.revision)
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `synthetic-${selected.id}-v${selected.revision}.${pdf ? 'pdf' : 'json'}`
      link.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
      setNotice(`记录 v${selected.revision} 已交给浏览器下载`)
    })
  }

  async function selectLatest() {
    const latest = await getScreeningCase(selected.id)
    display(latest)
    setCases((items) => upsertCase(items, latest))
  }

  const listRows = followupCases(cases, followupFilter, Date.now())
  return (
    <section className="screening-view">
      <header className="screening-header" inert={pendingNavigation || importTarget ? '' : undefined}>
        <div><h1>病例工作台</h1><p className="screening-muted">合成演练 · 仅供流程验证，急症直接人工交接</p></div>
        <div className="screening-actions">
          <button disabled={Boolean(busy) || loading || historical} onClick={openImport}>导入已有分析</button>
          <button className="screening-primary" disabled={Boolean(busy) || loading} onClick={newCase}>新建合成病例</button>
        </div>
      </header>
      <div className="screening-layout" inert={pendingNavigation || importTarget ? '' : undefined}>
        <nav className="screening-list" aria-label="合成病例列表">
          <header><h2>病例</h2><button disabled={Boolean(busy) || loading} onClick={() => run('刷新列表', async () => {
            setCases(await listScreeningCases()); setNotice('病例列表已刷新')
          })}>刷新</button></header>
          <label>转诊跟进筛选
            <select value={followupFilter} onChange={(event) => setFollowupFilter(event.target.value)}>
              <option value="all">全部病例</option>
              <option value="pending">待跟进</option>
              <option value="overdue">已逾期</option>
            </select>
          </label>
          {loading && <p role="status">正在载入病例…</p>}
          {!loading && !cases.length && <p className="screening-muted">还没有病例。</p>}
          {!loading && cases.length > 0 && !listRows.length && <p role="status">当前列表没有符合条件的病例。</p>}
          {listRows.map(({ item, pending, overdue }) => {
            return <button key={item.id} disabled={Boolean(busy)} aria-current={selected?.id === item.id ? 'true' : undefined}
              title={`${item.examination.encounter_id} · ${STAGE[item.stage]} · ${item.examination.followup_owner}`}
              className={selected?.id === item.id ? 'active' : ''} onClick={() => navigate(() => selectCase(item.id))}>
              <strong>{item.examination.encounter_id}</strong>
              <span>{STAGE[item.stage]} · {item.examination.followup_owner}</span>
              {pending > 0 && <span className={overdue ? 'screening-overdue' : ''}>{overdue ? '已逾期 · ' : ''}{pending} 份待跟进</span>}
            </button>
          })}
        </nav>
        <div className="screening-detail" aria-busy={Boolean(busy)}>
          <ExamGuide />
          {site?.organization && <p>合成演练机构 · {site.organization} · 新病例供本机构成员协作。
            接收科室 {site.receiving_unit}，每日容量 {site.daily_capacity}，紧急交接 {site.emergency_contact}。</p>}
          <div ref={feedbackRef} tabIndex={-1} className="screening-feedback" hidden={!notice && !error}>
            {notice && <p role="status" className="screening-success">{notice}</p>}
            {error && <div role="alert" className="screening-error">
              <p>{error}</p>
              {refreshAvailable && <button disabled={Boolean(busy)} onClick={() => {
                const refresh = () => run('载入最新状态', async () => {
                if (selected) await selectLatest()
                else setCases(await listScreeningCases())
                setNotice('已载入最新状态')
                })
                if (form) navigate(refresh)
                else refresh()
              }}>刷新查询最新结果</button>}
            </div>}
          </div>
          {busy && <p role="status" className="screening-muted">{busy}…</p>}
          {form ? <CaseForm value={form} onChange={setForm} editing={Boolean(selected)} reason={reason}
            onReasonChange={setReason} onSave={save} onCancel={() => navigate(() => { setForm(null); setError('') })}
            onExample={() => navigate(() => startForm(newExam(true)))} onError={reportError} busy={Boolean(busy)} />
          : selected ? <>
            <header className="screening-case-header">
              <div><h2>{selected.examination.encounter_id}</h2><p className="screening-muted">{STAGE[selected.stage]} · 跟进：{selected.examination.followup_owner}</p></div>
              <div className="screening-actions">
                {selected.signature && <button disabled={Boolean(busy)} onClick={() => download(true)}>演练 PDF</button>}
                <button disabled={Boolean(busy) || historical} onClick={() => navigate(() => startForm(structuredClone(selected.examination)))}>修订 / 补拍</button>
              </div>
            </header>
            <label className="screening-version">记录版本
              <select disabled={Boolean(busy)} value={selected.revision} onChange={(event) => {
                const revision = Number(event.target.value)
                navigate(() => run('载入历史版本', async () => display(await getScreeningCase(selected.id, revision), currentRevision)))
              }}>
                {Array.from({ length: currentRevision }, (_, index) => currentRevision - index).map((revision) => <option key={revision} value={revision}>v{revision}{revision === currentRevision ? ' · 最新' : ' · 历史快照'}</option>)}
              </select>
            </label>
            {historical && <p className="screening-notice">历史快照仅供查看；修改请切回最新版本。</p>}
            {selected.examination.urgent_handoff && <p role="alert" className="screening-error">立即人工交接 · 跟进人：{selected.examination.followup_owner}。无需等待报告，机构急诊路径待确认。</p>}
            <div className="screening-eyes">{selected.examination.eyes.map((eye) => <EyeSummary eye={eye} key={eye.laterality} />)}</div>
            {selected.examination.note && <p className="screening-case-note">{selected.examination.note}</p>}
            {selected.signature && <section className="screening-plan">
              <h3>处置计划 · 模拟签发报告 v{selected.signature.signed_revision}</h3>
              <p>{selected.signature.plan}</p>
            </section>}
            {!historical && <CaseActions key={`${selected.id}-${actionEpoch}`} record={selected} busy={Boolean(busy)} onAction={mutate} onError={reportError} onDraftChange={recordDraft} />}
            {selected.referrals.length > 0 && <section aria-label="转诊跟进">
              <h3>转诊跟进</h3>
              {selected.referrals.map((referral) => <ReferralCard key={`${referral.id}-${actionEpoch}`} referral={referral} historical={historical} busy={Boolean(busy)} onAction={mutate} onError={reportError} onDraftChange={recordDraft} />)}
            </section>}
            <div className="screening-secondary-actions">
              <button aria-expanded={explanationOpen} aria-controls="screening-explanation" disabled={Boolean(busy)} onClick={toggleExplanation}>
                {explanationOpen ? '收起逐眼释义' : '查看逐眼释义'}
              </button>
            </div>
            {explanationOpen && context?.case_id === selected.id && context.revision === selected.revision && <VersionExplanation context={context} />}
            <CaseHistory record={selected} onDownload={download} busy={Boolean(busy)} />
            <AnalysisSources key={`${selected.id}-${selected.revision}`} record={selected} sources={selected.analysis_sources} onAuthError={onAuthError} />
          </> : <div className="screening-empty"><h2>选择或新建病例</h2><p>逐眼记录结果，完成复核与转诊跟进。</p></div>}
        </div>
      </div>
      {importTarget && <AnalysisImport record={importTarget.record} examination={importTarget.examination} initialReportId={importTarget.reportId} preserveTasks={importTarget.preserveTasks}
        onDirtyChange={recordDraft} onAuthError={onAuthError} onClose={() => navigate(() => setImportTarget(null))}
        onSaved={async (saved, unchanged) => { setImportTarget(null); await acceptSaved(saved, unchanged ? '分析已存在，未重复追加' : '分析已导入草稿，请完成人工复核') }} />}
      {pendingNavigation && <div className="screening-dialog-backdrop">
        <section role="dialog" aria-modal="true" aria-labelledby="screening-discard-title" className="screening-dialog"
          onKeyDown={(event) => {
            if (event.key === 'Escape') setPendingNavigation(null)
            if (event.key === 'Tab') {
              const buttons = [...event.currentTarget.querySelectorAll('button')]
              const next = event.shiftKey ? buttons[0] : buttons[buttons.length - 1]
              if (event.target === next) { event.preventDefault(); (event.shiftKey ? buttons[buttons.length - 1] : buttons[0]).focus() }
            }
          }}>
          <h2 id="screening-discard-title">有尚未保存的修改</h2><p>离开编辑会放弃这些修改。</p>
          <div className="screening-actions">
            <button className="screening-primary" autoFocus onClick={() => setPendingNavigation(null)}>继续编辑</button>
            <button onClick={() => { const action = pendingNavigation; setPendingNavigation(null); setActionDrafts({}); setActionEpoch((epoch) => epoch + 1); action() }}>放弃修改</button>
          </div>
        </section>
      </div>}
    </section>
  )
}
