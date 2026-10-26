import { useMemo } from 'react'
import Showdown from 'showdown'

const converter = new Showdown.Converter({
  simpleLineBreaks: true,
  openLinksInNewWindow: true,
  // Showdown 默认不解析 | 表格 |，模型很爱用表格做对比，
  // 不开这个开关会被原样当段落渲染成一堆竖线。
  tables: true,
  // 别给表头加 id，报告里同一张表可能重复出现，id 会撞
  tablesHeaderId: false
})

/** 把 <table> 包一层横向滚动容器，窄屏下长表不撑破气泡。 */
function wrapTables(html) {
  if (!html.includes('<table>')) return html
  return html.replaceAll('<table>', '<div class="md-table-wrap"><table>').replaceAll('</table>', '</table></div>')
}

export default function Markdown({ text }) {
  const html = useMemo(() => wrapTables(converter.makeHtml(text || '')), [text])
  return <div className="markdown" dangerouslySetInnerHTML={{ __html: html }} />
}
