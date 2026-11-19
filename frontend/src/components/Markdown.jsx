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

export default function Markdown({ text, evidence, evidencePrefix }) {
  const html = useMemo(() => {
    const references = (evidence || []).map((item, index) => {
      const number = item.index ?? index + 1
      return `[${number}]: #${evidencePrefix}-${number}`
    })
    return wrapTables(converter.makeHtml([...references, '', text || ''].join('\n')))
  }, [text, evidence, evidencePrefix])

  function openCitation(event) {
    const href = event.target.closest('a')?.getAttribute('href')
    if (!evidencePrefix || !href?.startsWith(`#${evidencePrefix}-`)) return
    const item = document.getElementById(href.slice(1))
    if (!item) return
    event.preventDefault()
    const toggle = item.querySelector('button[aria-expanded]')
    if (toggle?.getAttribute('aria-expanded') === 'false') toggle.click()
    toggle?.focus({ preventScroll: true })
    item.scrollIntoView({ block: 'nearest' })
  }

  return <div className="markdown" onClick={openCitation} dangerouslySetInnerHTML={{ __html: html }} />
}
