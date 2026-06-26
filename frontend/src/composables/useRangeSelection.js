import { onBeforeUnmount } from 'vue'
import { copyText } from '../utils/clipboard.js'

// Excel 式单元格区域选择 + 复制（只读表格用）。事件委托到容器，按 td 的
// rowIndex/cellIndex 计算矩形选区，整块以 TSV 写入剪贴板，可直接粘贴进 Excel。
//
// 设计取舍：选区高亮用「直接给 DOM 的 td 加/去 .cell-range-sel 类」而非逐格
// :class 绑定，避免改动大量模板单元格、且对超大表格零渲染开销。
//
// 用法：
//   const range = useRangeSelection({ onCopy: n => toast.success(`已复制 ${n} 个单元格`) })
//   <div class="page-scroll" :ref="range.setRoot"> <table> … </table> </div>
//   选项 ignoreCols：忽略的列索引集合（如复选框列、操作列），这些列不参与选区。
export function useRangeSelection(opts = {}) {
  const ignoreCols = new Set(opts.ignoreCols || [])
  let root = null
  let anchor = null   // { r, c } —— tr 在 tbody 中的行号、td 的 cellIndex
  let focus = null
  let selecting = false

  function setRoot(el) { root = el }

  function cellFromEvent(e) {
    const td = e.target.closest('td')
    if (!td || !root || !root.contains(td)) return null
    const tr = td.closest('tr')
    if (!tr) return null
    const tbody = tr.closest('tbody')
    if (!tbody) return null
    const c = td.cellIndex
    if (ignoreCols.has(c)) return null
    // 行号：该 tr 在其 tbody 内的序号（跳过非 tr，如详情展开行可用 data-skiprange）
    const rows = Array.from(tbody.rows)
    const r = rows.indexOf(tr)
    if (r < 0 || tr.hasAttribute('data-skiprange')) return null
    return { r, c, tbody }
  }

  function clearHighlight() {
    if (!root) return
    root.querySelectorAll('td.cell-range-sel').forEach(td => td.classList.remove('cell-range-sel'))
  }

  function applyHighlight() {
    clearHighlight()
    if (!anchor || !focus || !root) return
    const tbody = anchor.tbody
    if (!tbody) return
    const r0 = Math.min(anchor.r, focus.r), r1 = Math.max(anchor.r, focus.r)
    const c0 = Math.min(anchor.c, focus.c), c1 = Math.max(anchor.c, focus.c)
    const rows = Array.from(tbody.rows)
    for (let r = r0; r <= r1; r++) {
      const tr = rows[r]
      if (!tr || tr.hasAttribute('data-skiprange')) continue
      for (let c = c0; c <= c1; c++) {
        const td = tr.cells[c]
        if (td && !ignoreCols.has(c)) td.classList.add('cell-range-sel')
      }
    }
  }

  function onMouseDown(e) {
    // 只响应左键、且不在输入控件/按钮上（避免干扰勾选/操作）
    if (e.button !== 0) return
    if (e.target.closest('input, button, select, a, textarea, label')) return
    const cell = cellFromEvent(e)
    if (!cell) return
    if (e.shiftKey && anchor) {
      focus = cell
    } else {
      anchor = cell
      focus = cell
    }
    selecting = true
    applyHighlight()
    // 阻止文本选择
    e.preventDefault()
  }

  function onMouseOver(e) {
    if (!selecting) return
    const cell = cellFromEvent(e)
    if (!cell || cell.tbody !== anchor?.tbody) return
    focus = cell
    applyHighlight()
  }

  function onMouseUp() { selecting = false }

  function selectionText() {
    if (!anchor || !focus) return ''
    const tbody = anchor.tbody
    const r0 = Math.min(anchor.r, focus.r), r1 = Math.max(anchor.r, focus.r)
    const c0 = Math.min(anchor.c, focus.c), c1 = Math.max(anchor.c, focus.c)
    const rows = Array.from(tbody.rows)
    const lines = []
    for (let r = r0; r <= r1; r++) {
      const tr = rows[r]
      if (!tr || tr.hasAttribute('data-skiprange')) continue
      const cells = []
      for (let c = c0; c <= c1; c++) {
        if (ignoreCols.has(c)) continue
        const td = tr.cells[c]
        const txt = (td?.innerText || '').replace(/[\t\n\r]+/g, ' ').trim()
        cells.push(txt)
      }
      lines.push(cells.join('\t'))
    }
    return lines.join('\n')
  }

  function cellCount() {
    if (!anchor || !focus) return 0
    const r = Math.abs(anchor.r - focus.r) + 1
    let cols = 0
    const c0 = Math.min(anchor.c, focus.c), c1 = Math.max(anchor.c, focus.c)
    for (let c = c0; c <= c1; c++) if (!ignoreCols.has(c)) cols++
    return r * cols
  }

  async function copy() {
    const text = selectionText()
    if (!text) return false
    const ok = await copyText(text)
    if (ok && opts.onCopy) opts.onCopy(cellCount())
    return ok
  }

  function onKeyDown(e) {
    if ((e.ctrlKey || e.metaKey) && (e.key === 'c' || e.key === 'C')) {
      // 仅当有区域选区、且当前没有原生文本选择时才接管
      if (anchor && focus && (cellCount() > 1) && !window.getSelection()?.toString()) {
        copy()
        e.preventDefault()
      }
    } else if (e.key === 'Escape') {
      anchor = focus = null
      clearHighlight()
    }
  }

  function bind() {
    if (!root) return
    root.addEventListener('mousedown', onMouseDown)
    root.addEventListener('mouseover', onMouseOver)
    document.addEventListener('mouseup', onMouseUp)
    document.addEventListener('keydown', onKeyDown)
  }
  function unbind() {
    if (root) {
      root.removeEventListener('mousedown', onMouseDown)
      root.removeEventListener('mouseover', onMouseOver)
    }
    document.removeEventListener('mouseup', onMouseUp)
    document.removeEventListener('keydown', onKeyDown)
  }

  // setRoot 由模板 ref 回调驱动；ref 设置后自动绑定一次
  function setRootAndBind(el) {
    if (root === el) return
    unbind()
    root = el
    if (root) bind()
  }

  onBeforeUnmount(unbind)

  return { setRoot: setRootAndBind, copy, clear: () => { anchor = focus = null; clearHighlight() } }
}
