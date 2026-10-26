import { useRef, useState } from 'react'
import LoadingOverlay from './LoadingOverlay.jsx'

/**
 * 生成报告：上传眼底图 + 填临床记录 → 六专科并发 → Director → 引用校验。
 * 结果追加到当前对话里，所以生成完能直接接着追问（报告正文本身就是上下文）。
 */
export default function ReportView({ onGenerate, onDownloadPdf, busy, notConfigured, onOpenSettings }) {
  const [file, setFile] = useState(null)
  const [previewUrl, setPreviewUrl] = useState(null)
  const [note, setNote] = useState('')
  const [dragging, setDragging] = useState(false)
  const [showDownload, setShowDownload] = useState(false)
  const inputRef = useRef(null)
  const previewRef = useRef(null)

  const acceptFile = (f) => {
    if (!f) return
    if (!f.type.startsWith('image/')) {
      alert('请选择图片文件（jpg / png）')
      return
    }
    if (previewRef.current) URL.revokeObjectURL(previewRef.current)
    const url = URL.createObjectURL(f)
    previewRef.current = url
    setFile(f)
    setPreviewUrl(url)
    setShowDownload(false)
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
    const ok = await onGenerate(file, note.trim())
    setShowDownload(Boolean(ok))
  }

  const download = async () => {
    if (!file) return
    await onDownloadPdf(file, note.trim())
  }

  return (
    <div className="report-view">
      <LoadingOverlay show={busy} />
      <div className="chat-head">
        <h2>生成报告</h2>
      </div>

      <div className="report-scroll">
        <label className="field">
          <span className="field-label">临床记录</span>
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
          accept="image/*"
          hidden
          onChange={(e) => acceptFile(e.target.files[0])}
        />

        {file && <div className="file-line">已选择：{file.name}</div>}

        <div className="report-actions">
          <button type="button" className="btn-primary" onClick={run} disabled={busy}>
            {busy ? '正在生成…' : '生成报告'}
          </button>
          {showDownload && (
            <button type="button" className="btn-secondary" onClick={download} disabled={busy}>
              下载 PDF
            </button>
          )}
        </div>

        {busy && <div className="report-progress">正在并发调用六个专科 → Director 综合 → 引用校验…</div>}
      </div>
    </div>
  )
}
