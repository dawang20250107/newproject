import { reactive } from 'vue'

const state = reactive({ toasts: [] })
let _id = 0

function add(type, msg, duration) {
  const id = ++_id
  state.toasts.push({ id, type, msg })
  setTimeout(() => {
    const i = state.toasts.findIndex(t => t.id === id)
    if (i >= 0) state.toasts.splice(i, 1)
  }, duration)
}

export const toast = {
  success: (msg, d = 3000) => add('success', msg, d),
  error:   (msg, d = 4500) => add('error', msg, d),
  warn:    (msg, d = 4000) => add('warn', msg, d),
  info:    (msg, d = 3500) => add('info', msg, d),
}

export function useToast() { return toast }
export { state as _toastState }
