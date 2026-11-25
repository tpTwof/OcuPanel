import assert from 'node:assert/strict'
import test from 'node:test'
import { followupCases } from '../src/screening/followup.js'

test('follow-up filters select synthetic cases by outstanding referrals and deadline', () => {
  const now = Date.parse('2026-11-25T10:00:00+08:00')
  const due = '2026-11-25T02:00:00Z'
  const earlier = '2026-11-24T02:00:00Z'
  const referral = (status, due_at) => ({ status, due_at })
  const cases = [
    { id: 'draft', referrals: [] },
    { id: 'waiting', referrals: [referral('waiting', due)] },
    { id: 'mixed', referrals: [referral('arrived', earlier), referral('accepted', earlier)] },
    { id: 'lost', referrals: [referral('lost', earlier)] },
    { id: 'done', referrals: [referral('arrived', earlier)] }
  ]
  const ids = (filter) => followupCases(cases, filter, now).map(({ item }) => item.id)
  assert.deepEqual(ids('all'), cases.map((item) => item.id))
  assert.deepEqual(ids('pending'), ['waiting', 'mixed', 'lost'])
  assert.deepEqual(ids('overdue'), ['mixed', 'lost'])
  assert.equal(followupCases(cases, 'overdue', now)[0].pending, 1)
})
import { appendCapture, bilateralExample, createExamination, importExamination, mergeCaseList, selectDiseases, updateTaskStatus, validateExamination } from '../src/screening/caseForm.js'

test('reference examinations require date, source and interpretation for the selected eye', () => {
  const exam = bilateralExample('operator')
  const reference = { modality: 'OCT', acquired_on: '2026-11-24', source: 'synthetic OCT', interpretation: '' }
  exam.eyes[1].tasks[0].reference_exam = reference
  assert.match(validateExamination(exam), /参考检查/)
  reference.interpretation = 'synthetic finding'
  assert.equal(validateExamination(exam), '')
})

test('changing task status preserves every original and retake record', () => {
  const left = bilateralExample('operator').eyes[1]
  const changed = updateTaskStatus(updateTaskStatus(left, 'glaucoma', 'not_captured'), 'glaucoma', 'ungradable')
  assert.deepEqual(changed.captures, left.captures)
  assert.equal(changed.captures.length, 2)
  assert.equal(changed.tasks[0].finding, 'not_assessed')
})

test('new disease tasks do not inherit glaucoma findings or overwrite the other eye', () => {
  const original = bilateralExample('operator')
  const changed = selectDiseases(original, ['glaucoma', 'diabetic_retinopathy', 'dme', 'age_related_macular_degeneration'])
  assert.deepEqual(changed.eyes[0].tasks[0], original.eyes[0].tasks[0])
  assert.deepEqual(changed.eyes[1].tasks[0], original.eyes[1].tasks[0])
  for (const eye of changed.eyes) for (const task of eye.tasks.slice(1)) {
    assert.equal(task.status, 'not_assessed')
    assert.equal(task.finding, 'not_assessed')
    assert.equal(task.observations, '')
  }
  assert.throws(() => selectDiseases(original, []), /至少保留/)
})

test('a fresh case has no made-up image acquisition or assessment', () => {
  const a = createExamination('operator')
  const b = createExamination('operator')
  assert.notEqual(a.patient_group, b.patient_group)
  for (const eye of a.eyes) {
    assert.equal(eye.captures.length, 0)
    assert.equal(eye.tasks[0].status, 'not_captured')
    assert.throws(() => updateTaskStatus(eye, 'glaucoma', 'gradable'), /先记录/)
  }
})

test('gradable status requires an explicit finding, never defaults to positive', () => {
  const original = createExamination('operator')
  const eye = appendCapture(original.eyes[0], 'glaucoma')
  const changed = updateTaskStatus(eye, 'glaucoma', 'gradable')
  assert.equal(changed.tasks[0].finding, '')
  assert.match(validateExamination({ ...original, eyes: [changed, original.eyes[1]] }), /右眼.*所见结论/)
})

test('validation includes tasks that are not currently selected in the editor', () => {
  const exam = selectDiseases(bilateralExample('operator'), ['glaucoma', 'dme'])
  exam.eyes[1].tasks[1].status = 'ungradable'
  exam.eyes[1].tasks[1].reason = '  '
  assert.match(validateExamination(exam), /左眼.*DME.*原因/)
})

test('an import with missing original permits pending review but cannot invent a readable result', () => {
  const exam = createExamination('operator')
  exam.eyes[0].analysis_refs = ['server-imported-report']
  const changed = updateTaskStatus(exam.eyes[0], 'glaucoma', 'not_assessed')
  assert.equal(validateExamination({ ...exam, eyes: [changed, exam.eyes[1]] }), '')
  assert.throws(() => updateTaskStatus(changed, 'glaucoma', 'gradable'), /先记录/)
  assert.deepEqual(selectDiseases({ ...exam, eyes: [changed, exam.eyes[1]] }, ['glaucoma', 'dme']).eyes[0].analysis_refs, ['server-imported-report'])
})

test('a late initial list response cannot overwrite a just-imported case or its newer version', () => {
  const saved = { id: 'new', revision: 2, updated_at: 20 }
  assert.deepEqual(mergeCaseList([saved], []), [saved])
  assert.equal(mergeCaseList([saved], [{ id: 'new', revision: 1, updated_at: 10 }])[0].revision, 2)
})

test('a fresh AMD-only import does not add glaucoma while manual tasks are preserved', () => {
  const base = createExamination('operator')
  const source = { source_metadata: { selected_diseases: ['age_related_macular_degeneration'] } }
  assert.deepEqual(importExamination(base, [source], false).eyes[0].tasks.map((task) => task.disease), ['age_related_macular_degeneration'])
  assert.deepEqual(importExamination(base, [source], true), base)
})
