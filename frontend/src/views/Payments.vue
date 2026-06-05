<script setup>
import { ref, onMounted, onBeforeUnmount, reactive, computed } from 'vue'
import api from '../api/index.js'
import { useAuthStore } from '../stores/auth.js'
import { todayCST } from '../constants.js'
import { fmtCompact, fmtTime } from '../utils/format.js'
import { downloadBlob } from '../utils/download.js'
import StatusBadge from '../components/StatusBadge.vue'
import PaymentModal from '../components/PaymentModal.vue'
import EmptyState from '../components/EmptyState.vue'

const auth = useAuthStore()

// Column visibility from field-level view permissions.
const showPaid = computed(() => auth.canView('installments'))
const showRemaining = computed(() => auth.canView('total_amount') && showPaid.value)
function dash(v) { return v === null || v === undefined ? '—' : fmt(v) }
const items = ref([])
const total = ref(0)
const outstandingTotal = ref('0')
const outstandingCount = ref(0)
const loading = ref(false)
const departments = ref([])
const showModal = ref(false)
const editItem = ref(null)
const loadErr = ref('')
const today = todayCST()  // UTC+8，与服务端 Asia/Shanghai 保持一致

const filters = reactive({
  q: '', dept: '', status: '', start_date: '', end_date: '',
  page: 1, size: 50,
})

// Show only departments within the user's currently-active scope.
const deptChoices = computed(() => {
  const scope = auth.effectiveDepts
  if (auth.isAdmin && !auth.activeDepts.length) return departments.value
  return departments.value.filter(d => scope.includes(d))
})

// Hover tooltip card for truncated long cells (付款事项 / 收款方).
const tip = reactive({ show: false, text: '', x: 0, y: 0 })
function showTip(e, text) {
  if (!text) return
  tip.text = text
  positionTip(e)
  tip.show = true
}
function positionTip(e) {
  tip.x = Math.min(e.clientX + 16, window.innerWidth - 340)
  tip.y = Math.min(e.clientY + 18, window.innerHeight - 60)
}
function moveTip(e) { if (tip.show) positionTip(e) }
function hideTip() { tip.show = false }

// 万级单位（不启用「亿」），单位前带空格；空值显示 0.00（保持原表现）
const fmt = (n) => fmtCompact(n, { space: true, yi: false, dash: '0.00' })

function daysOverdue(plannedDate) {
  if (!plannedDate) return 0
  const a = new Date(today + 'T00:00:00')
  const b = new Date(plannedDate + 'T00:00:00')
  return Math.max(0, Math.round((a - b) / 86400000))
}

// ── Excel import / export / template ──────────────────────────────────────────
const importInputRef = ref(null)
const importing = ref(false)
const exportingXlsx = ref(false)
const importResult = ref(null)

async function downloadTemplate() {
  try {
    // Interceptor returns res.data, so for a blob request this IS the Blob.
    const blob = await api.get('/payments/template', { responseType: 'blob', timeout: 60000 })
    triggerDownload(blob, '排款导入模板.xlsx')
  } catch { alert('模板下载失败') }
}

function triggerImport() {
  importResult.value = null
  importInputRef.value.click()
}

async function onImportFile(e) {
  const file = e.target.files[0]
  if (!file) return
  importing.value = true
  importResult.value = null
  const formData = new FormData()
  formData.append('file', file)
  try {
    const res = await api.post('/payments/import', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 60000,
    })
    importResult.value = res.data
    if (res.data.created > 0) load()
  } catch (ex) {
    importResult.value = { error: ex?.msg || '导入失败，请检查文件格式' }
  } finally {
    importing.value = false
    e.target.value = ''
  }
}

async function exportExcel() {
  exportingXlsx.value = true
  try {
    const params = Object.fromEntries(
      Object.entries(filters).filter(([k, v]) => v !== '' && k !== 'page' && k !== 'size')
    )
    const blob = await api.get('/payments/export', { params, responseType: 'blob', timeout: 60000 })
    const date = new Date().toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' }).replace('/', '月') + '日'
    triggerDownload(blob, `排款记录_${date}.xlsx`)
  } catch (e) { alert(e?.msg || '导出失败，请稍后重试') }
  finally { exportingXlsx.value = false }
}

const triggerDownload = downloadBlob

async function load() {
  loading.value = true
  loadErr.value = ''
  try {
    const params = Object.fromEntries(Object.entries(filters).filter(([, v]) => v !== ''))
    const res = await api.get('/payments', { params })
    items.value = res.data.items
    total.value = res.data.total
    outstandingTotal.value = res.data.outstanding_total ?? '0'
    outstandingCount.value = res.data.outstanding_count ?? 0
  } catch (e) {
    loadErr.value = e?.msg || '加载失败，请刷新重试'
  } finally {
    loading.value = false
  }
}

async function loadDepts() {
  try {
    const res = await api.get('/departments')
    departments.value = res.data
  } catch {}
}

// Reload list when the global active-dept scope changes.
const onScopeChange = () => {
  if (filters.dept && !auth.effectiveDepts.includes(filters.dept)) filters.dept = ''
  filters.page = 1
  load()
}
onMounted(() => {
  load(); loadDepts()
  window.addEventListener('pk:depts-changed', onScopeChange)
})
onBeforeUnmount(() => window.removeEventListener('pk:depts-changed', onScopeChange))

function openAdd() { editItem.value = null; showModal.value = true }
function openEdit(p) { editItem.value = p; showModal.value = true }

// ── change-log drawer ─────────────────────────────────────────────────────────
const logsOpen = ref(false)
const logsTarget = ref(null)
const logs = ref([])
const logsLoading = ref(false)
async function openLogs(p) {
  logsTarget.value = p; logsOpen.value = true; logsLoading.value = true; logs.value = []
  try {
    const res = await api.get(`/payments/${p.id}/logs`)
    logs.value = res.data.items || []
  } catch (e) {
    logs.value = []
  } finally { logsLoading.value = false }
}
function actionLabel(a) { return { create: '新建', update: '修改', delete: '删除' }[a] || a }
function onSaved(p) {
  showModal.value = false
  load()
  loadDepts()
}

async function onDelete(p) {
  if (!confirm(`确定删除「${p.project_desc}」？此操作不可撤销。`)) return
  try {
    await api.delete(`/payments/${p.id}`)
    load()
  } catch (e) {
    alert(e?.msg || '删除失败')
  }
}

function search() { filters.page = 1; load() }
function resetFilters() {
  Object.assign(filters, { q: '', dept: '', status: '', start_date: '', end_date: '', page: 1 })
  load()
}

function setPage(p) { filters.page = p; load() }
</script>

<template>
  <div>
    <div class="topbar">
      <h1>付款台账</h1>
      <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
        <button class="btn btn-ghost btn-sm" @click="downloadTemplate" title="下载Excel导入模板">
          <span style="margin-right:4px">⬇</span>模板
        </button>
        <button class="btn btn-ghost btn-sm" :disabled="importing" @click="triggerImport">
          <span v-if="importing" class="btn-spin"></span>
          <span v-else style="margin-right:4px">📥</span>{{ importing ? '导入中…' : '导入' }}
        </button>
        <button class="btn btn-ghost btn-sm" :disabled="exportingXlsx" @click="exportExcel">
          <span v-if="exportingXlsx" class="btn-spin"></span>
          <span v-else style="margin-right:4px">📤</span>{{ exportingXlsx ? '导出中…' : '导出' }}
        </button>
        <button v-if="auth.canCreate" class="btn btn-primary" @click="openAdd">+ 新增排款</button>
      </div>
    </div>

    <!-- hidden file input for import -->
    <input ref="importInputRef" type="file" accept=".xlsx,.xls" style="display:none" @change="onImportFile" />

    <div class="card" style="margin-bottom:16px">
      <div class="filter-bar">
        <input v-model="filters.q" placeholder="搜索事项/收款方/单号/申请人…" style="min-width:200px" @keyup.enter="search" />
        <select v-model="filters.dept" @change="search">
          <option value="">全部部门</option>
          <option v-for="d in deptChoices" :key="d" :value="d">{{ d }}</option>
        </select>
        <select v-model="filters.status" @change="search">
          <option value="">全部状态</option>
          <option value="pending">⏳ 待付款</option>
          <option value="partial">⚡ 部分付款</option>
          <option value="settled">✅ 已付清</option>
          <option value="adjusted">📋 计划调整</option>
          <option value="overdue">⚠ 已逾期</option>
        </select>
        <input v-model="filters.start_date" type="date" style="min-width:130px" @change="search" />
        <input v-model="filters.end_date" type="date" style="min-width:130px" @change="search" />
        <button class="btn btn-ghost btn-sm" @click="search">筛选</button>
        <button class="btn btn-sm" style="background:var(--bg2);border:none" @click="resetFilters">重置</button>
      </div>

      <div class="list-meta">
        <div class="list-count">共 <b>{{ total }}</b> 条记录</div>
        <div v-if="showRemaining" class="outstanding-card" :class="{ 'has-data': outstandingCount > 0 }">
          已计划未结清共计：<b>{{ fmt(outstandingTotal) }}</b> 元（{{ outstandingCount }} 笔）
        </div>
      </div>

      <EmptyState v-if="loading" loading />
      <EmptyState v-else-if="loadErr" :error="loadErr" />
      <EmptyState v-else-if="!items.length" empty />

      <div v-else class="table-wrap">
        <table>
          <thead>
            <tr>
              <th v-if="auth.canView('department')">部门</th>
              <th v-if="auth.canView('applicant')">申请人</th>
              <th v-if="auth.canView('approval_number')">审批单号</th>
              <th v-if="auth.canView('project_desc')">付款事项</th>
              <th v-if="auth.canView('payee')">收款方</th>
              <th v-if="auth.canView('planned_date')">计划日期</th>
              <th v-if="auth.canView('total_amount')">计划总额 (元)</th>
              <th v-if="showPaid">已付 (元)</th>
              <th v-if="showRemaining">剩余 (元)</th>
              <th>状态</th>
              <th>逾期</th>
              <th v-if="auth.canView('plan_adjustment')">计划调整金额</th>
              <th v-if="auth.canWrite || auth.canDelete">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="p in items" :key="p.id"
              :class="{ 'overdue-row': p.status !== 'settled' && p.planned_date && p.planned_date < today }">
              <td v-if="auth.canView('department')">{{ p.department }}</td>
              <td v-if="auth.canView('applicant')">{{ p.applicant || '—' }}</td>
              <td v-if="auth.canView('approval_number')">{{ p.approval_number || '—' }}</td>
              <td v-if="auth.canView('project_desc')" class="cell-clip cell-desc"
                @mouseenter="showTip($event, p.project_desc)" @mousemove="moveTip" @mouseleave="hideTip">
                <span v-if="p.project_no" class="proj-no">{{ p.project_no }}</span>{{ p.project_desc }}
              </td>
              <td v-if="auth.canView('payee')" class="cell-clip cell-payee"
                @mouseenter="showTip($event, p.payee)" @mousemove="moveTip" @mouseleave="hideTip">
                {{ p.payee }}
              </td>
              <td v-if="auth.canView('planned_date')">{{ p.planned_date }}</td>
              <td v-if="auth.canView('total_amount')" class="amt">{{ dash(p.total_amount) }}</td>
              <td v-if="showPaid" class="amt amt-green">{{ dash(p.total_paid) }}</td>
              <td v-if="showRemaining" class="amt" :class="parseFloat(p.remaining) > 0 ? 'amt-red' : ''">{{ dash(p.remaining) }}</td>
              <td><StatusBadge :status="p.status" /></td>
              <td>
                <span v-if="p.status === 'settled'" class="overdue-tag overdue-ok">—</span>
                <span v-else-if="p.planned_date && p.planned_date < today"
                      class="overdue-tag overdue-bad">逾期 {{ daysOverdue(p.planned_date) }} 天</span>
                <span v-else-if="p.planned_date === today" class="overdue-tag overdue-today">今日到期</span>
                <span v-else class="overdue-tag overdue-ok">未到期</span>
              </td>
              <td v-if="auth.canView('plan_adjustment')" class="amt">
                <span v-if="p.plan_adjustment != null" style="color:#1565c0;font-weight:600">
                  调整→{{ fmt(p.plan_adjustment) }}
                </span>
                <span v-else style="color:var(--muted)">—</span>
              </td>
              <td v-if="auth.canWrite || auth.canDelete">
                <div style="display:flex;gap:6px">
                  <button v-if="auth.canWrite" class="btn btn-ghost btn-sm" @click="openEdit(p)">编辑</button>
                  <button class="btn btn-ghost btn-sm" @click="openLogs(p)">日志</button>
                  <button v-if="auth.canDelete" class="btn btn-danger btn-sm" @click="onDelete(p)">删除</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- pagination -->
      <div class="pagination">
        <span>第 {{ filters.page }} 页，共 {{ Math.ceil(total / filters.size) || 1 }} 页</span>
        <button :disabled="filters.page <= 1" @click="setPage(filters.page - 1)">上一页</button>
        <button :disabled="filters.page * filters.size >= total" @click="setPage(filters.page + 1)">下一页</button>
      </div>
    </div>

    <PaymentModal
      v-if="showModal"
      :payment="editItem"
      :departments="departments"
      @saved="onSaved"
      @close="showModal = false"
    />

    <!-- import result popup -->
    <div v-if="importResult" class="overlay" @click.self="importResult = null">
      <div class="modal" style="width:520px">
        <div class="modal-header">
          <h3 v-if="importResult.error">导入失败</h3>
          <h3 v-else>导入完成</h3>
          <button class="modal-close" @click="importResult = null">×</button>
        </div>

        <!-- hard error (whole file rejected) -->
        <div v-if="importResult.error" class="imp-hero imp-hero-err">
          <div class="imp-emoji">⚠️</div>
          <div class="imp-msg">{{ importResult.error }}</div>
        </div>

        <template v-else>
          <!-- summary -->
          <div class="imp-summary">
            <div class="imp-stat imp-stat-ok">
              <div class="imp-num">{{ importResult.created }}</div>
              <div class="imp-lbl">成功导入</div>
            </div>
            <div class="imp-stat" :class="importResult.skipped ? 'imp-stat-skip' : ''">
              <div class="imp-num">{{ importResult.skipped || 0 }}</div>
              <div class="imp-lbl">跳过 / 未通过</div>
            </div>
          </div>

          <!-- highlighted list of skipped / non-compliant rows -->
          <div v-if="importResult.message" class="imp-msg-banner">{{ importResult.message }}</div>

          <div v-if="importResult.errors?.length" class="imp-errbox">
            <div class="imp-errtitle">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/>
                <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
              </svg>
              以下 {{ importResult.errors.length }} 行未通过校验，已跳过：
            </div>
            <ul class="imp-errlist">
              <li v-for="(e, i) in importResult.errors" :key="i">{{ e }}</li>
            </ul>
          </div>

          <div v-else-if="!importResult.skipped" class="imp-allok">🎉 全部数据校验通过，无跳过项。</div>
        </template>

        <div class="modal-footer">
          <button class="btn btn-primary" @click="importResult = null">我知道了</button>
        </div>
      </div>
    </div>

    <!-- Change log drawer -->
    <Teleport to="body">
      <div v-if="logsOpen" class="logs-overlay" @click.self="logsOpen = false">
        <div class="logs-panel">
          <div class="logs-header">
            <div>
              <h3>变更日志</h3>
              <div class="logs-sub" v-if="logsTarget">排款 #{{ logsTarget.id }} · {{ logsTarget.project_desc }}</div>
            </div>
            <button class="modal-close" @click="logsOpen = false">×</button>
          </div>
          <div class="logs-body">
            <EmptyState v-if="logsLoading" loading />
            <EmptyState v-else-if="!logs.length" empty text="暂无变更记录" />
            <ul v-else class="logs-list">
              <li v-for="l in logs" :key="l.id" class="logs-item" :class="`logs-${l.action}`">
                <div class="logs-meta">
                  <span class="logs-action">{{ actionLabel(l.action) }}</span>
                  <span class="logs-field">{{ l.field_label || '—' }}</span>
                  <span class="logs-by">{{ l.operator_name || '系统' }}</span>
                  <span class="logs-time">{{ fmtTime(l.at) }}</span>
                </div>
                <div v-if="l.action === 'update'" class="logs-diff">
                  <span class="logs-old">{{ l.old_value || '空' }}</span>
                  <span class="logs-arrow">→</span>
                  <span class="logs-new">{{ l.new_value || '空' }}</span>
                </div>
                <div v-else class="logs-summary">{{ l.new_value || l.old_value }}</div>
              </li>
            </ul>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- hover tooltip card for long cells -->
    <Transition name="tip-fade">
      <div v-if="tip.show" class="cell-tooltip" :style="{ left: tip.x + 'px', top: tip.y + 'px' }">
        {{ tip.text }}
      </div>
    </Transition>
  </div>
</template>

<style scoped>
/* List meta row: count + outstanding summary card */
.list-meta {
  display: flex; align-items: center; justify-content: space-between;
  gap: 12px; margin-bottom: 10px; flex-wrap: wrap;
}
.list-count { font-size: 13px; color: var(--muted); }
.outstanding-card {
  font-size: 12px; color: var(--muted);
  background: rgba(201,99,66,0.06); border: 1px solid rgba(201,99,66,0.18);
  border-radius: 10px; padding: 6px 10px; white-space: nowrap;
}
.outstanding-card.has-data { color: #8a4d2f; background: rgba(201,99,66,0.08); border-color: rgba(201,99,66,0.25); }
.outstanding-card b { color: #c96342; font-weight: 700; }

/* Overdue column tag */
.overdue-tag {
  display: inline-block; font-size: 11.5px; padding: 2px 8px;
  border-radius: 9px; white-space: nowrap;
}
.overdue-ok    { color: var(--muted); background: transparent; }
.overdue-today { color: #b35309; background: rgba(245,127,23,0.12); font-weight: 600; }
.overdue-bad   { color: #c62828; background: rgba(198,40,40,0.10); font-weight: 700; }

/* truncated long cells + hover tooltip card */
.cell-clip {
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: default;
}
.cell-desc { max-width: 160px; }
.proj-no { display: inline-block; margin-right: 6px; padding: 0 6px; border-radius: 5px; background: rgba(201,99,66,0.1); color: var(--primary); font-size: 11px; font-weight: 600; }
.cell-payee { max-width: 110px; }
.cell-tooltip {
  position: fixed;
  z-index: 9000;
  max-width: 320px;
  padding: 10px 14px;
  border-radius: 12px;
  background: rgba(36, 18, 10, 0.94);
  color: #f3e7dc;
  font-size: 13px;
  line-height: 1.55;
  white-space: normal;
  word-break: break-word;
  box-shadow: 0 10px 30px rgba(20, 8, 4, 0.4);
  border: 1px solid rgba(255,255,255,0.1);
  pointer-events: none;
  backdrop-filter: blur(6px);
}
.tip-fade-enter-active, .tip-fade-leave-active { transition: opacity 0.14s ease; }
.tip-fade-enter-from, .tip-fade-leave-to { opacity: 0; }

/* import result popup */
.imp-hero { display: flex; flex-direction: column; align-items: center; gap: 10px; padding: 14px 0 8px; text-align: center; }
.imp-emoji { font-size: 44px; }
.imp-msg { font-size: 14px; line-height: 1.6; }
.imp-hero-err .imp-msg { color: #c62828; }
.imp-summary { display: flex; gap: 14px; margin-bottom: 16px; }
.imp-stat {
  flex: 1; text-align: center; padding: 16px 10px;
  border-radius: 14px; border: 1px solid var(--border);
  background: rgba(255,253,250,0.6);
}
.imp-stat-ok { background: rgba(46,125,50,0.08); border-color: rgba(46,125,50,0.25); }
.imp-stat-skip { background: rgba(245,127,23,0.09); border-color: rgba(245,127,23,0.3); }
.imp-num { font-size: 30px; font-weight: 800; line-height: 1; }
.imp-stat-ok .imp-num { color: #2e7d32; }
.imp-stat-skip .imp-num { color: #e65100; }
.imp-lbl { font-size: 12px; color: var(--muted); margin-top: 6px; letter-spacing: 0.03em; }
.imp-errbox {
  border-radius: 12px; border: 1px solid rgba(245,127,23,0.3);
  background: rgba(245,127,23,0.06); overflow: hidden;
}
.imp-errtitle {
  display: flex; align-items: center; gap: 7px;
  padding: 10px 14px; font-size: 12.5px; font-weight: 600; color: #e65100;
  background: rgba(245,127,23,0.1);
}
.imp-errtitle svg { flex-shrink: 0; }
.imp-errlist {
  margin: 0; padding: 8px 14px 10px 30px;
  max-height: 240px; overflow-y: auto;
  font-size: 12.5px; line-height: 1.7; color: #b35309;
}
.imp-allok { text-align: center; color: #2e7d32; font-size: 13.5px; padding: 6px 0 4px; }
.imp-msg-banner {
  font-size: 13px; color: #5a4030; background: rgba(201,99,66,0.07);
  border: 1px solid rgba(201,99,66,0.18); border-radius: 8px;
  padding: 8px 14px; margin-bottom: 12px; line-height: 1.5;
}
.btn-spin {
  display: inline-block;
  width: 11px; height: 11px;
  border-radius: 50%;
  border: 2px solid rgba(0,0,0,0.2);
  border-top-color: var(--primary);
  animation: spin 0.7s linear infinite;
  margin-right: 4px;
  vertical-align: middle;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* ── Change-log drawer ── */
.logs-overlay {
  position: fixed; inset: 0; z-index: 9100;
  background: rgba(20,10,5,0.42);
  display: flex; align-items: center; justify-content: center;
  padding: 20px;
}
.logs-panel {
  width: min(720px, 96vw); max-height: 80vh; background: #fffaf3;
  border-radius: 16px; overflow: hidden;
  display: flex; flex-direction: column;
  box-shadow: 0 16px 48px rgba(20,10,5,0.28);
  animation: logsUp 0.26s cubic-bezier(0.34,1.5,0.64,1);
}
@keyframes logsUp { from { transform: translateY(16px) scale(0.97); opacity: 0; } to { transform: translateY(0) scale(1); opacity: 1; } }
.logs-header {
  display: flex; align-items: flex-start; justify-content: space-between;
  padding: 16px 22px 12px; border-bottom: 1px solid rgba(0,0,0,0.06);
}
.logs-header h3 { font-size: 16px; font-weight: 700; margin: 0; }
.logs-sub { font-size: 12px; color: var(--muted); margin-top: 3px; max-width: 540px;
            overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.logs-body { padding: 12px 22px 22px; overflow-y: auto; }
.logs-list { list-style: none; padding: 0; margin: 0; }
.logs-item {
  padding: 10px 12px; border-radius: 9px; margin-bottom: 6px;
  background: rgba(0,0,0,0.02); border-left: 3px solid var(--border);
}
.logs-create { border-left-color: #2e7d32; }
.logs-update { border-left-color: #1565c0; }
.logs-delete { border-left-color: #c62828; }
.logs-meta {
  display: flex; gap: 12px; align-items: center; flex-wrap: wrap;
  font-size: 12px; color: var(--muted); margin-bottom: 4px;
}
.logs-action {
  font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 8px;
  color: #fff;
}
.logs-create .logs-action { background: #2e7d32; }
.logs-update .logs-action { background: #1565c0; }
.logs-delete .logs-action { background: #c62828; }
.logs-field { font-weight: 600; color: var(--text); }
.logs-by { margin-left: auto; }
.logs-time { font-variant-numeric: tabular-nums; }
.logs-diff { font-size: 13px; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.logs-old { color: #c62828; text-decoration: line-through; opacity: 0.75; max-width: 280px;
            overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.logs-new { color: #2e7d32; font-weight: 600; max-width: 280px;
            overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.logs-arrow { color: var(--muted); }
.logs-summary { font-size: 13px; color: var(--text); }
</style>
