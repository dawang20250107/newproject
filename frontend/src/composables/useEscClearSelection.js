import { onMounted, onBeforeUnmount } from 'vue'

// ESC 清空表格行勾选（系统级复用）。
// 分层让路，避免一个 ESC 误伤多个语义：
//   输入框/文本域聚焦时不管（ESC 属于输入控件）；
//   确认弹窗/模态/筛选气泡/右键菜单打开时不管（ESC 先关它们）；
//   存在单元格区域选区时不管（该次 ESC 由 useRangeSelection 消化，再按一次才清行选）。
// 用法：useEscClearSelection(() => hasSelection.value, clearSelection)
export function useEscClearSelection(hasSelection, clear) {
  function onKey(e) {
    if (e.key !== 'Escape') return
    const ae = document.activeElement
    if (ae && (ae.tagName === 'INPUT' || ae.tagName === 'TEXTAREA' || ae.isContentEditable)) return
    // 豁免清单须覆盖全站所有弹层类名：漏一个,该弹窗开着时按 Esc 就会误清底下表格的勾选
    if (document.querySelector(
      '.modal-overlay, .overlay, .modal-mask, .edit-mask, .drawer-mask, .scrim, '
      + '.cfm-overlay, .colf-pop, .ctxm, .drop-overlay, .logs-overlay')) return
    if (document.querySelector('.cell-range-sel')) return
    if (!hasSelection()) return
    clear()
  }
  onMounted(() => document.addEventListener('keydown', onKey))
  onBeforeUnmount(() => document.removeEventListener('keydown', onKey))
}
