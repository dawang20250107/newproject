<script setup>
// 全局错误边界：捕获子树渲染/生命周期中抛出的异常，展示可恢复的友好兜底，
// 而非整页白屏。按路由 key 重置——切换页面后自动清除错误态。
import { ref, onErrorCaptured } from 'vue'

const err = ref(null)
const showDetail = ref(false)

onErrorCaptured((e) => {
  err.value = e
  // 返回 false 阻止错误继续向上冒泡导致整应用卸载
  return false
})

function reset() { err.value = null; showDetail.value = false }
function reload() { window.location.reload() }
</script>

<template>
  <div v-if="err" class="eb-fallback">
    <div class="eb-card">
      <div class="eb-icon">
        <svg width="44" height="44" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
          <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
          <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
        </svg>
      </div>
      <div class="eb-title">页面遇到点问题</div>
      <div class="eb-desc">该页面渲染时出现异常，你的数据未受影响。可重试本页，或刷新整个应用。</div>
      <pre v-if="showDetail" class="eb-detail">{{ String(err && (err.stack || err.message || err)) }}</pre>
      <div class="eb-actions">
        <button class="eb-btn ghost" @click="reset">重试本页</button>
        <button class="eb-btn primary" @click="reload">刷新应用</button>
        <button class="eb-btn link" @click="showDetail = !showDetail">{{ showDetail ? '隐藏详情' : '查看详情' }}</button>
      </div>
    </div>
  </div>
  <slot v-else />
</template>

<style scoped>
.eb-fallback { display: flex; align-items: center; justify-content: center; min-height: 60vh; padding: 24px; }
.eb-card {
  max-width: 460px; text-align: center; background: var(--surface-1);
  border: 1px solid var(--border); border-radius: 16px; padding: 32px 28px;
  box-shadow: var(--shadow-md);
}
.eb-icon { color: var(--c-warn); margin-bottom: 12px; }
.eb-title { font-size: 18px; font-weight: 700; color: var(--text); margin-bottom: 8px; }
.eb-desc { font-size: 13.5px; color: var(--muted); line-height: 1.7; margin-bottom: 18px; }
.eb-detail {
  text-align: left; font-size: 11px; color: var(--text-2); background: rgba(0,0,0,0.03);
  border: 1px solid var(--border-soft); border-radius: 8px; padding: 10px;
  max-height: 200px; overflow: auto; white-space: pre-wrap; word-break: break-word; margin-bottom: 16px;
}
.eb-actions { display: flex; gap: 10px; justify-content: center; flex-wrap: wrap; }
.eb-btn { padding: 8px 18px; border-radius: 9px; font-size: 13px; font-weight: 600; cursor: pointer; border: 1px solid transparent; }
.eb-btn.primary { background: var(--primary); color: #fff; }
.eb-btn.ghost { background: transparent; border-color: var(--border); color: var(--text-2); }
.eb-btn.link { background: transparent; color: var(--muted); border: none; }
.eb-btn.link:hover { color: var(--primary); }
</style>
