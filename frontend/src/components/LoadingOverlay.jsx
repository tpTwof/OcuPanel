export default function LoadingOverlay({ show, text = '正在生成报告，请稍候…' }) {
  if (!show) return null
  return (
    <div id="loading-overlay">
      <div className="spinner" />
      <p className="loading-text">{text}</p>
    </div>
  )
}
