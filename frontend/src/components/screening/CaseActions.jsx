import { useEffect, useState } from 'react'
import { eyeName, RECEIPT, RECEIPT_TRANSITIONS, formatTime } from '../../screening/caseForm.js'

function useDraft(key, dirty, onDraftChange) {
  useEffect(() => {
    onDraftChange?.(key, dirty)
    return () => onDraftChange?.(key, false)
  }, [key, dirty, onDraftChange])
}

function ReviewAction({ onAction, onDraftChange, sourcesIncomplete }) {
  const [checked, setChecked] = useState(false)
  useDraft('review', checked, onDraftChange)
  return (
    <section className="screening-next-action">
      <h3>下一步：人工复核</h3>
      {sourcesIncomplete && <p className="screening-muted">分析来源缺少原图、采集时间或设备；研究信息可查看，补齐前不能确认原图复核。</p>}
      <label className="screening-check"><input type="checkbox" checked={checked} onChange={(event) => setChecked(event.target.checked)} />已核对现有原图、眼别和双眼状态</label>
      <button className="screening-primary" disabled={!checked || sourcesIncomplete} onClick={() => onAction('review', {
        original_images_checked: true, case_checked: true, comment: '已核对合成原图引用、眼别与病例记录'
      }, '已记录人工复核')}>记录模拟复核</button>
    </section>
  )
}

function SignAction({ onAction, onError, unassessed, onDraftChange }) {
  const [plan, setPlan] = useState('')
  useDraft('sign', Boolean(plan.trim()), onDraftChange)
  return (
    <form className="screening-next-action" noValidate onSubmit={(event) => {
      event.preventDefault()
      if (!plan.trim()) return onError('请填写逐眼处置计划。')
      onAction('sign', { plan: plan.trim() }, '已保存模拟签发计划')
    }}>
      <h3>下一步：模拟签发</h3>
      {unassessed && <p className="screening-muted">仍有未评估任务，请先修订评估结果，再重新复核。</p>}
      <label>逐眼处置计划<textarea placeholder="分别填写左右眼的下一步安排" maxLength={500} value={plan} onChange={(event) => setPlan(event.target.value)} /></label>
      <button className="screening-primary" disabled={unassessed}>保存模拟签发</button>
    </form>
  )
}

function ReferralForm({ record, onAction, onError, onDraftChange }) {
  const [destination, setDestination] = useState('')
  const [eyes, setEyes] = useState(['right', 'left'])
  const [due, setDue] = useState('')
  useDraft('refer', Boolean(destination.trim() || due || eyes.length !== 2), onDraftChange)
  return (
    <details className="screening-disclosure">
      <summary>建立转诊 · 报告 v{record.signature.signed_revision}</summary>
      <form noValidate onSubmit={(event) => {
        event.preventDefault()
        const data = new FormData(event.currentTarget)
        const dateValue = data.get('due_at')
        const date = new Date(dateValue)
        if (!destination.trim()) return onError('请填写接收科室。')
        if (!dateValue || !Number.isFinite(date.getTime())) return onError('请选择有效的跟进截止时间。')
        if (!eyes.length) return onError('请至少选择一只转诊眼。')
        onAction('refer', { destination: destination.trim(), eyes, due_at: date.toISOString(),
          followup_owner: record.examination.followup_owner }, `已建立转诊，去向：${destination.trim()}`)
      }}>
        <label>接收科室<input maxLength={500} value={destination} onChange={(event) => setDestination(event.target.value)} /></label>
        <label>跟进截止时间<input name="due_at" type="datetime-local" value={due} onChange={(event) => setDue(event.target.value)} /></label>
        <div className="screening-actions">
          {['right', 'left'].map((eye) => <label className="screening-check" key={eye}>
            <input type="checkbox" checked={eyes.includes(eye)} onChange={(event) => setEyes(event.target.checked ? [...eyes, eye] : eyes.filter((item) => item !== eye))} />{eyeName(eye)}
          </label>)}
        </div>
        <p className="screening-muted">跟进人：{record.examination.followup_owner}</p>
        <button className="screening-primary">建立模拟转诊单</button>
      </form>
    </details>
  )
}

function FollowupForm({ onAction, onDraftChange }) {
  const [adherence, setAdherence] = useState('')
  const [symptoms, setSymptoms] = useState('')
  const [date, setDate] = useState('')
  useDraft('followup', Boolean(adherence || symptoms || date), onDraftChange)
  return <details className="screening-disclosure"><summary>登记计划随访</summary>
    <form onSubmit={async (event) => {
      event.preventDefault()
      if (await onAction('followup', { adherence, symptoms, next_visit: date || null }, '随访已保存到当前计划')) {
        setAdherence('')
        setSymptoms('')
        setDate('')
      }
    }}>
      <label>计划执行情况<input required maxLength={500} value={adherence} onChange={(e) => setAdherence(e.target.value)} /></label>
      <label>本次症状记录<input required maxLength={500} value={symptoms} onChange={(e) => setSymptoms(e.target.value)} /></label>
      <label>已约定复查日期<input type="date" value={date} onChange={(e) => setDate(e.target.value)} /></label>
      <button disabled={!adherence.trim() || !symptoms.trim()}>保存随访</button>
    </form>
  </details>
}

function HandoffForm({ onAction, onError, onDraftChange }) {
  const [owner, setOwner] = useState('')
  const [reason, setReason] = useState('')
  useDraft('handoff', Boolean(owner.trim() || reason.trim()), onDraftChange)
  return (
    <details className="screening-disclosure">
      <summary>移交跟进</summary>
      <form noValidate onSubmit={async (event) => {
        event.preventDefault()
        if (!owner.trim() || !reason.trim()) return onError('请填写接手人和交接原因。')
        if (await onAction('handoff', { followup_owner: owner.trim(), reason: reason.trim() }, `已移交给 ${owner.trim()}`)) {
          setOwner(''); setReason('')
        }
      }}>
        <label>接手人<input maxLength={500} value={owner} onChange={(event) => setOwner(event.target.value)} /></label>
        <label>交接原因<input maxLength={500} value={reason} onChange={(event) => setReason(event.target.value)} /></label>
        <button>记录移交</button>
      </form>
    </details>
  )
}

export function ReferralCard({ referral, historical, busy, onAction, onError, onDraftChange }) {
  const choices = RECEIPT_TRANSITIONS[referral.status]
  const [status, setStatus] = useState(choices[0] || '')
  const [note, setNote] = useState('')
  const activeStatus = choices.includes(status) ? status : choices[0] || ''
  useDraft(`receipt-${referral.id}`, !historical && Boolean(note.trim() || (activeStatus && activeStatus !== choices[0])), onDraftChange)
  const overdue = referral.status !== 'arrived' && Date.parse(referral.due_at) < Date.now()

  return (
    <article className="screening-referral">
      <header><strong>{referral.destination}</strong><span className="screening-badge">{RECEIPT[referral.status]}</span></header>
      <p>{referral.eyes.map(eyeName).join('、')} · 报告 v{referral.signed_revision} · 跟进：{referral.followup_owner}</p>
      <p className={overdue ? 'screening-overdue' : 'screening-muted'}>{overdue ? '已逾期 · ' : '截止：'}{formatTime(referral.due_at)}</p>
      {!historical && choices.length > 0 && (
        <details className="screening-disclosure">
          <summary>更新回执</summary>
          <form noValidate onSubmit={async (event) => {
            event.preventDefault()
            if (!note.trim()) return onError('请填写回执说明。')
            if (await onAction('receipt', { referral_id: referral.id, status: activeStatus, note: note.trim() }, `回执已更新：${RECEIPT[activeStatus]}`)) setNote('')
          }}>
            <fieldset disabled={busy} className="screening-form">
              <label>回执状态<select value={activeStatus} onChange={(event) => setStatus(event.target.value)}>
                {choices.map((value) => <option key={value} value={value}>{RECEIPT[value]}</option>)}
              </select></label>
              <label>回执说明<input maxLength={500} value={note} onChange={(event) => setNote(event.target.value)} /></label>
              <button>保存回执</button>
            </fieldset>
          </form>
        </details>
      )}
      {referral.receipts.length > 0 && <details className="screening-disclosure">
        <summary>回执记录（{referral.receipts.length}）</summary>
        {referral.receipts.map((receipt, index) => <p key={index}>{RECEIPT[receipt.status]} · {receipt.note} · {formatTime(receipt.at)}</p>)}
      </details>}
    </article>
  )
}

export default function CaseActions({ record, busy, onAction, onError, onDraftChange }) {
  const [reason, setReason] = useState('')
  useDraft('revoke', Boolean(reason.trim()), onDraftChange)
  const canRefer = record.signature && !record.referrals.some((item) => item.signed_revision === record.signature.signed_revision)
  const unassessed = record.examination.eyes.some((eye) => eye.tasks.some((task) => task.status === 'not_assessed'))
  const sourcesIncomplete = record.analysis_sources?.some((source) => source.original.status !== 'available' || !source.captured_at || !source.device)
  return (
    <fieldset disabled={busy} className="screening-form screening-action-panel">
      {record.stage === 'draft' && <ReviewAction key={`review-${record.id}`} onAction={onAction} onDraftChange={onDraftChange} sourcesIncomplete={sourcesIncomplete} />}
      {record.stage === 'reviewed' && <SignAction key={`sign-${record.id}`} onAction={onAction} onError={onError} unassessed={unassessed} onDraftChange={onDraftChange} />}
      {canRefer && <ReferralForm key={record.signature.signed_revision} record={record} onAction={onAction} onError={onError} onDraftChange={onDraftChange} />}
      {record.signature && <details><summary>撤销模拟签发</summary>
        <label>撤销原因<input maxLength={500} value={reason} onChange={(event) => setReason(event.target.value)} /></label>
        <button disabled={!reason.trim()} onClick={async () => {
          if (await onAction('revoke', { reason: reason.trim() }, '模拟签发已撤销，请核对已有转诊并重新复核')) setReason('')
        }}>确认撤销 v{record.signature.signed_revision}</button>
      </details>}
      {record.signature && <FollowupForm onAction={onAction} onDraftChange={onDraftChange} />}
      <HandoffForm onAction={onAction} onError={onError} onDraftChange={onDraftChange} />
    </fieldset>
  )
}
