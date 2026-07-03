// 批量操作结果弹窗服务：resultDlg({ title, okLine, skipped:[{id, reason}] })
// 跳过明细逐行展示、可复制——替代把明细用 \n 拼进 toast 的做法。
import { reactive } from 'vue'

export const resultState = reactive({ visible: false, title: '', okLine: '', skipped: [] })

export function resultDlg({ title = '操作结果', okLine = '', skipped = [] } = {}) {
  resultState.title = title
  resultState.okLine = okLine
  resultState.skipped = (skipped || []).map(s =>
    typeof s === 'string' ? { id: null, reason: s } : { id: s.id ?? null, reason: s.reason || String(s) })
  resultState.visible = true
}
