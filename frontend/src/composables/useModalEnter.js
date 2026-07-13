// Ctrl/Cmd+Enter 提交当前弹窗——与 useModalEsc 配对。
// 多字段录入表单不用裸 Enter（textarea 换行/误触风险），统一组合键提交；
// handler 内部自带校验与防重（busy 态直接 return），这里不做二次判断。
import { onMounted, onUnmounted } from 'vue'

export function useModalEnter(visible, handler) {
  function onKey(e) {
    if (e.key !== 'Enter' || !(e.ctrlKey || e.metaKey)) return
    const open = typeof visible === 'function' ? visible() : visible?.value
    if (!open) return
    e.preventDefault()
    handler()
  }
  onMounted(() => document.addEventListener('keydown', onKey))
  onUnmounted(() => document.removeEventListener('keydown', onKey))
}
