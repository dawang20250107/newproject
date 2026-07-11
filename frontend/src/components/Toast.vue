<script setup>
import { useRouter } from 'vue-router'
import { _toastState } from '../composables/useToast.js'

const router = useRouter()
function dismiss(id) {
  const i = _toastState.toasts.findIndex(t => t.id === id)
  if (i >= 0) _toastState.toasts.splice(i, 1)
}
// 行动按钮:{ label, to } 路由跳转 或 { label, onClick } 回调;点后关闭本条
function runAction(t, e) {
  e.stopPropagation()
  if (t.action?.to) router.push(t.action.to)
  else if (typeof t.action?.onClick === 'function') t.action.onClick()
  dismiss(t.id)
}
</script>
<template>
  <Teleport to="body">
    <TransitionGroup name="toast" tag="div" class="toast-wrap">
      <div v-for="t in _toastState.toasts" :key="t.id"
           :class="['toast-item', `toast-${t.type}`]"
           role="alert" @click="dismiss(t.id)">
        <span class="toast-icon">{{ {success:'✓',error:'✕',warn:'⚠',info:'ℹ'}[t.type] }}</span>
        <span class="toast-msg">{{ t.msg }}</span>
        <button v-if="t.action?.label" class="toast-act" @click="runAction(t, $event)">
          {{ t.action.label }} →
        </button>
      </div>
    </TransitionGroup>
  </Teleport>
</template>
<style scoped>
.toast-wrap {
  position: fixed; top: 18px; right: 18px; z-index: 9999;
  display: flex; flex-direction: column; gap: 8px; pointer-events: none;
  width: 320px;
}
.toast-item {
  display: flex; align-items: flex-start; gap: 10px;
  padding: 12px 14px; border-radius: 10px; font-size: 13.5px; line-height: 1.5;
  box-shadow: 0 4px 20px rgba(0,0,0,.18); cursor: pointer; pointer-events: all;
  background: #fffdf9; border: 1px solid rgba(180,140,110,.2);
}
.toast-success { border-left: 4px solid var(--c-success); }
.toast-error   { border-left: 4px solid var(--c-danger); }
.toast-warn    { border-left: 4px solid var(--c-warn); }
.toast-info    { border-left: 4px solid var(--c-info); }
.toast-icon    { font-weight: 700; flex-shrink: 0; margin-top: 1px; }
.toast-success .toast-icon { color: var(--c-success); }
.toast-error   .toast-icon { color: var(--c-danger); }
.toast-warn    .toast-icon { color: var(--c-warn); }
.toast-info    .toast-icon { color: var(--c-info); }
.toast-msg     { flex: 1; color: var(--text); }
.toast-act {
  flex-shrink: 0; align-self: center; padding: 3px 10px; border-radius: 7px;
  border: 1px solid var(--primary); background: transparent; color: var(--primary);
  font-size: 12px; font-weight: 600; cursor: pointer; white-space: nowrap;
}
.toast-act:hover { background: var(--primary); color: #fff; }
.toast-enter-from, .toast-leave-to { opacity: 0; transform: translateX(60px); }
.toast-enter-active, .toast-leave-active { transition: all .22s ease; }
.toast-move { transition: transform .22s ease; }
</style>
