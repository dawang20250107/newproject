<script setup>
import { ref, onMounted, onBeforeUnmount, reactive, computed } from 'vue'
import api from '../api/index.js'
import { useAuthStore } from '../stores/auth.js'
import { todayCST } from '../constants.js'
import { fmtMoney, fmtTime } from '../utils/format.js'
import { downloadBlob } from '../utils/download.js'
import StatusBadge from '../components/StatusBadge.vue'
import PaymentModal from '../components/PaymentModal.vue'
import EmptyState from '../components/EmptyState.vue'

const auth = useAuthStore()

// Column visibility from field-level view permissions.
const showPaid = computed(() => auth.canView('installments'))
const showRemaining = computed(() => auth.canView('total_amount') && showPaid.value)

// ── 列显示设置（自定义表格呈现，localStorage 持久化）─────────────────────────
// 权限隐藏的列不出现在设置面板里；用户勾掉的列存 pk_pay_hidden_cols。
const COL_DEFS = [
  { key: 'department',         label: '部门',     perm: () => auth.canView('department') },
  { key: 'secondary_dept',     label: '二级部门', perm: () => auth.canView('secondary_dept') },
  { key: 'project_short_name', label: '项目简称', perm: () => auth.canView('project_short_name') },
  { key: 'applicant',          label: '申请人',   perm: () => auth.canView('applicant') },
  { key: 'approval_number',    label: '审批单号', perm: () => auth.canView('approval_number') },
  { key: 'project_desc',       label: '付款事项', perm: () => auth.canView('project_desc') },
  { key: 'payee',              label: '收款方',   perm: () => auth.canView('payee') },
  { key: 'planned_date',       label: '计划日期', perm: () => auth.canView('planned_date') },
  { key: 'total_amount',       label: '计划额',   perm: () => auth.canView('total_amount') },
  { key: 'paid',               label: '已付',     perm: () => showPaid.value },
  { key: 'remaining',          label: '剩余',     perm: () => showRemaining.value },
  { key: 'status',             label: '状态',     perm: () => true },
  { key: 'overdue',            label: '逾期',     perm: () => true },
  { key: 'plan_adjustment',    label: '计划调整', perm: () => auth.canView('plan_adjustment') },
]
const hiddenCols = ref(new Set())
try { hiddenCols.value = new Set(JSON.parse(localStorage.getItem('pk_pay_hidden_cols') || '[]')) } catch {}
// 新增列默认隐藏过渡：历史用户首次见到二级部门/项目简称列即默认显示（不在隐藏集合则显示）
const showColSettings = ref(false)
function colVisible(key) {
  const def = COL_DEFS.find(c => c.key === key)
  if (!def || !def.perm()) return false
  return !hiddenCols.value.has(key)
}
function toggleCol(key) {
  const next = new Set(hiddenCols.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  hiddenCols.value = next
  localStorage.setItem('pk_pay_hidden_cols', JSON.stringify([...next]))
}
function resetCols() {
  hiddenCols.value = new Set()
  localStorage.removeItem('pk_pay_hidden_cols')
}
function dash(v) { return v === null || v === undefined ? '—' : fmt(v) }
const items = ref([])
const total = ref(0)
const outstandingTotal = ref('0')
const outstandingCount = ref(0)
const plannedTotal = ref('0')
const paidTotal = ref('0')
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

// ── date preset selector ──────────────────────────────────────────────────────
const datePreset = ref('')

function _d(y, m, d) {
  return `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`
}
function _addDays(ymd, n) {
  const [y, mo, d] = ymd.split('-').map(Number)
  const dt = new Date(y, mo - 1, d + n)
  return _d(dt.getFullYear(), dt.getMonth() + 1, dt.getDate())
}
function _monthEnd(y, m) { return new Date(y, m, 0).getDate() }  // m is 1-indexed

function dateRangeFor(key) {
  const [y, mo, d] = today.split('-').map(Number)
  const dow = new Date(y, mo - 1, d).getDay()          // 0=Sun
  const monday = _addDays(today, dow === 0 ? -6 : 1 - dow)
  const q = Math.floor((mo - 1) / 3)                   // 0-indexed quarter
  switch (key) {
    case 'today':        return [today, today]
    case 'this_week':    return [monday, _addDays(monday, 6)]
    case 'this_month':   return [_d(y, mo, 1), _d(y, mo, _monthEnd(y, mo))]
    case 'this_quarter': { const qs = q * 3 + 1; return [_d(y, qs, 1), _d(y, qs + 2, _monthEnd(y, qs + 2))] }
    case 'this_year':    return [_d(y, 1, 1), _d(y, 12, 31)]
    case 'last_week':    return [_addDays(monday, -7), _addDays(monday, -1)]
    case 'last_month':   { const lm = mo === 1 ? 12 : mo - 1, ly = mo === 1 ? y - 1 : y; return [_d(ly, lm, 1), _d(ly, lm, _monthEnd(ly, lm))] }
    case 'last_quarter': { const lq = q === 0 ? 3 : q - 1, ly = q === 0 ? y - 1 : y, lqs = lq * 3 + 1; return [_d(ly, lqs, 1), _d(ly, lqs + 2, _monthEnd(ly, lqs + 2))] }
    case 'last_year':    return [_d(y - 1, 1, 1), _d(y - 1, 12, 31)]
    case 'next_week':    return [_addDays(monday, 7), _addDays(monday, 13)]
    case 'next_month':   { const nm = mo === 12 ? 1 : mo + 1, ny = mo === 12 ? y + 1 : y; return [_d(ny, nm, 1), _d(ny, nm, _monthEnd(ny, nm))] }
    case 'next_quarter': { const nq = (q + 1) % 4, ny = q === 3 ? y + 1 : y, nqs = nq * 3 + 1; return [_d(ny, nqs, 1), _d(ny, nqs + 2, _monthEnd(ny, nqs + 2))] }
    case 'next_year':    return [_d(y + 1, 1, 1), _d(y + 1, 12, 31)]
    case 'last7':        return [_addDays(today, -6), today]
    case 'last30':       return [_addDays(today, -29), today]
    case 'last90':       return [_addDays(today, -89), today]
    default:             return ['', '']
  }
}

function applyDatePreset() {
  if (datePreset.value === '' || datePreset.value === 'custom') {
    if (datePreset.value === '') { filters.start_date = ''; filters.end_date = '' }
  } else {
    const [s, e] = dateRangeFor(datePreset.value)
    filters.start_date = s; filters.end_date = e
  }
  filters.page = 1; load()
}

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

// 精确数值：千分位、两位小数、不带单位（工作中确切金额更常用；KPI 卡片才用单位）
const fmt = (n) => fmtMoney(n, '0.00')

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
    plannedTotal.value = res.data.planned_total ?? '0'
    paidTotal.value = res.data.paid_total ?? '0'
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

// ── 预付核销（排款行内操作，支持多次）────────────────────────────────────────
// 该排款项目若有「预付」未核销余额，可直接在此冲抵：选预付 → 金额+日期 →
// 生成核销并自动更新本排款的预付冲抵额（待付 = 计划 − 已付 − 冲抵）。
const showOffset = ref(false)
const offsetTarget = ref(null)        // payment row
const offsetItems = ref([])           // 可用预付列表
const offsetLoading = ref(false)
const offsetForm = reactive({ advance_id: '', amount: '', writeoff_date: todayCST() })
const offsetBusy = ref(false)
const offsetDone = ref('')            // 成功提示（留在弹窗里可继续核销）

const offsetHistory = ref([])      // 本排款已有的核销（可反向删除）
async function fetchOffsetData(p) {
  const [bal, hist] = await Promise.allSettled([
    api.get('/payments/prepaid-balance', {
      params: { project_no: p.project_no || undefined, short_name: p.project_short_name || undefined,
                payee: p.payee || undefined },
    }),
    api.get(`/payments/${p.id}/offsets`),
  ])
  offsetItems.value = bal.status === 'fulfilled' ? (bal.value.data?.items || []) : []
  offsetHistory.value = hist.status === 'fulfilled' ? (hist.value.data?.items || []) : []
  if (offsetItems.value.length === 1 && !offsetForm.advance_id) offsetForm.advance_id = offsetItems.value[0].id
}
async function openOffset(p) {
  offsetTarget.value = p
  Object.assign(offsetForm, { advance_id: '', amount: '', writeoff_date: todayCST() })
  offsetItems.value = []
  offsetHistory.value = []
  offsetDone.value = ''
  showOffset.value = true
  offsetLoading.value = true
  try { await fetchOffsetData(p) } finally { offsetLoading.value = false }
}
async function reverseOffset(o) {
  if (!confirm(`反向核销：删除 ${o.writeoff_date} 冲抵的 ${o.amount} 元？\n预付余额将恢复，本排款待付相应回升。`)) return
  offsetBusy.value = true
  try {
    await api.delete(`/ar/advances/${o.advance_id}/writeoffs/${o.id}`)
    offsetDone.value = '✓ 已反向核销，预付余额已恢复'
    await load()
    const p = items.value.find(x => x.id === offsetTarget.value.id)
    if (p) offsetTarget.value = p
    await fetchOffsetData(offsetTarget.value)
  } catch (e) { alert(e?.msg || e?.error || '反向核销失败') }
  finally { offsetBusy.value = false }
}
const offsetRoom = computed(() => parseFloat(offsetTarget.value?.remaining) || 0)
async function doOffset() {
  const amt = parseFloat(offsetForm.amount)
  if (!offsetForm.advance_id) { alert('请选择要核销的预付'); return }
  if (!(amt > 0)) { alert('冲抵金额必须大于0'); return }
  offsetBusy.value = true
  try {
    await api.post(`/ar/advances/${offsetForm.advance_id}/writeoffs`, {
      amount: amt, writeoff_date: offsetForm.writeoff_date,
      payment_id: offsetTarget.value.id,
    })
    offsetDone.value = `✓ 已冲抵 ${amt.toFixed(2)} 元（可继续核销其他预付，或关闭）`
    offsetForm.amount = ''
    await load()
    const p = items.value.find(x => x.id === offsetTarget.value.id)
    if (p) offsetTarget.value = p
    await fetchOffsetData(offsetTarget.value)
  } catch (e) { alert(e?.msg || e?.error || '核销失败') }
  finally { offsetBusy.value = false }
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
  datePreset.value = ''
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
        <div class="col-settings-wrap">
          <button class="btn btn-ghost btn-sm" title="自定义表格显示哪些列"
                  @click="showColSettings = !showColSettings">⚙ 列设置</button>
          <div v-if="showColSettings" class="col-settings-pop" @mouseleave="showColSettings = false">
            <div class="csp-title">显示列<button class="csp-reset" @click="resetCols">恢复默认</button></div>
            <label v-for="c in COL_DEFS.filter(c => c.perm())" :key="c.key" class="csp-item">
              <input type="checkbox" :checked="!hiddenCols.has(c.key)" @change="toggleCol(c.key)" />{{ c.label }}
            </label>
          </div>
        </div>
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
        <select v-model="datePreset" @change="applyDatePreset" style="min-width:100px">
          <option value="">全部日期</option>
          <optgroup label="本期">
            <option value="today">今天</option>
            <option value="this_week">本周</option>
            <option value="this_month">本月</option>
            <option value="this_quarter">本季度</option>
            <option value="this_year">本年</option>
          </optgroup>
          <optgroup label="上期">
            <option value="last_week">上周</option>
            <option value="last_month">上月</option>
            <option value="last_quarter">上季度</option>
            <option value="last_year">上年</option>
          </optgroup>
          <optgroup label="下期">
            <option value="next_week">下周</option>
            <option value="next_month">下月</option>
            <option value="next_quarter">下季度</option>
            <option value="next_year">下年</option>
          </optgroup>
          <optgroup label="近期">
            <option value="last7">近 7 天</option>
            <option value="last30">近 30 天</option>
            <option value="last90">近 90 天</option>
          </optgroup>
          <option value="custom">自定义…</option>
        </select>
        <template v-if="datePreset === 'custom'">
          <input v-model="filters.start_date" type="date" style="min-width:120px" @change="search" />
          <span style="color:var(--muted);font-size:12px;flex-shrink:0">~</span>
          <input v-model="filters.end_date" type="date" style="min-width:120px" @change="search" />
        </template>
        <span v-else-if="datePreset && filters.start_date" class="date-range-hint">
          {{ filters.start_date }} ~ {{ filters.end_date }}
        </span>
        <button class="btn btn-ghost btn-sm" @click="search">筛选</button>
        <button class="btn btn-sm" style="background:var(--bg2);border:none" @click="resetFilters">重置</button>
      </div>

      <EmptyState v-if="loading" loading />
      <EmptyState v-else-if="loadErr" :error="loadErr" />
      <EmptyState v-else-if="!items.length" empty />

      <div v-else class="table-wrap pk-pay-tbl">
        <table>
          <thead>
            <tr>
              <th v-if="colVisible('department')" style="width:5%">部门</th>
              <th v-if="colVisible('secondary_dept')" style="width:5%">二级部门</th>
              <th v-if="colVisible('project_short_name')" style="width:6%">项目简称</th>
              <th v-if="colVisible('applicant')" style="width:4%">申请人</th>
              <th v-if="colVisible('approval_number')" style="width:8%">审批单号</th>
              <th v-if="colVisible('project_desc')">付款事项</th>
              <th v-if="colVisible('payee')" style="width:8%">收款方</th>
              <th v-if="colVisible('planned_date')" style="width:6%">计划日期</th>
              <th v-if="colVisible('total_amount')" style="width:8%">计划额</th>
              <th v-if="colVisible('paid')" style="width:7%">已付</th>
              <th v-if="colVisible('remaining')" style="width:6%">剩余</th>
              <th v-if="colVisible('status')" style="width:9%">状态</th>
              <th v-if="colVisible('overdue')" style="width:6%">逾期</th>
              <th v-if="colVisible('plan_adjustment')" style="width:6%">计划调整</th>
              <th v-if="auth.canWrite || auth.canDelete" style="width:12%">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="p in items" :key="p.id"
              :class="{ 'overdue-row': p.status !== 'settled' && p.planned_date && p.planned_date < today }">
              <td v-if="colVisible('department')">{{ p.department }}</td>
              <td v-if="colVisible('secondary_dept')" class="cell-clip">{{ p.secondary_dept || '—' }}</td>
              <td v-if="colVisible('project_short_name')" class="cell-clip" :title="p.project_short_name">{{ p.project_short_name || '—' }}</td>
              <td v-if="colVisible('applicant')">{{ p.applicant || '—' }}</td>
              <td v-if="colVisible('approval_number')">{{ p.approval_number || '—' }}</td>
              <td v-if="colVisible('project_desc')" class="cell-clip cell-desc"
                @mouseenter="showTip($event, p.project_desc)" @mousemove="moveTip" @mouseleave="hideTip">
                <span v-if="p.project_no" class="proj-no">{{ p.project_no }}</span>{{ p.project_desc }}
              </td>
              <td v-if="colVisible('payee')" class="cell-clip cell-payee"
                @mouseenter="showTip($event, p.payee)" @mousemove="moveTip" @mouseleave="hideTip">
                {{ p.payee }}
              </td>
              <td v-if="colVisible('planned_date')">{{ p.planned_date }}</td>
              <td v-if="colVisible('total_amount')" class="amt">{{ dash(p.total_amount) }}</td>
              <td v-if="colVisible('paid')" class="amt amt-green">{{ dash(p.total_paid) }}</td>
              <td v-if="colVisible('remaining')" class="amt" :class="parseFloat(p.remaining) > 0 ? 'amt-red' : ''">{{ dash(p.remaining) }}</td>
              <td v-if="colVisible('status')"><StatusBadge :status="p.status" /></td>
              <td v-if="colVisible('overdue')">
                <span v-if="p.status === 'settled'" class="overdue-tag overdue-ok">—</span>
                <span v-else-if="p.planned_date && p.planned_date < today"
                      class="overdue-tag overdue-bad">逾期 {{ daysOverdue(p.planned_date) }} 天</span>
                <span v-else-if="p.planned_date === today" class="overdue-tag overdue-today">今日到期</span>
                <span v-else class="overdue-tag overdue-ok">未到期</span>
              </td>
              <td v-if="colVisible('plan_adjustment')" class="amt">
                <span v-if="p.plan_adjustment != null" style="color:#1565c0;font-weight:600">
                  调整→{{ fmt(p.plan_adjustment) }}
                </span>
                <span v-else style="color:var(--muted)">—</span>
              </td>
              <td v-if="auth.canWrite || auth.canDelete" class="ops-cell">
                <div style="display:flex;gap:4px;justify-content:center">
                  <button v-if="auth.canWrite" class="btn btn-ghost btn-sm" @click="openEdit(p)">编辑</button>
                  <button v-if="auth.canWrite && (p.project_short_name || p.project_no)" class="btn btn-ghost btn-sm"
                    title="用该项目的预付余额冲抵本排款（支持多次核销）" @click="openOffset(p)">核销</button>
                  <button class="btn btn-ghost btn-sm" @click="openLogs(p)">日志</button>
                  <button v-if="auth.canDelete" class="btn btn-danger btn-sm" @click="onDelete(p)">删除</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 吸底合计 + 翻页：Teleport 到 body 以逃脱 .card transform 产生的 fixed 包含块 -->
      <Teleport to="body">
        <div v-if="!loading && items.length && !showModal" class="bottom-bar">
          <div class="bb-summary">
            <span class="bb-item"><i>合计</i><b>{{ total }}</b> 条</span>
            <span v-if="auth.canView('total_amount')" class="bb-item"><i>计划总额</i><b>{{ fmt(plannedTotal) }}</b></span>
            <span v-if="showPaid" class="bb-item ok"><i>已付</i><b>{{ fmt(paidTotal) }}</b></span>
            <span v-if="showRemaining" class="bb-item warn"><i>未结清</i><b>{{ fmt(outstandingTotal) }}</b>（{{ outstandingCount }} 笔）</span>
          </div>
          <div v-if="total > filters.size" class="bb-pager">
            <button :disabled="filters.page <= 1" class="page-btn" @click="setPage(filters.page - 1)">‹ 上一页</button>
            <span class="page-info">{{ filters.page }} / {{ Math.ceil(total / filters.size) || 1 }} 页 · 共 {{ total }} 条</span>
            <button :disabled="filters.page * filters.size >= total" class="page-btn" @click="setPage(filters.page + 1)">下一页 ›</button>
          </div>
        </div>
      </Teleport>
    </div>

    <PaymentModal
      v-if="showModal"
      :payment="editItem"
      :departments="departments"
      @saved="onSaved"
      @close="showModal = false"
    />

    <!-- 预付核销弹窗：用项目预付余额冲抵本排款（可多次） -->
    <div v-if="showOffset" class="overlay" @click.self="showOffset = false">
      <div class="modal" style="width:520px">
        <div class="modal-header">
          <h3>预付核销 — {{ offsetTarget?.project_short_name || offsetTarget?.project_no }}</h3>
          <button class="modal-close" @click="showOffset = false">×</button>
        </div>
        <div style="padding:4px 2px 0">
          <p style="font-size:12.5px;color:var(--muted);margin:0 0 10px">
            {{ offsetTarget?.project_desc }} · 收款方 {{ offsetTarget?.payee }}<br/>
            计划 <b>{{ fmt(offsetTarget?.plan_adjustment ?? offsetTarget?.total_amount) }}</b>
            · 已冲抵 <b>{{ fmt(offsetTarget?.prepaid_offset_amount || 0) }}</b>
            · 剩余待付 <b style="color:#e65100">{{ offsetRoom.toFixed(2) }}</b>
          </p>
          <p v-if="offsetDone" style="font-size:12.5px;color:#2e7d32;font-weight:600">{{ offsetDone }}</p>
          <!-- 已核销记录（可反向核销） -->
          <div v-if="offsetHistory.length" class="po-history">
            <div style="font-size:12px;font-weight:700;color:var(--text);margin-bottom:4px">已核销记录</div>
            <div v-for="o in offsetHistory" :key="o.id" class="po-hist-row">
              <span>{{ o.writeoff_date }} · {{ o.counterparty || '—' }}</span>
              <b>−{{ fmt(o.amount) }}</b>
              <button v-if="auth.canWrite" class="po-reverse" :disabled="offsetBusy"
                title="反向核销：预付余额恢复、待付回升" @click="reverseOffset(o)">撤销</button>
            </div>
          </div>
          <div v-if="offsetLoading" style="font-size:12.5px;color:var(--muted);padding:10px 0">查询可用预付…</div>
          <div v-else-if="!offsetItems.length" style="font-size:12.5px;color:var(--muted);padding:10px 0">
            该项目暂无可核销的「预付」余额——预付须先在「预收预付」录入并挂到该项目
          </div>
          <div v-else class="po-list">
            <label v-for="a in offsetItems" :key="a.id" class="po-opt" :class="{ on: offsetForm.advance_id === a.id }">
              <input type="radio" :value="a.id" v-model="offsetForm.advance_id" />
              <span>预付 {{ a.occur_date || '—' }} · {{ a.counterparty || '—' }}</span>
              <b>余额 {{ fmt(a.balance_amount) }}</b>
            </label>
          </div>
          <div style="display:flex;gap:8px;margin-top:10px">
            <input v-model="offsetForm.amount" type="number" step="0.01" placeholder="冲抵金额(元)" style="flex:1" />
            <input v-model="offsetForm.writeoff_date" type="date" style="width:150px" />
          </div>
          <p style="font-size:11px;color:var(--muted);margin:6px 0 0">
            冲抵后：待付 = 计划 − 已付 − 预付冲抵。每次核销逐笔可追溯，可多次核销不同预付。
          </p>
        </div>
        <div style="display:flex;justify-content:flex-end;gap:8px;margin-top:14px">
          <button class="btn btn-ghost" @click="showOffset = false">关闭</button>
          <button class="btn btn-primary" :disabled="offsetBusy || !offsetItems.length" @click="doOffset">
            {{ offsetBusy ? '核销中…' : '确认核销冲抵' }}
          </button>
        </div>
      </div>
    </div>

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
.date-range-hint {
  font-size: 11.5px; color: var(--muted); white-space: nowrap; flex-shrink: 0;
  padding: 4px 8px; background: rgba(201,99,66,0.06); border-radius: 7px;
  border: 1px solid rgba(201,99,66,0.18);
}

/* 付款台账：固定布局，不超出卡片宽度（table-layout:fixed 已防横向溢出，无需 overflow-x:hidden） */
.pk-pay-tbl table { table-layout: fixed; }
.pk-pay-tbl th, .pk-pay-tbl td { padding: 9px 7px; font-size: 12.5px; }
.pk-pay-tbl td:not(.ops-cell) { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 0; }
/* 操作列：不裁剪，按钮正常显示，更紧凑 */
.pk-pay-tbl .ops-cell { white-space: nowrap; text-align: center; }
.pk-pay-tbl .ops-cell .btn-sm { padding: 3px 7px; font-size: 11px; border-radius: 6px; }
.pk-pay-tbl .badge { font-size: 10.5px; padding: 2px 7px; }

/* 预付核销弹窗 */
.po-history { margin-bottom: 10px; padding: 8px 10px; border: 1px dashed var(--border); border-radius: 9px; }
.po-hist-row { display: flex; align-items: center; gap: 10px; font-size: 12.5px; padding: 3px 0; }
.po-hist-row b { color: #c62828; font-variant-numeric: tabular-nums; margin-left: auto; }
.po-reverse { border: 1px solid rgba(198,40,40,.4); color: #c62828; background: none; border-radius: 6px; padding: 1px 8px; font-size: 11px; cursor: pointer; }
.po-reverse:hover:not(:disabled) { background: rgba(198,40,40,.08); }
.po-list { display: flex; flex-direction: column; gap: 6px; max-height: 180px; overflow-y: auto; }
.po-opt { display: flex; align-items: center; gap: 8px; padding: 8px 10px; border: 1px solid var(--border); border-radius: 9px; cursor: pointer; font-size: 12.5px; }
.po-opt.on { border-color: var(--primary); background: rgba(201,99,66,0.06); }
.po-opt b { margin-left: auto; color: #2e7d32; font-variant-numeric: tabular-nums; }

/* .bottom-bar, .bb-*, .page-btn, .page-info → global styles in style.css */

/* Overdue column tag */
.overdue-tag {
  display: inline-block; font-size: 11.5px; padding: 2px 8px;
  border-radius: 9px; white-space: nowrap;
}
.overdue-ok    { color: var(--muted); background: transparent; }
.overdue-today { color: #b35309; background: rgba(245,127,23,0.12); font-weight: 600; }
.overdue-bad   { color: #c62828; background: rgba(198,40,40,0.10); font-weight: 700; }

/* truncated long cells + hover tooltip card */
.cell-clip { cursor: default; }
.proj-no { display: inline-block; margin-right: 6px; padding: 0 6px; border-radius: 5px; background: rgba(201,99,66,0.1); color: var(--primary); font-size: 11px; font-weight: 600; }
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

/* ── 列设置弹层 ───────────────────────────────────────────────────────────── */
.col-settings-wrap { position: relative; }
.col-settings-pop {
  position: absolute; right: 0; top: calc(100% + 6px); z-index: 120;
  width: 200px; padding: 10px 12px;
  background: rgba(255,252,248,0.97); backdrop-filter: blur(12px);
  border: 1px solid var(--border); border-radius: 12px;
  box-shadow: 0 12px 36px rgba(100,60,30,0.2);
}
.csp-title { display: flex; justify-content: space-between; align-items: center;
  font-size: 12px; font-weight: 700; color: var(--muted); margin-bottom: 6px; }
.csp-reset { border: none; background: none; font-size: 11px; color: var(--primary); cursor: pointer; }
.csp-item { display: flex; align-items: center; gap: 7px; font-size: 13px;
  padding: 3px 0; cursor: pointer; color: var(--text); }
.csp-item input { width: auto; }
</style>
