import { useEffect, useRef, useState } from 'react'
import LoadingOverlay from './LoadingOverlay.jsx'

const diseaseOptions = [
  ['glaucoma', '青光眼'],
  ['diabetic_retinopathy', '糖尿病视网膜病变（DR）'],
  ['age_related_macular_degeneration', '年龄相关性黄斑变性（AMD）']
]

/**
 * 按所选病种分析眼底图，结合临床记录生成并校验报告。
 * 结果追加到当前对话里，所以生成完能直接接着追问（报告正文本身就是上下文）。
 */
export default function ReportView({ hasConversation, onGenerate, busy, notConfigured, onOpenSettings }) {
  const [file, setFile] = useState(null)
  const [previewUrl, setPreviewUrl] = useState(null)
  const [note, setNote] = useState('')
  const [diseases, setDiseases] = useState(['glaucoma'])
  const [dragging, setDragging] = useState(false)
  const inputRef = useRef(null)
  useEffect(() => () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl)
  }, [previewUrl])

  const acceptFile = (f) => {
    if (!f) return
    if (!/\.(jpe?g|png)$/i.test(f.name)) {
      alert('请选择图片文件（jpg / png）')
      return
    }
    const url = URL.createObjectURL(f)
    setFile(f)
    setPreviewUrl(url)
  }

  const run = async () => {
    if (notConfigured) {
      onOpenSettings()
      return
    }
    if (!file) {
      alert('请先上传一张眼底影像')
      return
    }
    if (!diseases.length) return
    await onGenerate(file, note.trim(), diseases)
  }

  return (
    <div className="report-view">
      <LoadingOverlay show={busy} />
      <div className="chat-head">
        <h2>眼科分析</h2>
      </div>

      <div className="report-scroll">
        <p>{hasConversation ? '报告将追加到当前会话，之后可以继续追问。' : '提交后将新建眼科会话，在其中查看报告并继续追问。'}</p>
        <fieldset className="field report-diseases" disabled={busy}>
          <legend className="field-label">分析病种</legend>
          {diseaseOptions.map(([id, label]) => (
            <label key={id}>
              <input
                type="checkbox"
                checked={diseases.includes(id)}
                onChange={(event) => {
                  setDiseases(event.target.checked ? [...diseases, id] : diseases.filter((item) => item !== id))
                }}
              />
              {label}
            </label>
          ))}
          <small>请上传彩色眼底照片。DR 和 AMD 提供研究性匹配分数。</small>
        </fieldset>
        <label className="field">
          <span className="field-label">医疗报告或临床记录</span>
          <textarea
            className="report-note"
            rows={4}
            placeholder="例如：患者 62 岁，右眼视物模糊半年，眼压 26 mmHg，有高血压史…"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
        </label>

        <div
          className={`dropzone${dragging ? ' dragging' : ''}${previewUrl ? ' has-file' : ''}`}
          onClick={() => inputRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragging(false)
            acceptFile(e.dataTransfer.files[0])
          }}
        >
          {previewUrl ? (
            <img src={previewUrl} alt="待分析眼底图" />
          ) : (
            <>
              <div className="dropzone-icon" aria-hidden="true">
                <svg width="26" height="26" viewBox="0 0 24 24" fill="none">
                  <rect x="3" y="4" width="18" height="16" rx="3" stroke="currentColor" strokeWidth="1.5" />
                  <circle cx="8.5" cy="9.5" r="1.6" fill="currentColor" />
                  <path d="M4 17l5-4 3 2.5 3-2.5 5 4" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
                </svg>
              </div>
              <div className="dropzone-main">拖拽眼底影像到此处，或点击选择</div>
              <div className="dropzone-sub">支持 jpg / jpeg / png</div>
            </>
          )}
        </div>
        <input
          ref={inputRef}
          type="file"
          accept=".jpg,.jpeg,.png"
          hidden
          onChange={(e) => acceptFile(e.target.files[0])}
        />

        {file && <div className="file-line">已选择：{file.name}</div>}

        <div className="report-actions">
          <button type="button" className="btn-primary" onClick={run} disabled={busy || !diseases.length}>
            {busy ? '正在生成…' : hasConversation ? '生成报告并添加到当前会话' : '生成报告并创建会话'}
          </button>
        </div>

        {busy && <div className="report-progress">正在分析影像、生成报告并校验引用…</div>}
      </div>
    </div>
  )
}
