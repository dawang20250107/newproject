// 轻量 Markdown → HTML：标题(#~####)、有序/无序列表、粗体、行内代码、分隔线、
// GFM 表格(| --- |)、段落。内容来自我们自己的 AI（非用户输入），仍先转义 HTML
// 再套样式，避免注入。与 AiAnalysisModal、驾驶舱业财融合对话共用，确保 AI 输出
// 排版一致美观。逐字流式渲染：每次对累计文本整体重渲，表格补齐后即成形。

function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function inlineMd(s) {
  return escapeHtml(s)
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`]+?)`/g, '<code>$1</code>')
}

// 表格：表行至少含一个 |；分隔行形如 | --- | :--: |（决定列对齐）
function splitRow(line) {
  let s = line.trim()
  if (s.startsWith('|')) s = s.slice(1)
  if (s.endsWith('|')) s = s.slice(0, -1)
  return s.split('|').map(c => c.trim())
}
function isTableRow(line) { return line.includes('|') && line.trim() !== '' }
function isSepRow(line) {
  const s = line.trim()
  return s.includes('-') && /^\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?$/.test(s)
}
function alignOf(cell) {
  const l = cell.startsWith(':'), r = cell.endsWith(':')
  return l && r ? 'center' : r ? 'right' : l ? 'left' : ''
}
function renderTable(header, aligns, rows) {
  const th = header.map((h, i) =>
    `<th${aligns[i] ? ` style="text-align:${aligns[i]}"` : ''}>${inlineMd(h)}</th>`).join('')
  const body = rows.map(r => '<tr>' + header.map((_, i) =>
    `<td${aligns[i] ? ` style="text-align:${aligns[i]}"` : ''}>${inlineMd(r[i] ?? '')}</td>`).join('') + '</tr>').join('')
  return `<div class="md-table-wrap"><table class="md-table"><thead><tr>${th}</tr></thead><tbody>${body}</tbody></table></div>`
}

export function renderMarkdown(text) {
  if (!text) return ''
  const out = []
  let listType = null
  let para = []
  const flushPara = () => { if (para.length) { out.push(`<p>${para.join('<br>')}</p>`); para = [] } }
  const closeList = () => { if (listType) { out.push(`</${listType}>`); listType = null } }
  const flushAll = () => { flushPara(); closeList() }
  const lines = String(text).split('\n')
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].replace(/\s+$/, '')
    // 表格：当前行是表行且下一行是分隔行
    if (isTableRow(line) && i + 1 < lines.length && isSepRow(lines[i + 1])) {
      flushAll()
      const header = splitRow(line)
      const aligns = splitRow(lines[i + 1]).map(alignOf)
      const rows = []
      let j = i + 2
      while (j < lines.length && isTableRow(lines[j]) && !isSepRow(lines[j])) {
        rows.push(splitRow(lines[j])); j++
      }
      out.push(renderTable(header, aligns, rows))
      i = j - 1
      continue
    }
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
