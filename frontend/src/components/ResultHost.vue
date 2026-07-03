<script setup>
// 批量操作结果弹窗宿主：成功计数 + 跳过明细逐行列原因（可复制），替代 \n 拼接的长 toast。
import { copyText } from '../utils/clipboard.js'
import { useToast } from '../composables/useToast.js'
import { resultState as state } from '../composables/bulkResult.js'

const toast = useToast()

async function copyAll() {
  const text = state.skipped.map(s => `#${s.id ?? ''} ${s.reason}`).join('\n')
  const ok = await copyText(text)
  ok ? toast.success('已复制跳过明细') : toast.error('复制失败')
}
</script>

<template>
  <Teleport to="body">
    <div v-if="state.visible" class="rst-overlay" @click.self="state.visible = false" @keydown.esc="state.visible = false" tabindex="-1">
      <div class="rst-box" role="dialog" :aria-label="state.title">
        <div class="rst-head">
          <h3>{{ state.title }}</h3>
          <button class="rst-close" aria-label="关闭" @click="state.visible = false">×</button>
        </div>
        <p v-if="state.okLine" class="rst-ok">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>
          {{ state.okLine }}
        </p>
        <template v-if="state.skipped.length">
          <div class="rst-skip-head">
            <span>跳过 {{ state.skipped.length }} 条（原因如下）</span>
            <button class="rst-copy" @click="copyAll">复制明细</button>
          </div>
          <ul class="rst-list">
            <li v-for="(s, i) in state.skipped" :key="i"><b v-if="s.id != null">#{{ s.id }}</b> {{ s.reason }}</li>
          </ul>
        </template>
        <div class="rst-actions"><button class="btn btn-primary" @click="state.visible = false">知道了</button></div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.rst-overlay { position: fixed; inset: 0; z-index: 3900; display: flex; align-items: center; justify-content: center; background: rgba(30,20,12,0.4); backdrop-filter: blur(3px); }
.rst-box { width: min(520px, calc(100vw - 40px)); max-height: 76vh; display: flex; flex-direction: column; background: var(--surface-2); border: 1px solid var(--border); border-radius: var(--radius); box-shadow: var(--shadow-lg); padding: 16px 18px 14px; }
.rst-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.rst-head h3 { font-size: 15px; color: var(--text); }
.rst-close { border: none; background: none; font-size: 18px; color: var(--muted); cursor: pointer; line-height: 1; }
.rst-ok { display: flex; align-items: center; gap: 6px; color: var(--c-success); font-size: 13px; font-weight: 600; margin: 4px 0 8px; }
.rst-skip-head { display: flex; align-items: center; justify-content: space-between; font-size: 12.5px; color: var(--c-warn); font-weight: 700; margin-bottom: 6px; }
.rst-copy { border: 1px solid var(--border); background: none; border-radius: 6px; font-size: 11.5px; padding: 2px 8px; color: var(--muted); cursor: pointer; }
.rst-copy:hover { color: var(--primary); border-color: var(--primary); }
.rst-list { flex: 1; overflow-y: auto; list-style: none; margin: 0; padding: 8px 10px; background: var(--surface-tint); border: 1px solid var(--border-soft); border-radius: var(--radius-sm); font-size: 12px; line-height: 1.8; color: var(--text-2); }
.rst-list b { color: var(--muted); font-weight: 600; margin-right: 4px; }
.rst-actions { display: flex; justify-content: flex-end; margin-top: 12px; }
</style>
