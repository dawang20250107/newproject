import { reactive } from 'vue'

const state = reactive({ toasts: [] })
let _id = 0

function add(type, msg, duration, action) {
  const id = ++_id
  state.toasts.push({ id, type, msg, action })
  // 带行动按钮的 toast 给足操作时间(至少 8s)
  setTimeout(() => {
    const i = state.toasts.findIndex(t => t.id === id)
    if (i >= 0) state.toasts.splice(i, 1)
  }, action ? Math.max(duration, 8000) : duration)
}

// 错误文案自适应时长:后端硬闸的引导文案普遍 40–80 字(含「下一步怎么办」),
// 固定 4.5s 读不完就消失。按长度阶梯延长,长引导给足阅读时间。
function errDuration(msg, d) {
  if (d != null) return d
  const len = String(msg || '').length
  if (len > 60) return 12000
  if (len > 36) return 8000
  return 4500
}

// action(可选): { label, to } 路由跳转 或 { label, onClick } —— 关键动作后的「去查看」直达
export const toast = {
  success: (msg, d = 3000, action) => add('success', msg, d, action),
  error:   (msg, d, action) => add('error', msg, errDuration(msg, d), action),
  warn:    (msg, d = 4000, action) => add('warn', msg, d, action),
  info:    (msg, d = 3500, action) => add('info', msg, d, action),
}

export function useToast() { return toast }
export { state as _toastState }
