import { ref, onMounted, onBeforeUnmount } from 'vue'

// 全局操作手感（App.vue 一处接入，全站生效）：
//   1. 「/」聚焦当前页第一个可见搜索框（未在输入态、无弹层时）
//   2. 搜索框内 Esc 一键清空，并触发 input 走各页面自己的防抖重查；
//      再按一次 Esc 才轮到弹窗关闭/清选等下一层语义
//   3. 勾选列整格热区：td/th.sel-col 任意位置点击等于点中复选框，
//      不再要求精确命中 14px 的小方块；整行本身可点选/可点开的表
//      （回收站/客户列表/预收核销）用 data-no-selzone 豁免
//   4. 勾选列上的双击只属于勾选，不触发行双击打开（捕获阶段拦截）
//   5. 数字输入框聚焦即全选：改金额直接输新值，不必先删旧值
//   6. 「?」呼出快捷键速查面板（HotkeyHelp 组件消费 hotkeyHelpVisible）

// 全局共享的速查面板开关：AppNav 的 ⌨ 按钮与「?」快捷键共用
export const hotkeyHelpVisible = ref(false)

const OVERLAY_SEL = '.modal-overlay, .overlay, .modal-mask, .edit-mask, .drawer-mask, .scrim, '
  + '.cfm-overlay, .colf-pop, .ctxm, .drop-overlay, .logs-overlay, .ap-backdrop, .lt-overlay'

function isTyping() {
  const ae = document.activeElement
  return !!ae && (ae.tagName === 'INPUT' || ae.tagName === 'TEXTAREA' || ae.tagName === 'SELECT' || ae.isContentEditable)
}
const SEARCH_SEL = 'input.search-input, input.global-search, input.qs-input, input[data-search]'
const isVisible = el => !!el && el.offsetParent !== null && !el.disabled

function onKeydown(e) {
  if (e.key === '?' && !e.ctrlKey && !e.metaKey && !e.altKey && !isTyping()) {
    e.preventDefault()
    hotkeyHelpVisible.value = !hotkeyHelpVisible.value
    return
  }
  if (e.key === '/' && !e.ctrlKey && !e.metaKey && !e.altKey
      && !isTyping() && !document.querySelector(OVERLAY_SEL)) {
    // 各页搜索框类名不一（search-input/global-search/qs-input），统一在此枚举——
    // 修复「/」在付款/审批/应收明细等最高频页失效的问题
    const inp = [...document.querySelectorAll(SEARCH_SEL)].find(isVisible)
    if (inp) { e.preventDefault(); inp.focus(); inp.select() }
    return
  }
  if (e.key === 'Escape') {
    const ae = document.activeElement
    if (ae && ae.tagName === 'INPUT' && ae.matches(SEARCH_SEL) && ae.value) {
      // 页面级 Esc 监听（useModalEsc/useEscClearSelection）对输入态本就让路；
      // 这里再截断后续 document 监听，确保这次 Esc 只做「清空搜索」一件事
      e.stopImmediatePropagation()
      ae.value = ''
      ae.dispatchEvent(new Event('input', { bubbles: true }))
    }
  }
}

function onClick(e) {
  const cell = e.target.closest('td.sel-col, th.sel-col')
  if (!cell || e.target.tagName === 'INPUT') return
  if (cell.closest('[data-no-selzone]')) return
  cell.querySelector('input[type="checkbox"]:not(:disabled)')?.click()
}

function onDblClickCapture(e) {
  if (e.target.closest?.('td.sel-col, th.sel-col')) e.stopPropagation()
}

function onFocusIn(e) {
  const el = e.target
  if (el.tagName === 'INPUT' && el.type === 'number' && el.value !== '') {
    requestAnimationFrame(() => { try { el.select() } catch { /* 已失焦等 */ } })
  }
}

export function useInteractionFeel() {
  onMounted(() => {
    document.addEventListener('keydown', onKeydown)
    document.addEventListener('click', onClick)
    document.addEventListener('dblclick', onDblClickCapture, true)
    document.addEventListener('focusin', onFocusIn)
  })
  onBeforeUnmount(() => {
    document.removeEventListener('keydown', onKeydown)
    document.removeEventListener('click', onClick)
    document.removeEventListener('dblclick', onDblClickCapture, true)
    document.removeEventListener('focusin', onFocusIn)
  })
}
