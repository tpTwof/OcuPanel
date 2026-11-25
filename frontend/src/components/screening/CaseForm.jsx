import { useState } from 'react'
import { appendCapture, DISEASES, diseaseName, eyeName, formatTime, selectDiseases, STATUS, updateTaskStatus } from '../../screening/caseForm.js'

function EyeForm({ eye, onChange, onError }) {
  const [activeDisease, setActiveDisease] = useState(eye.tasks[0].disease)
  const task = eye.tasks.find((item) => item.disease === activeDisease) || eye.tasks[0]
  const patchTask = (patch) => onChange({
    ...eye,
    tasks: eye.tasks.map((item) => item.disease === task.disease ? { ...item, ...patch } : item)
  })

  function changeStatus(status) {
    try { onChange(updateTaskStatus(eye, task.disease, status)) } catch (error) { onError(error.message) }
  }

  return (
    <fieldset className="screening-eye">
      <legend>{eyeName(eye.laterality)}</legend>
      {eye.tasks.length > 1 ? (
        <label>当前任务
          <select value={task.disease} onChange={(event) => setActiveDisease(event.target.value)}>
            {eye.tasks.map((item) => <option key={item.disease} value={item.disease}>{diseaseName(item.disease)}</option>)}
          </select>
        </label>
      ) : <p className="screening-muted">{diseaseName(task.disease)}</p>}
      <div className="screening-acquisition">
        <span>{eye.captures.length ? `已记录 ${eye.captures.length} 次采集` : '尚未采集'}</span>
        <button type="button" disabled={eye.captures.length >= 20} onClick={() => onChange(appendCapture(eye, task.disease))}>
          {eye.captures.length ? '记录合成补拍' : '记录合成采集'}
        </button>
      </div>
      <label>任务状态
        <select value={task.status} onChange={(event) => changeStatus(event.target.value)}>
          {Object.entries(STATUS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
      </label>
      {task.status === 'gradable' && (
        <label>所见结论
          <select required value={task.finding} onChange={(event) => patchTask({ finding: event.target.value })}>
            <option value="" disabled>请选择结论</option>
            <option value="suspect">可疑，需复核</option>
            <option value="no_target_signs">未见目标征象（仅此眼此任务）</option>
          </select>
        </label>
      )}
      {task.status === 'ungradable' && (
        <label>不可判读原因
          <input maxLength={1000} value={task.reason} onChange={(event) => patchTask({ reason: event.target.value })} />
        </label>
      )}
      <label>下一步安排
        <input maxLength={500} value={task.next_step} onChange={(event) => patchTask({ next_step: event.target.value })} />
      </label>
      <details className="screening-disclosure">
        <summary>所见与采集记录</summary>
        <label>同眼参考检查
          <select value={task.reference_exam?.modality || ''} onChange={(event) => patchTask({
            reference_exam: event.target.value ? { acquired_on: '', source: '', interpretation: '', ...task.reference_exam, modality: event.target.value } : null
          })}>
            <option value="">未提供</option>
            {['彩色眼底照', 'OCT', '裂隙灯', '视野', '专科综合检查'].map((name) => <option key={name}>{name}</option>)}
          </select>
        </label>
        {task.reference_exam && [['acquired_on', '检查日期'], ['source', '检查记录来源'], ['interpretation', '专科人工解读']].map(([field, label]) =>
          <label key={field}>{label}<input type={field === 'acquired_on' ? 'date' : 'text'} maxLength={500}
            value={task.reference_exam[field]} onChange={(event) => patchTask({ reference_exam: { ...task.reference_exam, [field]: event.target.value } })} /></label>
        )}
        <label>可见区域
          <input maxLength={500} value={task.visible_region} onChange={(event) => patchTask({ visible_region: event.target.value })} />
        </label>
        <label>所见或备注
          <textarea maxLength={2000} value={task.observations} onChange={(event) => patchTask({ observations: event.target.value })} />
        </label>
        {eye.captures.map((capture, index) => (
          <p className="screening-source" key={capture.image_ref + index}>
            第 {index + 1} 次 · {formatTime(capture.captured_at)}<br />
            {capture.device} · {capture.field}<br />{capture.image_ref}
          </p>
        ))}
      </details>
    </fieldset>
  )
}

export default function CaseForm({ value, onChange, editing, reason, onReasonChange, onSave, onCancel, onExample, onError, busy }) {
  const diseases = [...new Set(value.eyes.flatMap((eye) => eye.tasks.map((task) => task.disease)))]

  function toggleDisease(disease, checked) {
    try {
      onChange(selectDiseases(value, checked ? [...diseases, disease] : diseases.filter((item) => item !== disease)))
    } catch (error) { onError(error.message) }
  }

  return (
    <form onSubmit={onSave} noValidate>
      <fieldset disabled={busy} className="screening-form">
        <header className="screening-case-header">
          <h2>{editing ? '修订病例' : '新建合成病例'}</h2>
          {!editing && <button type="button" onClick={onExample}>填入双眼示例</button>}
        </header>
        <div className="screening-fields">
          {[
            ['encounter_id', '就诊编号'], ['followup_owner', '跟进人']
          ].map(([field, label]) => (
            <label key={field}>{label}
              <input maxLength={500} value={value[field]} onChange={(event) => onChange({ ...value, [field]: event.target.value })} />
            </label>
          ))}
        </div>
        <fieldset className="screening-task-picker">
          <legend>检查任务</legend>
          <div className="screening-task-options">
            {Object.entries(DISEASES).map(([disease, item]) => (
              <label className="screening-check" key={disease}>
                <input type="checkbox" checked={diseases.includes(disease)} onChange={(event) => toggleDisease(disease, event.target.checked)} />
                {item.label}
              </label>
            ))}
          </div>
          <p className="screening-muted">仅登记人工评估，不增加模型诊断能力。取消任务会移除本次草稿中的该项记录。</p>
        </fieldset>
        <div className="screening-eyes">
          {value.eyes.map((eye, index) => (
            <EyeForm key={eye.laterality} eye={eye} onError={onError} onChange={(changed) => onChange({
              ...value, eyes: value.eyes.map((item, position) => position === index ? changed : item)
            })} />
          ))}
        </div>
        <label>病例备注（选填）
          <textarea maxLength={4000} value={value.note} onChange={(event) => onChange({ ...value, note: event.target.value })} />
        </label>
        <label className="screening-check">
          <input type="checkbox" checked={value.urgent_handoff} disabled={Boolean(value.urgent_symptoms?.length)} onChange={(event) => onChange({ ...value, urgent_handoff: event.target.checked })} />
          需要立即人工交接
        </label>
        <fieldset><legend>受检者自述的急性症状（合成演练）</legend>
          {Object.entries({ curtain: '新发大量飞蚊、闪光或幕帘样遮挡', sudden_loss: '突发单眼视力丧失', painful_red_eye: '突发剧烈眼痛伴红眼或视物模糊' }).map(([key, label]) => (
            <label className="screening-check" key={key}><input type="checkbox" checked={Boolean(value.urgent_symptoms?.includes(key))}
              onChange={(event) => {
                const before = value.urgent_symptoms || []
                const symptoms = event.target.checked ? [...before, key] : before.filter((item) => item !== key)
                onChange({ ...value, urgent_symptoms: symptoms, urgent_handoff: symptoms.length > 0 || value.urgent_handoff })
              }} />{label}</label>
          ))}
          {value.urgent_handoff && <p role="alert">立即联系眼科急诊或就近急诊。无需等待拍照、模型或提交表单。</p>}
        </fieldset>
        <details className="screening-disclosure">
          <summary>机构与分组信息</summary>
          <div className="screening-fields">
            <label>机构<input maxLength={500} value={value.institution} onChange={(event) => onChange({ ...value, institution: event.target.value })} /></label>
            <label>患者分组编号<input maxLength={500} value={value.patient_group} onChange={(event) => onChange({ ...value, patient_group: event.target.value })} /></label>
            <label>年龄（成人）<input type="number" min="18" max="120" value={value.age} onChange={(event) => onChange({ ...value, age: Number(event.target.value) })} /></label>
          </div>
        </details>
        {editing && <label>修订原因<input maxLength={500} value={reason} onChange={(event) => onReasonChange(event.target.value)} /></label>}
        <div className="screening-actions">
          <button className="screening-primary" type="submit">{busy ? '正在保存…' : '保存病例'}</button>
          <button type="button" onClick={onCancel}>取消编辑</button>
        </div>
      </fieldset>
    </form>
  )
}
