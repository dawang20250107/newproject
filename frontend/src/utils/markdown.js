// 轻量 Markdown → HTML：标题(#~####)、有序/无序列表、粗体、行内代码、分隔线、段落。
// 内容来自我们自己的 AI（非用户输入），仍先转义 HTML 再套样式，避免注入。
// 与 AiAnalysisModal、驾驶舱业财融合对话共用，确保 AI 输出排版一致美观。

function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function inlineMd(s) {
  return escapeHtml(s)
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`]+?)`/g, '<code>$1</code>')
}

export function renderMarkdown(text) {
  if (!text) return ''
  const out = []
  let listType = null
  let para = []
  const flushPara = () => { if (para.length) { out.push(`<p>${para.join('<br>')}</p>`); para = [] } }
  const closeList = () => { if (listType) { out.push(`</${listType}>`); listType = null } }
  const flushAll = () => { flushPara(); closeList() }
  for (const raw of String(text).split('\n')) {
    const line = raw.replace(/\s+$/, '')
    if (!line.trim()) { flushAll(); continue }
    let m
    if (/^(-{3,}|\*{3,}|_{3,})$/.test(line.trim())) {
      flushAll(); out.push('<hr>')
    } else if ((m = line.match(/^(#{1,4})\s+(.*)$/))) {
      flushAll()
      const lvl = m[1].length
      out.push(`<h${lvl} class="md-h md-h${lvl}">${inlineMd(m[2])}</h${lvl}>`)
    } else if ((m = line.match(/^\s*[-*+]\s+(.*)$/))) {
      flushPara()
      if (listType !== 'ul') { closeList(); out.push('<ul class="md-list">'); listType = 'ul' }
      out.push(`<li>${inlineMd(m[1])}</li>`)
    } else if ((m = line.match(/^\s*\d+[.、]\s*(.*)$/))) {
      flushPara()
      if (listType !== 'ol') { closeList(); out.push('<ol class="md-list">'); listType = 'ol' }
      out.push(`<li>${inlineMd(m[1])}</li>`)
    } else {
      closeList()
      para.push(inlineMd(line))
    }
  }
  flushAll()
  return out.join('')
}
