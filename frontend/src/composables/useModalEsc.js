import { onMounted, onBeforeUnmount } from 'vue'

// 弹窗 Esc 关闭（系统级复用）：一页多个弹窗时按「后声明优先」关闭最上层。
// 用法：useModalEsc([() => showA.value, () => (showA.value = false)],
//                  [() => showB.value, closeB])
// 让路规则（与 useEscClearSelection 同一纪律）：
//   确认弹窗(ConfirmHost)自带 Esc 且在焦点链上 stopPropagation，天然优先；
//   右键菜单/列头筛选气泡开着时不关弹窗（Esc 先关它们）。
export function useModalEsc(...pairs) {
  function onKey(e) {
    if (e.key !== 'Escape') return
    if (document.querySelector('.cfm-overlay, .ctxm, .colf-pop')) return
    for (let i = pairs.length - 1; i >= 0; i--) {
      const [isOpen, close] = pairs[i]
      if (isOpen()) { e.stopPropagation(); close(); return }
    }
  }
  onMounted(() => document.addEventListener('keydown', onKey))
  onBeforeUnmount(() => document.removeEventListener('keydown', onKey))
}
