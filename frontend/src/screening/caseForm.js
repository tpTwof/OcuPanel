// Form operations preserve source records and keep unassessed tasks inconclusive.
export const DISEASES = {
  glaucoma: { label: '青光眼', region: '视盘区域' },
  diabetic_retinopathy: { label: '糖尿病视网膜病变（DR）', region: '眼底视野' },
  dme: { label: '糖尿病黄斑水肿（DME）', region: '黄斑区域' },
  age_related_macular_degeneration: { label: '年龄相关性黄斑变性（AMD）', region: '黄斑区域' }
}
export const STATUS = { not_captured: '未拍', not_assessed: '未评估', ungradable: '不可判读', gradable: '可判读' }
export const FINDING = { not_assessed: '未形成结论', no_target_signs: '未见目标征象', suspect: '可疑，需复核' }
export const STAGE = { draft: '待复核', reviewed: '待模拟签发', signed: '已模拟签发' }
export const RECEIPT = { waiting: '等待接收', accepted: '已接单', arrived: '已到诊', lost: '失访' }
export const RECEIPT_TRANSITIONS = {
  waiting: ['accepted', 'arrived', 'lost'], accepted: ['arrived', 'lost'], lost: ['accepted', 'arrived'], arrived: []
}
export const ACTION = { create: '创建', revise: '修订', review: '复核', sign: '模拟签发', revoke: '撤销模拟签发', refer: '转诊', receipt: '回执', handoff: '移交', followup: '计划随访', import_analysis: '导入分析' }
export const eyeName = (eye) => eye === 'right' ? '右眼' : '左眼'
export const diseaseName = (disease) => DISEASES[disease]?.label || disease
export const formatTime = (value) => new Date(typeof value === 'number' ? value * 1000 : value).toLocaleString('zh-CN')

export function newTask(disease, captured = false) {
  return {
    disease, status: captured ? 'not_assessed' : 'not_captured', finding: 'not_assessed',
    visible_region: DISEASES[disease].region, reason: '', observations: '',
    next_step: '待人工评估并补充安排', source: 'human_rehearsal'
  }
}

export function createExamination(owner) {
  const identifier = crypto.randomUUID().slice(0, 8)
  return {
    synthetic: true, institution: '合成演练机构', encounter_id: `DEMO-${identifier}`,
    patient_group: `synthetic-patient-${identifier}`, age: 55, followup_owner: owner,
    note: '', urgent_handoff: false,
    eyes: ['right', 'left'].map((laterality) => ({ laterality, captures: [], tasks: [newTask('glaucoma')] }))
  }
}

export function appendCapture(eye, activeDisease) {
  if (eye.captures.length >= 20) return eye
  const capture = {
    image_ref: `synthetic:${eye.laterality}-${crypto.randomUUID()}`,
    captured_at: new Date().toISOString(), device: '合成设备 A', field: '合成眼底视野'
  }
  return {
    ...eye, captures: [...eye.captures, capture],
    tasks: eye.tasks.map((task) => task.disease === activeDisease && task.status === 'not_captured'
      ? { ...task, status: 'not_assessed' } : task)
  }
}

export function updateTaskStatus(eye, disease, status) {
  if (!eye.captures.length && status !== 'not_captured' && !(status === 'not_assessed' && eye.analysis_refs?.length)) throw new Error('请先记录一次合成采集，再填写评估状态。')
  return {
    ...eye,
    tasks: eye.tasks.map((task) => task.disease === disease ? {
      ...task, status,
      finding: status === 'gradable' ? (task.status === 'gradable' ? task.finding : '') : 'not_assessed'
    } : task)
  }
}

export function selectDiseases(examination, diseases) {
  if (!diseases.length) throw new Error('至少保留一个检查任务。')
  return {
    ...examination,
    eyes: examination.eyes.map((eye) => ({
      ...eye,
      tasks: diseases.map((disease) => eye.tasks.find((task) => task.disease === disease) || newTask(disease, eye.captures.length > 0))
    }))
  }
}

export function bilateralExample(owner) {
  const examination = createExamination(owner)
  examination.note = '合成病例：右眼可疑，左眼补拍后仍不可判读。'
  examination.eyes = examination.eyes.map((eye) => {
    const captured = appendCapture(eye, 'glaucoma')
    if (eye.laterality === 'right') return { ...captured, tasks: [{ ...captured.tasks[0], status: 'gradable', finding: 'suspect', observations: '合成可疑所见，供流程演练', next_step: '人工复核并决定去向' }] }
    const retaken = appendCapture(captured, 'glaucoma')
    return { ...retaken, tasks: [{ ...retaken.tasks[0], status: 'ungradable', reason: '补拍后仍无法辨认所需区域', next_step: '安排人工检查' }] }
  })
  return examination
}

export function validateExamination(examination) {
  for (const [field, label] of [['institution', '机构'], ['encounter_id', '就诊编号'], ['patient_group', '患者分组编号'], ['followup_owner', '跟进人']]) {
    if (!examination[field]?.trim()) return `请填写${label}。`
  }
  if (!Number.isInteger(examination.age) || examination.age < 18 || examination.age > 120) return '年龄须为 18–120 岁的整数。'
  for (const eye of examination.eyes) {
    for (const task of eye.tasks) {
      const prefix = `${eyeName(eye.laterality)} · ${diseaseName(task.disease)}`
      const reference = task.reference_exam
      if (reference && (!reference.acquired_on || !reference.source?.trim() || !reference.interpretation?.trim())) {
        return `${prefix}：请填写参考检查日期、记录来源及人工解读。`
      }
      if (!eye.captures.length && task.status !== 'not_captured' && !(task.status === 'not_assessed' && eye.analysis_refs?.length)) return `${prefix}：请先记录采集。`
      if (task.status === 'gradable' && !['suspect', 'no_target_signs'].includes(task.finding)) return `${prefix}：请选择所见结论。`
      if (task.status === 'ungradable' && !task.reason.trim()) return `${prefix}：请说明不可判读原因。`
      if (!task.visible_region.trim()) return `${prefix}：请填写可见区域。`
      if (!task.next_step.trim()) return `${prefix}：请填写下一步安排。`
    }
  }
  return ''
}

export function upsertCase(cases, saved) {
  return [saved, ...cases.filter((item) => item.id !== saved.id)].sort((a, b) => b.updated_at - a.updated_at)
}

export function mergeCaseList(current, fetched) {
  const cases = new Map(fetched.map((item) => [item.id, item]))
  for (const item of current) {
    if (!cases.has(item.id) || cases.get(item.id).revision < item.revision) cases.set(item.id, item)
  }
  return [...cases.values()].sort((a, b) => b.updated_at - a.updated_at)
}

export function importExamination(base, reports, preserveTasks) {
  if (preserveTasks) return base
  const supported = ['glaucoma', 'diabetic_retinopathy', 'age_related_macular_degeneration']
  const diseases = [...new Set(reports.flatMap((report) => {
    const names = report.source_metadata?.selected_diseases || Object.keys(report.visual_findings || {})
    return names.length ? names : report.cup_to_disc != null ? ['glaucoma'] : []
  }))].filter((name) => supported.includes(name))
  return diseases.length ? selectDiseases(base, diseases) : base
}
