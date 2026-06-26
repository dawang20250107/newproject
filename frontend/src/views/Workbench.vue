<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import api from '../api/index.js'
import { useAuthStore } from '../stores/auth.js'
import { fmtCompact } from '../utils/format.js'
import EmptyState from '../components/EmptyState.vue'

const router = useRouter()
const auth = useAuthStore()
const buckets = ref([])
const loading = ref(true)
const loadErr = ref('')
const generatedAt = ref('')
const expanded = ref(new Set())   // 展开了部门联动的桶 key

const ORDER_KEY = 'pk_workbench_order'
const showAmount = computed(() => auth.canView('total_amount'))
const fmt = (n) => fmtCompact(n, { space: true, yuan: true, yi: false })

// 桶图标 + 主题
const META = {
  approval_pending: { icon: '📝', tip: '待你或团队审批的记录' },
  schedule_pending: { icon: '📅', tip: '已通过审批、等待排款流转付款' },
  payment_due:      { icon: '⏰', tip: '今日计划付款到期，请及时执行' },
  overdue:          { icon: '🔴', tip: '已过计划付款日仍未付清，需尽快跟进' },
  budget_alert:     { icon: '📊', tip: '本月排款已超出付款预算的事业部' },
}

function savedOrder() {
  try { return JSON.parse(localStorage.getItem(ORDER_KEY) || '[]') } catch { return [] }
}
function applyOrder(list) {
  const ord = savedOrder()
  if (!ord.length) return list
  const idx = k => { const i = ord.indexOf(k); return i < 0 ? 999 : i }
  return [...list].sort((a, b) => idx(a.key) - idx(b.key))
}

async function load() {
  loading.value = true; loadErr.value = ''
  try {
    const r = await api.get('/workbench')
    buckets.value = applyOrder(r.data?.buckets || [])
    generatedAt.value = r.data?.generated_at || ''
  } catch (e) {
    loadErr.value = e?.error || e?.msg || '加载失败，请刷新重试'
  } finally { loading.value = false }
}
onMounted(load)

function goBucket(b) {
  const q = b.link_query && Object.keys(b.link_query).length ? { query: b.link_query } : {}
  router.push({ path: b.link, ...q })
}
function toggleExpand(key) {
  const s = new Set(expanded.value)
  s.has(key) ? s.delete(key) : s.add(key)
  expanded.value = s
}

// ── 拖拽排序（HTML5 原生，无依赖）──
const dragKey = ref(null)
function onDragStart(b, e) { dragKey.value = b.key; e.dataTransfer.effectAllowed = 'move' }
function onDragOver(b, e) { e.preventDefault(); e.dataTransfer.dropEffect = 'move' }
function onDrop(target) {
  if (!dragKey.value || dragKey.value === target.key) { dragKey.value = null; return }
  const list = [...buckets.value]
  const from = list.findIndex(x => x.key === dragKey.value)
  const to = list.findIndex(x => x.key === target.key)
  if (from < 0 || to < 0) { dragKey.value = null; return }
  const [moved] = list.splice(from, 1)
  list.splice(to, 0, moved)
  buckets.value = list
  localStorage.setItem(ORDER_KEY, JSON.stringify(list.map(x => x.key)))
  dragKey.value = null
}
function onDragEnd() { dragKey.value = null }

const totalTodo = computed(() => buckets.value.reduce((s, b) => s + (b.count || 0), 0))
const today = new Date().toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric', weekday: 'long' })
</script>

<template>
  <div>
    <div class="topbar">
      <div>
        <h1>待办中心</h1>
        <div style="font-size:13px;color:var(--muted);margin-top:2px">
          {{ today }} · 共 <b style="color:var(--primary)">{{ totalTodo }}</b> 项待办
          <span v-if="auth.isDeptScoped" class="scope-pill">已按 {{ auth.effectiveDepts.length }} 个事业部范围联动</span>
        </div>
      </div>
      <button class="btn btn-ghost btn-sm" @click="load">刷新</button>
    </div>

    <EmptyState v-if="loading" loading />
    <EmptyState v-else-if="loadErr" :error="loadErr" />
    <EmptyState v-else-if="!buckets.length" variant="empty" text="暂无待办" />

    <template v-else>
      <p class="wb-hint">💡 拖拽卡片可自定义排序（自动记住）；点击卡片跳转到对应列表，点「按事业部」展开各部门联动明细。</p>
      <div class="wb-grid">
        <div v-for="b in buckets" :key="b.key"
             class="wb-card" :class="[`lv-${b.level}`, { dragging: dragKey === b.key, dim: !b.count }]"
             draggable="true"
             @dragstart="onDragStart(b, $event)" @dragover="onDragOver(b, $event)"
             @drop="onDrop(b)" @dragend="onDragEnd">
          <div class="wb-grip" title="拖拽排序">⋮⋮</div>
          <div class="wb-top" @click="goBucket(b)">
            <span class="wb-icon">{{ META[b.key]?.icon || '•' }}</span>
            <div class="wb-label">{{ b.label }}</div>
          </div>
          <div class="wb-count" @click="goBucket(b)">{{ b.count }}<span class="wb-unit">项</span></div>
          <div v-if="showAmount && b.key !== 'budget_alert'" class="wb-amt">{{ fmt(b.amount) }}</div>
          <div v-else-if="showAmount && b.key === 'budget_alert' && b.count" class="wb-amt danger">超 {{ fmt(b.amount) }}</div>
          <div class="wb-tip">{{ META[b.key]?.tip || '' }}</div>

          <button v-if="b.by_dept && b.by_dept.length" class="wb-deptbtn"
                  @click.stop="toggleExpand(b.key)">
            <span>按事业部 ({{ b.by_dept.length }})</span>
            <svg :class="{ rot: expanded.has(b.key) }" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"><path d="M6 9l6 6 6-6"/></svg>
          </button>
          <Transition name="wb-exp">
            <ul v-if="expanded.has(b.key) && b.by_dept.length" class="wb-deptlist">
              <li v-for="d in b.by_dept" :key="d.dept">
                <span class="wb-dname">{{ d.dept }}</span>
                <span class="wb-dcount">{{ d.count }} 项</span>
                <span v-if="showAmount" class="wb-damt">{{ fmt(d.amount) }}</span>
              </li>
            </ul>
          </Transition>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.scope-pill { display: inline-block; margin-left: 8px; font-size: 11px; padding: 1px 8px;
  border-radius: 8px; background: rgba(245,127,23,0.12); color: #b06a00; font-weight: 600; }
.wb-hint { font-size: 12.5px; color: var(--muted); margin: 0 0 14px; }

.wb-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 14px; }

.wb-card {
  position: relative; background: var(--surface-1); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 16px 16px 12px; cursor: default;
  box-shadow: var(--shadow-sm); transition: box-shadow 0.18s, transform 0.12s, border-color 0.18s;
  border-top: 3px solid var(--border);
}
.wb-card:hover { box-shadow: var(--shadow-md); transform: translateY(-2px); }
.wb-card.lv-info   { border-top-color: var(--c-info); }
.wb-card.lv-warn   { border-top-color: var(--c-warn); }
.wb-card.lv-danger { border-top-color: var(--c-danger); }
.wb-card.dragging { opacity: 0.5; }
.wb-card.dim { opacity: 0.62; }

.wb-grip { position: absolute; top: 10px; right: 10px; color: var(--muted-light); cursor: grab;
  font-size: 12px; letter-spacing: -2px; line-height: 1; user-select: none; }
.wb-grip:active { cursor: grabbing; }

.wb-top { display: flex; align-items: center; gap: 8px; cursor: pointer; }
.wb-icon { font-size: 18px; }
.wb-label { font-size: 13.5px; font-weight: 700; color: var(--text); }
.wb-count { font-size: 32px; font-weight: 800; line-height: 1.1; margin-top: 8px; color: var(--text);
  cursor: pointer; font-variant-numeric: tabular-nums; letter-spacing: -0.02em; }
.lv-danger .wb-count { color: var(--c-danger); }
.lv-warn .wb-count { color: var(--c-warn); }
.wb-unit { font-size: 14px; font-weight: 600; color: var(--muted); margin-left: 3px; }
.wb-amt { font-size: 13px; color: var(--text-2); font-variant-numeric: tabular-nums; margin-top: 2px; }
.wb-amt.danger { color: var(--c-danger); font-weight: 600; }
.wb-tip { font-size: 11.5px; color: var(--muted); line-height: 1.5; margin-top: 8px; min-height: 32px; }

.wb-deptbtn {
  display: flex; align-items: center; justify-content: center; gap: 4px; width: 100%;
  margin-top: 6px; padding: 5px; border: 1px solid var(--border-soft); border-radius: 8px;
  background: rgba(0,0,0,0.015); color: var(--muted); font-size: 11.5px; cursor: pointer;
  transition: all 0.14s;
}
.wb-deptbtn:hover { background: rgba(201,99,66,0.05); color: var(--primary); border-color: var(--border); }
.wb-deptbtn svg { transition: transform 0.18s; }
.wb-deptbtn svg.rot { transform: rotate(180deg); }
.wb-deptlist { list-style: none; margin: 8px 0 0; padding: 0; overflow: hidden; }
.wb-deptlist li { display: flex; align-items: center; gap: 8px; padding: 4px 2px;
  font-size: 12px; border-bottom: 1px solid var(--border-soft); }
.wb-deptlist li:last-child { border-bottom: none; }
.wb-dname { flex: 1; min-width: 0; color: var(--text-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wb-dcount { color: var(--muted); white-space: nowrap; }
.wb-damt { color: var(--text); font-variant-numeric: tabular-nums; white-space: nowrap; min-width: 64px; text-align: right; }

.wb-exp-enter-active, .wb-exp-leave-active { transition: opacity 0.16s; }
.wb-exp-enter-from, .wb-exp-leave-to { opacity: 0; }

@media (max-width: 640px) {
  .wb-grid { grid-template-columns: 1fr 1fr; gap: 10px; }
  .wb-count { font-size: 26px; }
  .wb-tip { display: none; }
}
</style>
