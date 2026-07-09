<script setup>
// 全局确认弹窗宿主（App.vue 挂载一次）。Esc=取消、Enter=确认；打开时焦点落在
// 非破坏性按钮上（危险操作默认聚焦「取消」，防手快回车误确认）。
import { watch, nextTick, ref } from 'vue'
import { confirmState, _settle } from '../composables/confirm.js'

const safeBtn = ref(null)
watch(() => confirmState.visible, async (v) => {
  if (v) { await nextTick(); safeBtn.value && safeBtn.value.focus() }
})
// 输入式确认：须原样输入指定词，确认按钮才可用（彻底删除等最高危操作）
const typeOk = () => !confirmState.requireText || confirmState.typed === confirmState.requireText
function onKey(e) {
  if (e.key === 'Escape') { e.stopPropagation(); _settle(false) }
  else if (e.key === 'Enter') {
    e.stopPropagation()
    if (!typeOk()) return
    // 危险操作:Enter 全局兜底会绕过「默认聚焦取消」的防误确认设计——
    // 焦点在取消按钮上时按回车应触发取消而不是确认;只有焦点明确在确认按钮上才放行
    if (confirmState.danger && e.target === safeBtn.value) { _settle(false); return }
    if (confirmState.danger && !(e.target instanceof HTMLButtonElement)) return
    _settle(true)
  }
}
</script>

<template>
  <Teleport to="body">
    <div v-if="confirmState.visible" class="cfm-overlay" tabindex="-1" @keydown="onKey" @click.self="_settle(false)">
      <div class="cfm-box" role="alertdialog" :aria-label="confirmState.title">
        <div class="cfm-head" :class="{ danger: confirmState.danger }">
          <svg v-if="confirmState.danger" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
          <svg v-else width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
          <h3>{{ confirmState.title }}</h3>
        </div>
        <p v-if="confirmState.message" class="cfm-msg">{{ confirmState.message }}</p>
        <ul v-if="confirmState.detail.length" class="cfm-detail">
          <li v-for="(d, i) in confirmState.detail" :key="i">{{ d }}</li>
        </ul>
        <div v-if="confirmState.requireText" class="cfm-type">
          <label>请输入「<b>{{ confirmState.requireText }}</b>」以确认执行：</label>
          <input v-model="confirmState.typed" class="cfm-type-inp"
                 :placeholder="confirmState.requireText" autocomplete="off" />
        </div>
        <div class="cfm-actions">
          <button ref="safeBtn" class="btn btn-ghost" @click="_settle(false)">{{ confirmState.cancelText }}</button>
          <button class="btn" :class="confirmState.danger ? 'cfm-danger-btn' : 'btn-primary'"
                  :disabled="!typeOk()" @click="typeOk() && _settle(true)">{{ confirmState.confirmText }}</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.cfm-overlay {
  position: fixed; inset: 0; z-index: 4000; display: flex; align-items: center; justify-content: center;
  background: rgba(30, 20, 12, 0.42); backdrop-filter: blur(3px);
}
.cfm-box {
  width: min(460px, calc(100vw - 40px)); background: var(--surface-2); border: 1px solid var(--border);
  border-radius: var(--radius); box-shadow: var(--shadow-lg); padding: 18px 20px 16px;
}
.cfm-head { display: flex; align-items: center; gap: 8px; color: var(--c-info); margin-bottom: 10px; }
.cfm-head.danger { color: var(--c-danger); }
.cfm-head h3 { font-size: 15px; color: var(--text); }
.cfm-msg { font-size: 13px; line-height: 1.65; color: var(--text-2); white-space: pre-line; }
.cfm-detail {
  margin: 10px 0 0; padding: 8px 12px; max-height: 180px; overflow-y: auto; list-style: none;
  background: var(--surface-tint); border: 1px solid var(--border-soft); border-radius: var(--radius-sm);
  font-size: 12px; line-height: 1.7; color: var(--muted);
}
.cfm-type { margin-top: 12px; font-size: 12.5px; color: var(--text-2); }
.cfm-type b { color: var(--c-danger); }
.cfm-type-inp { display: block; width: 100%; margin-top: 6px; padding: 7px 10px;
  border: 1px solid var(--c-danger); border-radius: 8px; font-size: 13px;
  background: var(--card); color: var(--text); }
.cfm-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }
.cfm-actions .btn:disabled { opacity: .45; cursor: not-allowed; }
.cfm-danger-btn { background: var(--c-danger); color: #fff; border: none; }
.cfm-danger-btn:hover { filter: brightness(1.08); }
</style>
