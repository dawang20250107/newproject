<script setup>
import { ref, onMounted } from 'vue'
import api from '../api/index.js'
import { useAuthStore } from '../stores/auth.js'
import { useToast } from '../composables/useToast.js'

const auth = useAuthStore()
const toast = useToast()

const activeTab = ref('approvals') // 'approvals' | 'payments'
const loading = ref(false)
const items = ref([])
const total = ref(0)
const page = ref(1)
const size = 50
const selectedIds = ref(new Set())

async function load() {
  loading.value = true
  selectedIds.value = new Set()
  try {
    const r = await api.get(`/trash/${activeTab.value}`, { params: { page: page.value, size } })
    items.value = r.data.items || []
    total.value = r.data.total || 0
  } catch (e) {
    toast.error(e?.msg || '加载失败')
  } finally {
    loading.value = false
  }
}

function switchTab(t) { activeTab.value = t; page.value = 1; load() }
onMounted(load)

function toggleSel(id) {
  if (selectedIds.value.has(id)) selectedIds.value.delete(id)
  else selectedIds.value.add(id)
}
function toggleAll() {
  if (selectedIds.value.size === items.value.length) selectedIds.value = new Set()
  else selectedIds.value = new Set(items.value.map(i => i.id))
}

const busy = ref(false)
async function doAction(action) {
  if (!selectedIds.value.size) { toast.warn('请先选择记录'); return }
  const label = action === 'restore' ? '还原' : '彻底删除'
  if (action === 'purge' && !confirm(`彻底删除 ${selectedIds.value.size} 条记录？此操作不可撤销。`)) return
  busy.value = true
  try {
    const r = await api.post(`/trash/${activeTab.value}`, { action, ids: [...selectedIds.value] })
    toast.success(`已${label} ${r.data.count} 条`)
    load()
  } catch (e) {
    toast.error(e?.msg || '操作失败')
  } finally {
    busy.value = false }
}

function fmtDate(s) {
  if (!s) return '-'
  return s.replace('T', ' ').slice(0, 16)
}
</script>

<template>
  <div class="trash-page">
    <div class="trash-header">
      <h2 class="trash-title">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="color:var(--c-danger)">
          <polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4h6v2"/>
        </svg>
        回收站
      </h2>
      <div class="trash-tabs">
        <button :class="['ttab', activeTab === 'approvals' ? 'active' : '']" @click="switchTab('approvals')">审批管理</button>
        <button :class="['ttab', activeTab === 'payments' ? 'active' : '']" @click="switchTab('payments')">付款管理</button>
      </div>
      <div class="trash-actions" v-if="auth.canDelete">
        <button class="tact-btn restore" :disabled="!selectedIds.size || busy" @click="doAction('restore')">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 109-9H3"/><polyline points="3 3 3 9 9 9"/></svg>
          还原
        </button>
        <button class="tact-btn purge" :disabled="!selectedIds.size || busy" @click="doAction('purge')">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/></svg>
          彻底删除
        </button>
      </div>
    </div>
    <div class="trash-hint">回收站内的记录不计入列表和统计；可还原恢复，或彻底删除永久清除。</div>

    <div class="trash-card">
      <div v-if="loading" class="trash-loading">加载中…</div>
      <div v-else-if="!items.length" class="trash-empty">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" style="color:var(--muted-light)">
          <polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4h6v2"/>
        </svg>
        <p>回收站为空</p>
      </div>
      <template v-else>
        <table class="trash-tbl">
          <thead>
            <tr>
              <th class="sel-col"><input type="checkbox" :checked="selectedIds.size === items.length && items.length > 0" @change="toggleAll"/></th>
              <th v-if="activeTab === 'approvals'">申请人</th>
              <th>部门</th>
              <th v-if="activeTab === 'approvals'">审批编号</th>
              <th v-if="activeTab === 'approvals'">摘要</th>
              <th v-if="activeTab === 'payments'">付款事项</th>
              <th v-if="activeTab === 'payments'">收款方</th>
              <th>金额</th>
              <th>删除时间</th>
              <th>删除人</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="it in items" :key="it.id" :class="{ 'row-sel': selectedIds.has(it.id) }" @click="toggleSel(it.id)" style="cursor:pointer">
              <td class="sel-col" @click.stop><input type="checkbox" :checked="selectedIds.has(it.id)" @change="toggleSel(it.id)"/></td>
              <td v-if="activeTab === 'approvals'">{{ it.applicant }}</td>
              <td>{{ it.department }}</td>
              <td v-if="activeTab === 'approvals'">{{ it.approval_number }}</td>
              <td v-if="activeTab === 'approvals'" class="ellipsis" :title="it.summary">{{ it.summary }}</td>
              <td v-if="activeTab === 'payments'" class="ellipsis" :title="it.project_desc">{{ it.project_desc }}</td>
              <td v-if="activeTab === 'payments'" class="ellipsis">{{ it.payee }}</td>
              <td class="mono">{{ activeTab === 'approvals' ? it.amount : it.total_amount }}</td>
              <td class="mono muted">{{ fmtDate(it.deleted_at) }}</td>
              <td class="muted">{{ it.deleted_by_name || '-' }}</td>
            </tr>
          </tbody>
        </table>
        <div class="trash-footer">
          <span class="trash-count">共 {{ total }} 条</span>
          <div class="trash-pg" v-if="total > size">
            <button :disabled="page === 1" @click="page--; load()">上一页</button>
            <span>{{ page }}</span>
            <button :disabled="page * size >= total" @click="page++; load()">下一页</button>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.trash-page { padding: 24px; max-width: 1100px; }
.trash-header { display: flex; align-items: center; gap: 16px; margin-bottom: 6px; flex-wrap: wrap; }
.trash-title { display: flex; align-items: center; gap: 8px; font-size: 20px; font-weight: 700; color: var(--text); }
.trash-tabs { display: flex; gap: 4px; background: rgba(0,0,0,0.05); border-radius: 10px; padding: 3px; }
.ttab { border: none; background: none; padding: 5px 16px; border-radius: 8px; font-size: 13px; font-weight: 600;
  color: var(--muted); cursor: pointer; transition: all 0.16s; }
.ttab.active { background: #fff; color: var(--text); box-shadow: 0 1px 4px rgba(0,0,0,0.1); }
.trash-actions { display: flex; gap: 8px; margin-left: auto; }
.tact-btn { display: inline-flex; align-items: center; gap: 6px; padding: 6px 14px; border-radius: 8px;
  font-size: 13px; font-weight: 600; cursor: pointer; border: none; transition: all 0.16s; }
.tact-btn:disabled { opacity: .45; cursor: default; }
.tact-btn.restore { background: var(--c-success-bg); color: var(--c-success); border: 1px solid var(--c-success-bdr); }
.tact-btn.restore:hover:not(:disabled) { background: var(--c-success); color: #fff; }
.tact-btn.purge { background: var(--c-danger-bg); color: var(--c-danger); border: 1px solid var(--c-danger-bdr); }
.tact-btn.purge:hover:not(:disabled) { background: var(--c-danger); color: #fff; }

.trash-hint { font-size: 12.5px; color: var(--muted); margin-bottom: 16px; }
.trash-card { background: rgba(255,253,250,0.90); border-radius: var(--radius); border: 1px solid rgba(255,255,255,0.65);
  box-shadow: 0 2px 12px rgba(100,60,30,0.09); overflow-x: auto; }
@media (max-width: 768px) {
  .trash-page { padding: 14px; }
  .trash-header { gap: 10px; }
  .trash-actions { width: 100%; margin-left: 0; }
}

.trash-loading, .trash-empty { text-align: center; padding: 60px 20px; color: var(--muted); }
.trash-empty { display: flex; flex-direction: column; align-items: center; gap: 12px; }
.trash-empty p { font-size: 14px; }

.trash-tbl { width: 100%; border-collapse: collapse; table-layout: auto; }
.trash-tbl th, .trash-tbl td { padding: var(--td-py) var(--td-px); font-size: var(--td-fs); border-bottom: 1px solid var(--border-soft);
  text-align: left; white-space: nowrap; }
.trash-tbl th { background: #f4f1ef; font-weight: 600; font-size: 12px; color: var(--text-2); }
.trash-tbl tr:last-child td { border-bottom: none; }
.trash-tbl tr.row-sel td { background: rgba(201,99,66,0.06); }
.sel-col { width: 34px; text-align: center !important; }
.ellipsis { max-width: 200px; overflow: hidden; text-overflow: ellipsis; }
.mono { font-variant-numeric: tabular-nums; }
.muted { color: var(--muted); font-size: 12px; }

.trash-footer { display: flex; align-items: center; justify-content: space-between;
  padding: 10px 16px; background: rgba(0,0,0,0.02); border-top: 1px solid var(--border-soft); }
.trash-count { font-size: 12.5px; color: var(--muted); }
.trash-pg { display: flex; align-items: center; gap: 8px; font-size: 13px; }
.trash-pg button { padding: 3px 10px; border: 1px solid var(--border); border-radius: 6px; background: none;
  cursor: pointer; font-size: 12.5px; }
.trash-pg button:disabled { opacity: .4; cursor: default; }
</style>
