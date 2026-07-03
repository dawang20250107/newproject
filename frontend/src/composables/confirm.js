// 统一确认弹窗服务（替代原生 confirm()）：Promise 化，支持危险态、明细列表。
// 用法：if (!(await confirmDlg('确定删除？'))) return
//      await confirmDlg({ title:'彻底删除', message:'不可撤销', danger:true, detail:[...] })
import { reactive } from 'vue'

export const confirmState = reactive({
  visible: false,
  title: '',
  message: '',
  detail: [],        // 可选：逐行明细（数组）
  danger: false,     // 危险操作：红色主按钮
  confirmText: '确定',
  cancelText: '取消',
  _resolve: null,
})

export function confirmDlg(opts) {
  const o = typeof opts === 'string' ? { message: opts } : (opts || {})
  // 兼容原 confirm() 里用 \n 排版的文案：首行做标题候选，其余进明细
  let message = o.message || ''
  let detail = Array.isArray(o.detail) ? o.detail : []
  if (!detail.length && message.includes('\n')) {
    const lines = message.split('\n').map(s => s.trim()).filter(Boolean)
    message = lines.shift() || ''
    detail = lines
  }
  return new Promise(resolve => {
    // 若已有弹窗在挂起，先按取消处理，避免悬挂的 Promise
    if (confirmState._resolve) confirmState._resolve(false)
    // 危险语义自动识别：未显式指定 danger 时按文案判断（删除/退回/撤销/清除/不可撤销）
    const danger = o.danger !== undefined ? !!o.danger
      : /删除|退回|撤销|清除|清空|作废|不可恢复|不可撤销/.test(message + detail.join(''))
    confirmState.title = o.title || (danger ? '危险操作确认' : '操作确认')
    confirmState.message = message
    confirmState.detail = detail
    confirmState.danger = danger
    confirmState.confirmText = o.confirmText || '确定'
    confirmState.cancelText = o.cancelText || '取消'
    confirmState._resolve = resolve
    confirmState.visible = true
  })
}

export function _settle(val) {
  const r = confirmState._resolve
  confirmState.visible = false
  confirmState._resolve = null
  if (r) r(val)
}
