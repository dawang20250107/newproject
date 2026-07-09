<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import api from '../../api/caiwu.js'

const router = useRouter()

// 默认核对「上一个自然月」：关账通常发生在次月初
const now = new Date()
const prev = new Date(now.getFullYear(), now.getMonth() - 1, 1)
const year = ref(prev.getFullYear())
const month = ref(prev.getMonth() + 1)
const years = Array.from({ length: 5 }, (_, i) => now.getFullYear() - 3 + i)
const months = Array.from({ length: 12 }, (_, i) => i + 1)

const loading = ref(false)
const loadErr = ref('')
const data = ref(null)

async function load() {
  loading.value = true
  loadErr.value = ''
  try {
    const res = await api.get('/close-checklist',
                              { params: { year: year.value, month: month.value } })
    data.value = res.data
  } catch (e) {
    loadErr.value = e?.error || e?.msg || '加载失败，请刷新重试'
    data.value = null
  } finally { loading.value = false }
}
onMounted(load)

const STATUS_META = {
  ok:   { icon: '✓', label: '已就绪', cls: 'st-ok' },
  warn: { icon: '!', label: '需关注', cls: 'st-warn' },
  todo: { icon: '✕', label: '未完成', cls: 'st-todo' },
}
const meta = s => STATUS_META[s] || STATUS_META.warn
// 未完成在前、需关注居中、已就绪沉底：一眼看到还差什么
const ORDER = { todo: 0, warn: 1, ok: 2 }
const sortedItems = computed(() =>
  [...(data.value?.items || [])].sort((a, b) => ORDER[a.status] - ORDER[b.status]))
const allClear = computed(() => {
  const s = data.value?.summary
  return s && s.todo === 0 && s.warn === 0
})
function goto(item) { if (item.link) router.push(item.link) }
</script>

<template>
  <div class="page">
    <div class="topbar" style="align-items:flex-start">
      <div>
        <h1>月末关账清单</h1>
        <div style="font-size:13px;color:var(--muted);margin-top:2px">
          关账前一页看清：报表提交 / 毛利导入 / 内往轧平 / 预算达成 / 逾期与在途处理，逐项直达
        </div>
      </div>
    </div>

    <div class="cc-bar">
      <select v-model.number="year" class="sel" @change="load">
        <option v-for="y in years" :key="y" :value="y">{{ y }} 年</option>
      </select>
      <select v-model.number="month" class="sel" @change="load">
        <option v-for="m in months" :key="m" :value="m">{{ m }} 月</option>
      </select>
      <button class="btn btn-ghost btn-sm" :disabled="loading" @click="load">
        {{ loading ? '核对中…' : '↻ 重新核对' }}
      </button>
      <template v-if="data">
        <div class="cc-chips">
          <span class="chip chip-todo" v-if="data.summary.todo">✕ 未完成 {{ data.summary.todo }}</span>
          <span class="chip chip-warn" v-if="data.summary.warn">! 需关注 {{ data.summary.warn }}</span>
          <span class="chip chip-ok">✓ 已就绪 {{ data.summary.ok }}/{{ data.summary.total }}</span>
        </div>
      </template>
    </div>

    <div v-if="loadErr" class="cc-err">⚠️ {{ loadErr }}
      <button class="cc-retry" @click="load">重试</button>
    </div>

    <div v-else-if="allClear" class="cc-allclear">
      🎉 {{ year }} 年 {{ month }} 月全部 {{ data.summary.total }} 项检查通过，可以关账
    </div>

    <div v-if="data" class="cc-list">
      <div v-for="it in sortedItems" :key="it.key" class="cc-item" :class="meta(it.status).cls"
           @click="goto(it)" role="button" :title="'前往处理：' + it.link">
        <span class="cc-light">{{ meta(it.status).icon }}</span>
        <div class="cc-main">
          <div class="cc-label">{{ it.label }}
            <span class="cc-status">{{ meta(it.status).label }}</span>
          </div>
          <div class="cc-value">{{ it.value }}</div>
          <div v-if="it.detail" class="cc-detail">{{ it.detail }}</div>
        </div>
        <span class="cc-go">前往处理 →</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.cc-bar { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; flex-wrap: wrap; }
.cc-chips { display: flex; gap: 8px; margin-left: auto; }
.chip { padding: 4px 12px; border-radius: 999px; font-size: 12.5px; font-weight: 700; }
.chip-ok   { background: rgba(46,125,50,.1);  color: var(--c-success); }
.chip-warn { background: rgba(245,127,23,.12); color: #b35309; }
.chip-todo { background: rgba(198,40,40,.1);  color: var(--c-danger); }

.cc-err { padding: 14px; border-radius: 10px; background: rgba(198,40,40,.07);
  border: 1px solid rgba(198,40,40,.2); color: var(--c-danger); font-size: 13.5px; }
.cc-retry { border: none; background: none; color: var(--primary); cursor: pointer;
  text-decoration: underline; font-size: 13px; margin-left: 8px; }
.cc-allclear { padding: 16px 18px; border-radius: 12px; margin-bottom: 14px;
  background: rgba(46,125,50,.08); border: 1px solid rgba(46,125,50,.25);
  color: var(--c-success); font-size: 15px; font-weight: 700; }

.cc-list { display: flex; flex-direction: column; gap: 8px; }
.cc-item { display: flex; align-items: center; gap: 14px; padding: 13px 16px;
  border-radius: 11px; background: var(--card); border: 1px solid var(--border);
  cursor: pointer; transition: transform .12s, box-shadow .12s, border-color .12s; }
.cc-item:hover { transform: translateX(3px); border-color: var(--primary);
  box-shadow: 0 3px 12px rgba(0,0,0,.06); }
.cc-item:hover .cc-go { opacity: 1; }

.cc-light { width: 30px; height: 30px; border-radius: 50%; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  font-size: 15px; font-weight: 800; color: #fff; }
.st-ok   .cc-light { background: var(--c-success); }
.st-warn .cc-light { background: #f57f17; }
.st-todo .cc-light { background: var(--c-danger); }

.cc-main { flex: 1; min-width: 0; }
.cc-label { font-size: 14px; font-weight: 700; color: var(--text); }
.cc-status { font-size: 11px; font-weight: 600; margin-left: 8px; padding: 1px 8px;
  border-radius: 999px; background: var(--surface-2, rgba(120,120,120,.1)); color: var(--muted); }
.st-todo .cc-status { background: rgba(198,40,40,.1); color: var(--c-danger); }
.st-warn .cc-status { background: rgba(245,127,23,.12); color: #b35309; }
.st-ok   .cc-status { background: rgba(46,125,50,.1); color: var(--c-success); }
.cc-value { font-size: 13px; color: var(--text-2, var(--text)); margin-top: 2px; }
.cc-detail { font-size: 12px; color: var(--muted); margin-top: 1px; }
@media (hover: none) { .cc-go { opacity: 1 !important; } }
.cc-go { font-size: 12.5px; color: var(--primary); white-space: nowrap;
  opacity: 0; transition: opacity .12s; flex-shrink: 0; }
</style>
