import { useState } from 'react'

const guides = [
  ['糖网', '准备逐眼视力、糖尿病史及有明确视野的眼底照。由阅片人员记录所见和转诊去向。', '我国糖尿病视网膜病变临床诊疗指南', 'https://www.gzzoc.org.cn/node/13780'],
  ['糖尿病黄斑水肿', '核对同眼黄斑 OCT 和检查日期。缺少参考检查时登记未评估。', 'NICE NG242 · 1.6.11', 'https://www.nice.org.uk/guidance/ng242/chapter/Recommendations'],
  ['黄斑变性', '记录近期视物变化和眼别。疑活动性湿性 AMD 时联系黄斑专科评估并安排 OCT。', 'NICE NG82 · 1.4.6–1.4.7', 'https://www.nice.org.uk/guidance/ng82/chapter/Recommendations'],
  ['白内障', '准备视力、眩光及日常活动受影响的记录，由眼科进行晶状体裂隙灯检查。', '国家卫健委成人白内障手术操作规范', 'https://www.nhc.gov.cn/cms-search/xxgk/getManuscriptXxgk.htm?id=5ba49ac3bf3148d8baab72c7547cc1bb'],
  ['干眼', '记录干涩、异物感及持续时间。就诊时可评估泪液和眼表。', 'NEI 干眼检查', 'https://www.nei.nih.gov/eye-health-information/eye-conditions-and-diseases/dry-eye/testing-dry-eye'],
  ['紧急就医', '新发大量飞蚊、闪光或幕帘样遮挡应立即联系眼科急诊或就近急诊，无需等待上传照片。', 'NEI 视网膜脱离', 'https://www.nei.nih.gov/eye-health-information/eye-conditions-and-diseases/retinal-detachment']
]

export default function ExamGuide() {
  const [topic, setTopic] = useState(0)
  const [, instruction, source, url] = guides[topic]
  return <details className="screening-disclosure">
    <summary>检查与就医导航</summary>
    <label>查阅主题<select value={topic} onChange={(event) => setTopic(Number(event.target.value))}>
      {guides.map(([label], index) => <option key={label} value={index}>{label}</option>)}
    </select></label>
    <p>{instruction}</p><a href={url} target="_blank" rel="noreferrer">{source}</a>
    <p className="screening-muted">研究用资料，待本地专科审核。</p>
  </details>
}
