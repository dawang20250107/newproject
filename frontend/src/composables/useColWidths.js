// 通用列宽拖拽持久化：每列可拖拽调整宽度，自动存 localStorage（按 storageKey 隔离）。
//
// 用法：
//   const cw = useColWidths('ar_records', { short_name: 160, operation_date: 90 })
//   <th :style="cw.thStyle('short_name')" class="...">
//     ...列头内容...
//     <div class="col-rh" @mousedown.stop="cw.startDrag($event, 'short_name')"></div>
//   </th>
import { reactive } from 'vue'

const MIN_W = 48
const MAX_W = 700

export function useColWidths(storageKey, defaults = {}) {
  const STORE_KEY = `col_widths:${storageKey}`

  function _load() {
    try {
      const saved = JSON.parse(localStorage.getItem(STORE_KEY) || '{}')
      return { ...defaults, ...saved }
    } catch { return { ...defaults } }
  }

  const widths = reactive(_load())

  function _save() {
    try { localStorage.setItem(STORE_KEY, JSON.stringify({ ...widths })) } catch (_) { /* */ }
  }

  // :style binding for <th>/<td>
  function thStyle(field) {
    const w = widths[field]
    return w ? { minWidth: w + 'px', width: w + 'px', maxWidth: w + 'px' } : {}
  }

  // @mousedown on resize handle
  function startDrag(e, field) {
    e.preventDefault()
    const th = e.currentTarget.closest('th') || e.target.closest('th')
    const startX = e.clientX
    const startW = widths[field] || (th ? th.offsetWidth : defaults[field] || 100)

    function onMove(mv) {
      const delta = mv.clientX - startX
      widths[field] = Math.max(MIN_W, Math.min(MAX_W, startW + delta))
    }
    function onUp() {
      _save()
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
    }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }

  function reset() {
    Object.keys(widths).forEach(k => delete widths[k])
    Object.assign(widths, { ...defaults })
    localStorage.removeItem(STORE_KEY)
  }

  return { widths, thStyle, startDrag, reset }
}
