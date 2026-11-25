import { ACTION, diseaseName, eyeName, FINDING, formatTime, STATUS } from '../../screening/caseForm.js'

export function EyeSummary({ eye }) {
  return (
    <article className="screening-eye">
      <h3>{eyeName(eye.laterality)}</h3>
      {eye.tasks.map((task) => (
        <div className="screening-task-result" key={task.disease}>
          <header><strong>{diseaseName(task.disease)}</strong><span className={`screening-badge status-${task.status}`}>{STATUS[task.status]}</span></header>
          <p>{FINDING[task.finding]}</p>
          {task.status === 'ungradable' && <p className="screening-muted">原因：{task.reason}</p>}
          <p>下一步：{task.next_step}</p>
          {task.reference_exam && <p>同眼参考检查 · {task.reference_exam.modality} · {task.reference_exam.acquired_on} · {task.reference_exam.source} · {task.reference_exam.interpretation}</p>}
        </div>
      ))}
      <details className="screening-disclosure">
        <summary>所见与采集来源（{eye.captures.length} 次）</summary>
        {eye.tasks.map((task) => <p key={task.disease}>{diseaseName(task.disease)} · {task.visible_region}{task.observations ? `：${task.observations}` : ''}</p>)}
        {eye.captures.map((capture, index) => <p className="screening-source" key={capture.image_ref + index}>
          第 {index + 1} 次 · {formatTime(capture.captured_at)}<br />{capture.device} · {capture.field}<br />{capture.image_ref}
        </p>)}
        {!eye.captures.length && <p className="screening-muted">没有采集记录。</p>}
      </details>
    </article>
  )
}

export function VersionExplanation({ context }) {
  return (
    <section id="screening-explanation" className="screening-explanation" aria-label="逐眼释义">
      <p className="screening-muted">记录 v{context.revision} · 仅解释此版本</p>
      {context.eyes.map((eye) => <div key={eye.laterality}>
        <h4>{eyeName(eye.laterality)}释义</h4>
        <ul>{eye.tasks.map((task) => <li key={task.disease}>
          <strong>{diseaseName(task.disease)}</strong>：{STATUS[task.status]}，{FINDING[task.finding]}。
          {task.status === 'ungradable' && `原因：${task.reason}。`}下一步：{task.next_step}。
        </li>)}</ul>
      </div>)}
      {context.signed_plan && <p>此版本模拟签发计划：{context.signed_plan}</p>}
      <details><summary>复诊时要核对哪些安排？</summary>
        <p>{context.signed_plan || '此版本没有模拟签发计划，请联系跟进人核对。'}</p>
        {context.eyes.map((eye) => <p key={eye.laterality}>{eyeName(eye.laterality)} · {eye.tasks.map((t) => diseaseName(t.disease) + '：' + t.next_step).join('。')}</p>)}
      </details>
      <details><summary>我可以更改用药吗？</summary>
        <p>用药变更请联系接诊医生，核对药名、用药眼别和现行医嘱。演练计划仅供流程验证。</p>
      </details>
      <p className="screening-muted">未拍、未评估和不可判读均不代表阴性；不能推断另一只眼或其他日期的结果。</p>
    </section>
  )
}

export function CaseHistory({ record, onDownload, busy }) {
  return (
    <details className="screening-disclosure screening-history">
      <summary>来源与操作记录</summary>
      <p>{record.examination.institution} · {record.examination.age} 岁 · 分组：{record.examination.patient_group}</p>
      <p className="screening-source">软件：{record.provenance.software} · 模型：{record.provenance.model}</p>
      <ol>{record.events.map((event) => <li key={event.revision}>
        v{event.revision} · {ACTION[event.action] || event.action} · {event.actor_name} · {formatTime(event.at)}
        {event.detail.reason && <span> · {event.detail.reason}</span>}
        {event.action === 'followup' && <span> · 计划 v{event.detail.signed_revision} · {event.detail.adherence} · {event.detail.symptoms} · 约定复查：{event.detail.next_visit || '未约定'}</span>}
        {event.action === 'handoff' && <span> · 接手：{event.detail.followup_owner}</span>}
      </li>)}</ol>
      <button disabled={busy} onClick={() => onDownload(false)}>导出此版本 JSON</button>
    </details>
  )
}
