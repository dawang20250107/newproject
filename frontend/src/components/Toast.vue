<script setup>
import { _toastState, toast } from '../composables/useToast.js'
function dismiss(id) {
  const i = _toastState.toasts.findIndex(t => t.id === id)
  if (i >= 0) _toastState.toasts.splice(i, 1)
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
.toast-success { border-left: 4px solid #2e7d32; }
.toast-error   { border-left: 4px solid #c62828; }
.toast-warn    { border-left: 4px solid #e65100; }
.toast-info    { border-left: 4px solid #1565c0; }
.toast-icon    { font-weight: 700; flex-shrink: 0; margin-top: 1px; }
.toast-success .toast-icon { color: #2e7d32; }
.toast-error   .toast-icon { color: #c62828; }
.toast-warn    .toast-icon { color: #e65100; }
.toast-info    .toast-icon { color: #1565c0; }
.toast-msg     { flex: 1; color: #1a1208; }
.toast-enter-from, .toast-leave-to { opacity: 0; transform: translateX(60px); }
.toast-enter-active, .toast-leave-active { transition: all .22s ease; }
.toast-move { transition: transform .22s ease; }
</style>
