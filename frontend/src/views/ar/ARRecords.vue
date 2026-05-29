<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '../../stores/auth.js'
import { DEPARTMENTS, yearCST, monthCST, todayCST } from '../../constants.js'
import ar from '../../api/ar.js'

const route = useRoute()

const auth = useAuthStore()
const items = ref([])
const total = ref(0)
const kpiData = ref(null)
const loading = ref(false)
const page = ref(1)
const size = 50
const activeTab = ref('all')   // all | reconciliation | invoice | collection
const filters = reactive({
  dept: '', year: '', month: '', status: '',
  reconciliation_status: '', invoice_status: '', responsibility: '', q: '', project_id: '',
  due_start: '', due_end: '', manager: '', is_shared: '',
})

const showModal = ref(false)
const editRec = ref(null)
const saving = ref(false)
const recForm = reactive({
  project_id: '', operation_year: yearCST(), operation_month: monthCST(),
  estimated_amount: '', actual_invoice_amount: '', tax_amount: '',
  invoice_date: '', reconciliation_date: '', account_diff_adjustment: '', notes: '',
})

const projects = ref([])
const projectKeyword = ref('')
const projectSearching = ref(false)
let projectSearchTimer = null
// Server-side search by project_no / short_name / contract_name (debounced).
async function searchProjects(kw) {
  projectSearching.value = true
  try {
    const res = await ar.listProjects({ size: 100, q: kw || undefined })
    projects.value = res.data.items
  } finally { projectSearching.value = false }
}
function onProjectKeywordInput() {
  clearTimeout(projectSearchTimer)
  projectSearchTimer = setTimeout(() => searchProjects(projectKeyword.value.trim()), 220)
}
const showPayModal = ref(false)
const payRec = ref(null)
const payForm = reactive({ amount: '', payment_date: '', notes: '' })
const paySaving = ref(false)
const expandedPayments = ref({})
const importing = ref(false)
const exporting = ref(false)
const fileInput = ref(null)

const accessibleDepts = computed(() => auth.effectiveDepts.filter(d => DEPARTMENTS.includes(d)))
const years = Array.from({ length: 5 }, (_, i) => yearCST() - 2 + i)
const months = Array.from({ length: 12 }, (_, i) => i + 1)

// Field-permission column visibility
const show = k => auth.canArView(k)

const TABS = [
  { key: 'all', label: '全部明细' },
  { key: 'reconciliation', label: '对账跟踪' },
  { key: 'invoice', label: '开票跟踪' },
  { key: 'collection', label: '回款跟踪' },
  { key: 'payments', label: '回款流水' },
  { key: 'summary', label: '汇总' },
]
const DATA_TABS = ['all', 'reconciliation', 'invoice', 'collection']
const isDataTab = computed(() => DATA_TABS.includes(activeTab.value))
const summaryData = ref(null)

// ── Collapsible filter bar ──────────────────────────────────────────────────
const showMoreFilters = ref(false)
const FILTER_CHIP_LABELS = {
  month: v => `${v}月`,
  status: v => ({ overdue: '逾期', current: '当期', not_due: '未到期', settled: '已结清', outstanding: '未结清' }[v] || v),
  reconciliation_status: v => `对账:${v}`,
  invoice_status: v => `开票:${v}`,
  responsibility: v => `责任:${({ settled: '已结清', recon: '对账阶段', invoice: '待开票', post: '票后回款' }[v] || v)}`,
  is_shared: v => (v === '1' ? '共享' : '非共享'),
  manager: v => `负责人:${v}`,
  due_start: v => `到期≥${v}`,
  due_end: v => `到期≤${v}`,
}
const ADVANCED_FILTER_KEYS = ['month', 'due_start', 'due_end', 'status', 'reconciliation_status', 'invoice_status', 'responsibility', 'is_shared', 'manager']
const activeFilterChips = computed(() =>
  ADVANCED_FILTER_KEYS
    .filter(k => filters[k] !== '' && filters[k] != null)
    .map(k => ({ key: k, text: FILTER_CHIP_LABELS[k](filters[k]) })))
const hasAnyFilter = computed(() =>
  !!(filters.dept || filters.year || filters.q) || activeFilterChips.value.length > 0)
function removeFilter(key) { filters[key] = ''; onFilterChange() }

// ── 回款流水 (payment ledger) ───────────────────────────────────────────────
const payFilters = reactive({ pay_start: '', pay_end: '', dept: '', q: '' })
const payItems = ref([])
const paySummary = ref(null)
const payTotal = ref(0)
const payPage = ref(1)
const payLoading = ref(false)
const payExporting = ref(false)

// ── 多维汇总 (group-by pivot) ────────────────────────────────────────────────
const GROUP_DIMS = [
  { key: 'dept', label: '交付部门' },
  { key: 'invoice_status', label: '开票状态' },
  { key: 'customer_level', label: '客户等级' },
  { key: 'business_mode', label: '业务模式' },
  { key: 'month', label: '运作年月' },
  { key: 'manager', label: '项目负责人' },
]
const DRILLABLE_DIMS = ['dept', 'invoice_status', 'month', 'manager']
const summaryGroupBy = ref('dept')
const groupRows = ref([])
const groupLoading = ref(false)

function fmtAmt(v) {
  const n = parseFloat(v) || 0
  if (Math.abs(n) >= 1e8) return (n / 1e8).toFixed(2) + '亿'
  if (Math.abs(n) >= 1e4) return (n / 1e4).toFixed(2) + '万'
  return n.toFixed(2)
}

async function load(reset = false) {
  if (reset) page.value = 1
  loading.value = true
  try {
    const [recs, kpi] = await Promise.all([
      ar.listRecords({ ...filters, include_payments: 1, page: page.value, size }),
      ar.recordsKpi(filters),
    ])
    items.value = recs.data.items
    total.value = recs.data.total
    summaryData.value = recs.data.summary
    kpiData.value = kpi.data
  } finally { loading.value = false }
}

async function loadPayments(reset = false) {
  if (reset) payPage.value = 1
  payLoading.value = true
  try {
    const res = await ar.listPaymentLedger({ ...payFilters, page: payPage.value, size })
    payItems.value = res.data.items
    payTotal.value = res.data.total
    paySummary.value = res.data.summary
  } finally { payLoading.value = false }
}

async function exportPayments() {
  payExporting.value = true
  try {
    const res = await ar.exportPaymentLedger(payFilters)
    const url = URL.createObjectURL(res)
    const a = document.createElement('a'); a.href = url; a.download = '回款流水.xlsx'; a.click()
    URL.revokeObjectURL(url)
  } catch (e) { alert(e?.response?.data?.msg || '导出失败')
  } finally { payExporting.value = false }
}

async function loadGroupSummary() {
  groupLoading.value = true
  try {
    const res = await ar.recordsSummary({ ...filters, group_by: summaryGroupBy.value })
    groupRows.value = res.data.rows
  } finally { groupLoading.value = false }
}

const groupTotals = computed(() => {
  const acc = { count: 0, estimated: 0, invoiced: 0, outstanding: 0, collected: 0 }
  for (const r of groupRows.value) {
    acc.count += r.count
    acc.estimated += parseFloat(r.estimated) || 0
    acc.invoiced += parseFloat(r.invoiced) || 0
    acc.outstanding += parseFloat(r.outstanding) || 0
    acc.collected += parseFloat(r.collected) || 0
  }
  return acc
})

// Switch tab + lazily load the data backing that tab.
function switchTab(key) {
  const prev = activeTab.value
  if (key === prev) return
  activeTab.value = key
  if (key === 'payments') loadPayments(true)
  else if (key === 'summary') loadGroupSummary()
  else if (!DATA_TABS.includes(prev)) load()  // returning from a non-data tab
}

// Shared-filter change → refresh whichever tab consumes those filters.
function onFilterChange() {
  if (activeTab.value === 'summary') loadGroupSummary()
  else load(true)
}

function drillIntoGroup(row) {
  if (!DRILLABLE_DIMS.includes(summaryGroupBy.value)) return
  const gb = summaryGroupBy.value
  if (gb === 'dept') filters.dept = row.key
  else if (gb === 'invoice_status') filters.invoice_status = row.key
  else if (gb === 'month') { filters.year = row.year; filters.month = row.month }
  else if (gb === 'manager') filters.manager = row.key
  switchTab('all')
  load(true)
}

function openCreate() {
  editRec.value = null
  Object.assign(recForm, {
    project_id: '',
    operation_year: yearCST(), operation_month: monthCST(),
    estimated_amount: '', actual_invoice_amount: '', tax_amount: '',
    invoice_date: '', reconciliation_date: '', account_diff_adjustment: '', notes: '',
  })
  showModal.value = true
  projectKeyword.value = ''
  searchProjects('')  // initial page of projects
}

function openEdit(rec) {
  editRec.value = rec
  Object.assign(recForm, {
    project_id: rec.project_id, operation_year: rec.operation_year, operation_month: rec.operation_month,
    estimated_amount: rec.estimated_amount, actual_invoice_amount: rec.actual_invoice_amount || '',
    tax_amount: rec.tax_amount || '', invoice_date: rec.invoice_date || '',
    reconciliation_date: rec.reconciliation_date || '',
    account_diff_adjustment: rec.account_diff_adjustment || '',
    notes: rec.notes,
  })
  showModal.value = true
}

async function saveRec() {
  if (!recForm.project_id) { alert('请选择项目'); return }
  saving.value = true
  try {
    const payload = {
      project_id: recForm.project_id, operation_year: recForm.operation_year,
      operation_month: recForm.operation_month, estimated_amount: recForm.estimated_amount || 0,
      actual_invoice_amount: recForm.actual_invoice_amount || null,
      tax_amount: recForm.tax_amount || null, invoice_date: recForm.invoice_date || null,
      reconciliation_date: recForm.reconciliation_date || null, account_diff_adjustment: recForm.account_diff_adjustment || 0, notes: recForm.notes,
    }
    if (editRec.value) await ar.updateRecord(editRec.value.id, payload)
    else await ar.createRecord(payload)
    showModal.value = false; await load()
  } catch (e) { alert(e?.response?.data?.msg || '保存失败')
  } finally { saving.value = false }
}

async function deleteRec(rec) {
  const amt = parseFloat(rec.estimated_amount || 0).toFixed(2)
  if (!confirm(`确定删除「${rec.short_name || rec.contract_name}」${rec.operation_year}年${rec.operation_month}月的应收记录（${amt} 元）？同月可能存在多条记录，请确认。`)) return
  try { await ar.deleteRecord(rec.id); await load() }
  catch (e) { alert(e?.response?.data?.msg || '删除失败') }
}

function togglePayments(id) { expandedPayments.value[id] = !expandedPayments.value[id] }

function openAddPayment(rec) {
  payRec.value = rec
  Object.assign(payForm, { amount: '', payment_date: todayCST(), notes: '' })
  showPayModal.value = true
}

async function savePayment() {
  if (!payForm.amount || !payForm.payment_date) { alert('金额和日期必填'); return }
  paySaving.value = true
  try {
    await ar.addPayment(payRec.value.id, payForm)
    showPayModal.value = false; await load()
  } catch (e) { alert(e?.response?.data?.msg || '保存失败')
  } finally { paySaving.value = false }
}

async function deletePayment(rec, pay) {
  if (!confirm(`确定删除第${pay.payment_no}次回款 ${pay.amount} 元？`)) return
  try { await ar.deletePayment(rec.id, pay.id); await load() }
  catch (e) { alert(e?.response?.data?.msg || '删除失败') }
}

async function downloadTemplate() {
  const res = await ar.recordTemplate()
  const url = URL.createObjectURL(res)
  const a = document.createElement('a'); a.href = url; a.download = '应收账款明细导入模板.xlsx'; a.click()
  URL.revokeObjectURL(url)
}

async function handleImport(e) {
  const f = e.target.files?.[0]; if (!f) return
  importing.value = true
  try {
    const fd = new FormData(); fd.append('file', f)
    const res = await ar.importRecords(fd); const d = res.data
    let msg = `导入完成：创建 ${d.created}，更新 ${d.updated}，跳过 ${d.skipped}`
    if (d.tip) msg += `\n${d.tip}`
    alert(msg)
    await load()
  } catch (e) { alert(e?.response?.data?.msg || '导入失败')
  } finally { importing.value = false; if (fileInput.value) fileInput.value.value = '' }
}

async function exportData() {
  exporting.value = true
  try {
    const res = await ar.exportRecords(filters)
    const url = URL.createObjectURL(res)
    const a = document.createElement('a'); a.href = url; a.download = '应收账款明细.xlsx'; a.click()
    URL.revokeObjectURL(url)
  } catch (e) { alert(e?.response?.data?.msg || '导出失败')
  } finally { exporting.value = false }
}

const onScopeChange = () => {
  if (filters.dept && !accessibleDepts.value.includes(filters.dept)) filters.dept = ''
  if (payFilters.dept && !accessibleDepts.value.includes(payFilters.dept)) payFilters.dept = ''
  if (activeTab.value === 'payments') loadPayments(true)
  else if (activeTab.value === 'summary') loadGroupSummary()
  else load(true)
}
onMounted(() => {
  // Pick up query params from router navigation (e.g., from Cashflow or Analytics)
  if (route.query.status) filters.status = route.query.status
  if (route.query.project_id) filters.project_id = route.query.project_id
  if (route.query.dept) filters.dept = route.query.dept
  load()
  window.addEventListener('pk:depts-changed', onScopeChange)
})
onBeforeUnmount(() => window.removeEventListener('pk:depts-changed', onScopeChange))
function clearFilters() {
  Object.assign(filters, { dept: '', year: '', month: '', status: '', reconciliation_status: '', invoice_status: '', responsibility: '', q: '', project_id: '', due_start: '', due_end: '', manager: '', is_shared: '' })
  onFilterChange()
}
</script>

<template>
  <div>
    <div class="topbar">
      <div class="topbar-left">
        <h1>应收明细</h1>
        <div class="segment-ctrl">
          <button v-for="t in TABS" :key="t.key"
            :class="['seg-btn', activeTab === t.key ? 'active' : '']" @click="switchTab(t.key)">
            <span class="seg-dot"></span>{{ t.label }}
          </button>
        </div>
      </div>
      <div class="ctrl-row">
        <button class="act-btn" @click="downloadTemplate">↓ 模板</button>
        <label class="act-btn" style="cursor:pointer">
          {{ importing ? '导入中…' : '↑ 导入' }}
          <input ref="fileInput" type="file" accept=".xlsx,.xls" style="display:none" @change="handleImport" />
        </label>
        <button class="act-btn" :disabled="exporting" @click="exportData">↓ 导出</button>
        <button v-if="auth.canCreate" class="btn btn-primary btn-sm" @click="openCreate">+ 新增应收</button>
      </div>
    </div>

    <!-- Filter bar (compact + collapsible; 回款流水 has its own filters) -->
    <div v-if="activeTab !== 'payments'" class="filter-bar">
      <div class="filter-main">
        <select v-model="filters.dept" class="sel-bu" @change="onFilterChange">
          <option value="">全部事业部</option>
          <option v-for="d in accessibleDepts" :key="d" :value="d">{{ d }}</option>
        </select>
        <select v-model="filters.year" class="sel-yr" @change="onFilterChange">
          <option value="">全部年份</option>
          <option v-for="y in years" :key="y" :value="y">{{ y }}年</option>
        </select>
        <input v-model="filters.q" placeholder="搜索项目" class="search-input" @input="onFilterChange" />
        <button class="filter-toggle" :class="{ active: showMoreFilters }" @click="showMoreFilters = !showMoreFilters">
          更多筛选<span v-if="activeFilterChips.length" class="ft-badge">{{ activeFilterChips.length }}</span>
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" :style="showMoreFilters ? 'transform:rotate(180deg)' : ''"><path d="M6 9l6 6 6-6"/></svg>
        </button>
        <!-- active advanced-filter chips (shown when collapsed) -->
        <template v-if="!showMoreFilters">
          <span v-for="c in activeFilterChips" :key="c.key" class="filter-chip">
            {{ c.text }}
            <button @click="removeFilter(c.key)" title="移除">✕</button>
          </span>
        </template>
        <button v-if="hasAnyFilter" class="clear-mini" @click="clearFilters">清空</button>
      </div>

      <!-- expanded advanced filters -->
      <div v-if="showMoreFilters" class="filter-more">
        <select v-model="filters.month" class="sel-mo" @change="onFilterChange">
          <option value="">全月</option>
          <option v-for="m in months" :key="m" :value="m">{{ m }}月</option>
        </select>
        <input v-model="filters.due_start" type="date" class="sel-mo" @change="onFilterChange" />
        <input v-model="filters.due_end" type="date" class="sel-mo" @change="onFilterChange" />
        <select v-model="filters.status" class="sel-mo" @change="onFilterChange">
          <option value="">全部状态</option>
          <option value="overdue">逾期</option>
          <option value="current">当期</option>
          <option value="not_due">未到期</option>
          <option value="settled">已结清</option>
        </select>
        <select v-model="filters.reconciliation_status" class="sel-mo" @change="onFilterChange">
          <option value="">对账(全部)</option>
          <option value="已对账">已对账</option>
          <option value="未对账">未对账</option>
        </select>
        <select v-model="filters.invoice_status" class="sel-mo" @change="onFilterChange">
          <option value="">开票(全部)</option>
          <option value="未开票">未开票</option>
          <option value="已开票">已开票</option>
          <option value="已结清">已结清</option>
        </select>
        <select v-model="filters.responsibility" class="sel-mo" @change="onFilterChange" title="按责任归属阶段筛选">
          <option value="">责任(全部)</option>
          <option value="recon">对账阶段</option>
          <option value="invoice">待开票</option>
          <option value="post">票后回款</option>
          <option value="settled">已结清</option>
        </select>
        <select v-model="filters.is_shared" class="sel-mo" @change="onFilterChange">
          <option value="">共享(全部)</option>
          <option value="1">共享</option>
          <option value="0">非共享</option>
        </select>
        <input v-model="filters.manager" placeholder="负责人" class="search-input" @input="onFilterChange" />
        <button class="act-btn" @click="Object.assign(filters, { status: 'outstanding' }); onFilterChange()">未结清</button>
      </div>
    </div>

    <!-- Tab + table card -->
    <div class="card" :class="{ 'data-reloading': loading && items.length }">
      <!-- 合并指标条：左侧=本Tab进度/重点；右侧=当前筛选全集合计 -->
      <div v-if="isDataTab && (kpiData || summaryData)" class="metrics-bar">
        <template v-if="kpiData">
          <template v-if="activeTab === 'all'">
            <div class="kpi-item danger"><span class="kpi-k">逾期</span><span class="kpi-v">{{ kpiData.overdue.count }} 笔 / {{ fmtAmt(kpiData.overdue.amount) }}</span></div>
          </template>
          <template v-else-if="activeTab === 'reconciliation'">
            <div class="kpi-progress">
              <div class="kpi-k">对账完成度</div>
              <div class="kpi-track"><div class="kpi-fill fill-blue" :style="`width:${kpiData.reconciliation.rate}%`"></div></div>
              <div class="kpi-pct">{{ kpiData.reconciliation.rate }}%</div>
            </div>
            <div class="kpi-item warn"><span class="kpi-k">待对账</span><span class="kpi-v">{{ kpiData.reconciliation.pending }} 笔 / {{ fmtAmt(kpiData.reconciliation.pending_amount) }}</span></div>
          </template>
          <template v-else-if="activeTab === 'invoice'">
            <div class="kpi-progress">
              <div class="kpi-k">开票完成度</div>
              <div class="kpi-track"><div class="kpi-fill fill-amber" :style="`width:${kpiData.invoice.rate}%`"></div></div>
              <div class="kpi-pct">{{ kpiData.invoice.rate }}%</div>
            </div>
            <div class="kpi-item warn"><span class="kpi-k">待开票</span><span class="kpi-v">{{ kpiData.invoice.pending }} 笔 / {{ fmtAmt(kpiData.invoice.pending_amount) }}</span></div>
          </template>
          <template v-else>
            <div class="kpi-progress">
              <div class="kpi-k">回款结清率</div>
              <div class="kpi-track"><div class="kpi-fill fill-green" :style="`width:${kpiData.collection.rate}%`"></div></div>
              <div class="kpi-pct">{{ kpiData.collection.rate }}%</div>
            </div>
            <div class="kpi-item ok"><span class="kpi-k">已收</span><span class="kpi-v">{{ fmtAmt(kpiData.collection.collected_amount) }}</span></div>
            <div class="kpi-item danger"><span class="kpi-k">其中逾期</span><span class="kpi-v">{{ kpiData.overdue.count }} 笔</span></div>
          </template>
        </template>

        <span v-if="kpiData && summaryData" class="metrics-div"></span>

        <!-- 筛选全集合计（不止当前页） -->
        <template v-if="summaryData">
          <span class="sum-section-lbl" :title="`以下为全部 ${summaryData.count} 条筛选记录的汇总（跨所有分页）`">全集合计</span>
          <div class="kpi-item"><span class="kpi-k">记录</span><span class="kpi-v">{{ summaryData.count }} 条</span></div>
          <div class="kpi-item"><span class="kpi-k">预估</span><span class="kpi-v">{{ fmtAmt(summaryData.estimated) }}</span></div>
          <div class="kpi-item"><span class="kpi-k">开票</span><span class="kpi-v">{{ fmtAmt(summaryData.invoiced) }}</span></div>
          <div class="kpi-item"><span class="kpi-k">税额</span><span class="kpi-v">{{ fmtAmt(summaryData.tax) }}</span></div>
          <div class="kpi-item warn"><span class="kpi-k">未收合计</span><span class="kpi-v">{{ fmtAmt(summaryData.outstanding) }}</span></div>
        </template>
      </div>

      <!-- ══ 数据明细表（全部/对账/开票/回款 跟踪）══ -->
      <div v-if="isDataTab" class="table-wrap" style="margin-top:12px">
        <table class="rec-table">
          <thead>
            <tr>
              <th>项目</th>
              <th class="ctr">年月</th>

              <!-- all -->
              <template v-if="activeTab === 'all'">
                <th v-if="show('r_estimated_amount')" class="amt">预估金额</th>
                <th v-if="show('r_actual_invoice_amount')" class="amt">实际开票</th>
                <th v-if="show('r_tax_amount')" class="amt">税额</th>
                <th v-if="show('r_account_diff')" class="amt">账实差额</th>
                <th v-if="show('r_outstanding')" class="amt">未收金额</th>
                <th v-if="show('r_due_date')" class="ctr">应收到期</th>
                <th v-if="show('r_reconciliation')" class="ctr">对账</th>
                <th v-if="show('r_payments')" class="ctr">回款</th>
                <th class="ctr">状态</th>
                <th class="ctr">责任状态</th>
                <th v-if="show('r_notes')" class="notes-col">备注</th>
              </template>
              <!-- reconciliation -->
              <template v-else-if="activeTab === 'reconciliation'">
                <th v-if="show('r_estimated_amount')" class="amt">预估金额</th>
                <th v-if="show('r_reconciliation')" class="ctr">对账状态</th>
                <th v-if="show('r_reconciliation')" class="ctr">对账日期</th>
                <th v-if="show('r_due_date')" class="ctr">应收到期</th>
                <th class="ctr">状态</th>
                <th v-if="show('r_outstanding')" class="amt">未收金额</th>
              </template>
              <!-- invoice -->
              <template v-else-if="activeTab === 'invoice'">
                <th v-if="show('r_estimated_amount')" class="amt">预估金额</th>
                <th v-if="show('r_actual_invoice_amount')" class="amt">实际开票额</th>
                <th v-if="show('r_tax_amount')" class="amt">税额</th>
                <th v-if="show('r_invoice_date')" class="ctr">开票日期</th>
                <th v-if="show('r_account_diff')" class="amt">账实差额</th>
                <th v-if="show('r_invoice_status')" class="ctr">开票状态</th>
              </template>
              <!-- collection -->
              <template v-else>
                <th class="amt">应收基础</th>
                <th v-if="show('r_payments')">回款记录</th>
                <th v-if="show('r_outstanding')" class="amt">未收金额</th>
                <th v-if="show('r_invoice_status')" class="ctr">回款状态</th>
              </template>

              <th class="ctr">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="loading && !items.length">
              <td colspan="12" class="empty-cell">⏳ 加载中…</td>
            </tr>
            <tr v-else-if="!items.length">
              <td colspan="12" class="empty-cell">暂无数据</td>
            </tr>
            <template v-for="rec in items" :key="rec.id">
              <tr :class="['data-row', rec.is_overdue ? 'row-overdue' : '']">
                <td>
                  <div class="proj-name">{{ rec.short_name || rec.contract_name }}</div>
                  <div v-if="rec.short_name && rec.short_name !== rec.contract_name" class="proj-sub">{{ rec.contract_name }}</div>
                  <div class="proj-no">{{ rec.project_no }}</div>
                </td>
                <td class="ctr">
                  <span class="ym-chip">{{ rec.operation_year }}/{{ String(rec.operation_month).padStart(2,'0') }}</span>
                </td>

                <!-- all -->
                <template v-if="activeTab === 'all'">
                  <td v-if="show('r_estimated_amount')" class="amt fw">{{ fmtAmt(rec.estimated_amount) }}</td>
                  <td v-if="show('r_actual_invoice_amount')" class="amt">{{ rec.actual_invoice_amount ? fmtAmt(rec.actual_invoice_amount) : '—' }}</td>
                  <td v-if="show('r_tax_amount')" class="amt text-muted">{{ rec.tax_amount ? fmtAmt(rec.tax_amount) : '—' }}</td>
                  <td v-if="show('r_account_diff')" class="amt">{{ parseFloat(rec.account_diff_adjustment) !== 0 ? fmtAmt(rec.account_diff_adjustment) : '—' }}</td>
                  <td v-if="show('r_outstanding')" class="amt" :class="parseFloat(rec.outstanding_amount) > 0 ? 'amt-warn' : 'amt-zero'">{{ parseFloat(rec.outstanding_amount) > 0 ? fmtAmt(rec.outstanding_amount) : '—' }}</td>
                  <td v-if="show('r_due_date')" class="ctr text-sm-muted">{{ rec.due_date || '—' }}</td>
                  <td v-if="show('r_reconciliation')" class="ctr">
                    <span :class="['status-pill', rec.reconciliation_status === '已对账' ? 'pill-ok' : 'pill-warn']">{{ rec.reconciliation_status }}</span>
                  </td>
                  <td v-if="show('r_payments')" class="ctr">
                    <span class="pay-count" :class="rec.payments?.length ? 'count-has' : 'count-none'">{{ rec.payments?.length || 0 }}</span>
                  </td>
                  <td class="ctr">
                    <span v-if="rec.is_overdue" class="status-pill pill-danger">逾期{{ rec.overdue_days }}天</span>
                    <span v-else-if="rec.is_current" class="status-pill pill-blue">当期</span>
                    <span v-else-if="rec.invoice_status === '已结清'" class="status-pill pill-ok">已结清</span>
                    <span v-else class="status-pill pill-muted">未到期</span>
                  </td>
                  <td class="ctr">
                    <span v-if="rec.post_invoice_status" :class="['status-pill', `pill-${rec.post_invoice_status.style}`]">{{ rec.post_invoice_status.label }}</span>
                    <span v-else class="status-pill pill-muted">—</span>
                  </td>
                  <td v-if="show('r_notes')" class="notes-col text-sm-muted" :title="rec.notes">{{ rec.notes || '—' }}</td>
                </template>

                <!-- reconciliation -->
                <template v-else-if="activeTab === 'reconciliation'">
                  <td v-if="show('r_estimated_amount')" class="amt fw">{{ fmtAmt(rec.estimated_amount) }}</td>
                  <td v-if="show('r_reconciliation')" class="ctr">
                    <span :class="['status-pill', rec.reconciliation_status === '已对账' ? 'pill-ok' : 'pill-warn']">{{ rec.reconciliation_status }}</span>
                  </td>
                  <td v-if="show('r_reconciliation')" class="ctr text-sm-muted">{{ rec.reconciliation_date || '—' }}</td>
                  <td v-if="show('r_due_date')" class="ctr text-sm-muted">{{ rec.due_date || '—' }}</td>
                  <td class="ctr">
                    <span v-if="rec.is_overdue" class="status-pill pill-danger">逾期{{ rec.overdue_days }}天</span>
                    <span v-else-if="rec.is_current" class="status-pill pill-blue">当期</span>
                    <span v-else-if="rec.invoice_status === '已结清'" class="status-pill pill-ok">已结清</span>
                    <span v-else class="status-pill pill-muted">未到期</span>
                  </td>
                  <td v-if="show('r_outstanding')" class="amt" :class="parseFloat(rec.outstanding_amount) > 0 ? 'amt-warn' : 'amt-zero'">{{ parseFloat(rec.outstanding_amount) > 0 ? fmtAmt(rec.outstanding_amount) : '—' }}</td>
                </template>

                <!-- invoice -->
                <template v-else-if="activeTab === 'invoice'">
                  <td v-if="show('r_estimated_amount')" class="amt text-muted">{{ fmtAmt(rec.estimated_amount) }}</td>
                  <td v-if="show('r_actual_invoice_amount')" class="amt fw">{{ rec.actual_invoice_amount ? fmtAmt(rec.actual_invoice_amount) : '—' }}</td>
                  <td v-if="show('r_tax_amount')" class="amt text-muted">{{ rec.tax_amount ? fmtAmt(rec.tax_amount) : '—' }}</td>
                  <td v-if="show('r_invoice_date')" class="ctr text-sm-muted">{{ rec.invoice_date || '—' }}</td>
                  <td v-if="show('r_account_diff')" class="amt">{{ parseFloat(rec.account_diff_adjustment) !== 0 ? fmtAmt(rec.account_diff_adjustment) : '—' }}</td>
                  <td v-if="show('r_invoice_status')" class="ctr">
                    <span :class="['status-pill', rec.invoice_status === '已结清' ? 'pill-ok' : rec.invoice_status === '部分回款' ? 'pill-blue' : rec.invoice_status === '已开票' ? 'pill-warn' : 'pill-muted']">{{ rec.invoice_status }}</span>
                  </td>
                </template>

                <!-- collection -->
                <template v-else>
                  <td class="amt fw">{{ fmtAmt(rec.actual_invoice_amount || rec.estimated_amount) }}</td>
                  <td v-if="show('r_payments')">
                    <button class="pay-toggle" @click="togglePayments(rec.id)">
                      <span class="pay-count" :class="rec.payments?.length ? 'count-has' : 'count-none'">{{ rec.payments?.length || 0 }}</span>
                      <span style="font-size:12px;color:var(--muted)">{{ rec.payments?.length ? '笔回款' : '无回款' }}</span>
                      <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" style="margin-left:3px;color:var(--muted)" :style="expandedPayments[rec.id] ? 'transform:rotate(180deg)' : ''"><path d="M6 9l6 6 6-6"/></svg>
                    </button>
                    <button v-if="auth.canCreate" class="add-pay-btn" @click="openAddPayment(rec)">+ 回款</button>
                  </td>
                  <td v-if="show('r_outstanding')" class="amt" :class="parseFloat(rec.outstanding_amount) > 0 ? 'amt-warn' : 'amt-zero'">{{ parseFloat(rec.outstanding_amount) > 0 ? fmtAmt(rec.outstanding_amount) : '—' }}</td>
                  <td v-if="show('r_invoice_status')" class="ctr">
                    <span :class="['status-pill', rec.invoice_status === '已结清' ? 'pill-ok' : rec.invoice_status === '部分回款' ? 'pill-blue' : rec.invoice_status === '已开票' ? 'pill-warn' : 'pill-muted']">{{ rec.invoice_status }}</span>
                  </td>
                </template>

                <td class="ctr">
                  <div class="row-acts">
                    <button class="icon-btn" @click="openEdit(rec)" title="编辑">
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4z"/></svg>
                    </button>
                    <button v-if="auth.canDelete" class="icon-btn icon-btn-del" @click="deleteRec(rec)" title="删除">
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/></svg>
                    </button>
                  </div>
                </td>
              </tr>

              <!-- Payment detail rows (collection tab) -->
              <template v-if="activeTab === 'collection' && show('r_payments') && expandedPayments[rec.id]">
                <tr v-if="!rec.payments?.length" class="pay-row">
                  <td :colspan="99" class="pay-empty">暂无回款记录</td>
                </tr>
                <tr v-else v-for="pay in rec.payments" :key="pay.id" class="pay-row">
                  <td :colspan="99">
                    <div class="pay-detail">
                      <span class="pay-no">第{{ pay.payment_no }}次</span>
                      <span class="pay-amt">{{ fmtAmt(pay.amount) }}</span>
                      <span class="pay-date">{{ pay.payment_date }}</span>
                      <span v-if="pay.notes" class="pay-notes">{{ pay.notes }}</span>
                      <button v-if="auth.canDelete" class="pay-del" @click="deletePayment(rec, pay)">删除</button>
                    </div>
                  </td>
                </tr>
              </template>
            </template>
          </tbody>
        </table>
      </div>

      <div v-if="isDataTab && total > size" class="pagination">
        <button :disabled="page <= 1" class="page-btn" @click="page--; load()">‹ 上一页</button>
        <span class="page-info">{{ page }} / {{ Math.ceil(total / size) }} 页 · 共 {{ total }} 条</span>
        <button :disabled="page * size >= total" class="page-btn" @click="page++; load()">下一页 ›</button>
      </div>

      <!-- ══ 回款流水 ══ -->
      <div v-if="activeTab === 'payments'">
        <div class="filter-strip" style="margin-top:4px">
          <label class="pay-range-lbl">回款日期</label>
          <input v-model="payFilters.pay_start" type="date" class="sel-mo" @change="loadPayments(true)" />
          <span style="color:var(--muted)">~</span>
          <input v-model="payFilters.pay_end" type="date" class="sel-mo" @change="loadPayments(true)" />
          <select v-model="payFilters.dept" class="sel-bu" @change="loadPayments(true)">
            <option value="">全部事业部</option>
            <option v-for="d in accessibleDepts" :key="d" :value="d">{{ d }}</option>
          </select>
          <input v-model="payFilters.q" placeholder="搜索项目" class="search-input" @input="loadPayments(true)" />
          <button class="act-btn" :disabled="payExporting" @click="exportPayments">↓ 导出</button>
        </div>

        <div v-if="paySummary" class="totals-strip">
          <span class="tot-label">区间合计</span>
          <span class="tot-item"><i>笔数</i>{{ paySummary.count }}</span>
          <span class="tot-item tot-green"><i>回款总额</i>{{ fmtAmt(paySummary.total_amount) }}</span>
        </div>

        <div class="table-wrap" style="margin-top:12px">
          <table class="rec-table">
            <thead>
              <tr>
                <th class="ctr">回款日期</th>
                <th class="amt">回款金额</th>
                <th>项目</th>
                <th class="ctr">交付部门</th>
                <th class="ctr">运作年月</th>
                <th class="ctr">序号</th>
                <th>备注</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="payLoading && !payItems.length"><td colspan="7" class="empty-cell">⏳ 加载中…</td></tr>
              <tr v-else-if="!payItems.length"><td colspan="7" class="empty-cell">暂无回款记录</td></tr>
              <tr v-for="p in payItems" :key="p.id" class="data-row">
                <td class="ctr text-sm-muted">{{ p.payment_date }}</td>
                <td class="amt fw" style="color:#2e7d32">{{ fmtAmt(p.amount) }}</td>
                <td>
                  <div class="proj-name">{{ p.short_name || '—' }}</div>
                  <div class="proj-no">{{ p.project_no }}</div>
                </td>
                <td class="ctr text-sm-muted">{{ p.delivery_dept }}</td>
                <td class="ctr"><span class="ym-chip">{{ p.operation_year }}/{{ String(p.operation_month).padStart(2,'0') }}</span></td>
                <td class="ctr text-sm-muted">第{{ p.payment_no }}次</td>
                <td class="text-sm-muted">{{ p.notes || '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div v-if="payTotal > size" class="pagination">
          <button :disabled="payPage <= 1" class="page-btn" @click="payPage--; loadPayments()">‹ 上一页</button>
          <span class="page-info">{{ payPage }} / {{ Math.ceil(payTotal / size) }} 页 · 共 {{ payTotal }} 条</span>
          <button :disabled="payPage * size >= payTotal" class="page-btn" @click="payPage++; loadPayments()">下一页 ›</button>
        </div>
      </div>

      <!-- ══ 多维汇总（透视）══ -->
      <div v-if="activeTab === 'summary'">
        <div class="filter-strip" style="margin-top:4px">
          <label class="pay-range-lbl">分组维度</label>
          <select v-model="summaryGroupBy" class="sel-bu" @change="loadGroupSummary">
            <option v-for="d in GROUP_DIMS" :key="d.key" :value="d.key">{{ d.label }}</option>
          </select>
          <span class="text-sm-muted">（沿用上方筛选条件；可点击行下钻到全部明细）</span>
        </div>

        <div class="table-wrap" style="margin-top:12px">
          <table class="rec-table">
            <thead>
              <tr>
                <th>{{ GROUP_DIMS.find(d => d.key === summaryGroupBy)?.label }}</th>
                <th class="ctr">记录数</th>
                <th class="amt">预估总额</th>
                <th class="amt">开票总额</th>
                <th class="amt">已收总额</th>
                <th class="amt">未收总额</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="groupLoading && !groupRows.length"><td colspan="6" class="empty-cell">⏳ 加载中…</td></tr>
              <tr v-else-if="!groupRows.length"><td colspan="6" class="empty-cell">暂无数据</td></tr>
              <tr v-for="r in groupRows" :key="r.key"
                  class="data-row"
                  :class="{ 'row-drill': DRILLABLE_DIMS.includes(summaryGroupBy) }"
                  @click="drillIntoGroup(r)">
                <td class="fw">{{ r.label }}</td>
                <td class="ctr text-sm-muted">{{ r.count }}</td>
                <td class="amt">{{ fmtAmt(r.estimated) }}</td>
                <td class="amt">{{ fmtAmt(r.invoiced) }}</td>
                <td class="amt" style="color:#2e7d32">{{ fmtAmt(r.collected) }}</td>
                <td class="amt" :class="parseFloat(r.outstanding) > 0 ? 'amt-warn' : 'amt-zero'">{{ fmtAmt(r.outstanding) }}</td>
              </tr>
            </tbody>
            <tfoot v-if="groupRows.length">
              <tr class="group-total-row">
                <td class="fw">合计</td>
                <td class="ctr">{{ groupTotals.count }}</td>
                <td class="amt fw">{{ fmtAmt(groupTotals.estimated) }}</td>
                <td class="amt fw">{{ fmtAmt(groupTotals.invoiced) }}</td>
                <td class="amt fw" style="color:#2e7d32">{{ fmtAmt(groupTotals.collected) }}</td>
                <td class="amt fw" :class="groupTotals.outstanding > 0 ? 'amt-warn' : 'amt-zero'">{{ fmtAmt(groupTotals.outstanding) }}</td>
              </tr>
            </tfoot>
          </table>
        </div>
      </div>
    </div>

    <!-- AR Record Modal -->
    <Teleport to="body">
      <div v-if="showModal" class="modal-overlay" @click.self="showModal = false">
        <div class="modal-box" style="max-width:560px">
          <div class="modal-header">
            <h3>{{ editRec ? '编辑应收记录' : '新增应收' }}</h3>
            <button class="modal-close" @click="showModal = false">✕</button>
          </div>
          <div class="modal-body">
            <div class="form-grid">
              <label class="form-field span2">
                <span>关联项目 <em>*</em></span>
                <input v-model="projectKeyword"
                       placeholder="输入项目编号 / 简称 / 合同名称 / 负责人 模糊搜索"
                       :disabled="!!editRec"
                       @input="onProjectKeywordInput" />
                <select v-model="recForm.project_id" :disabled="!!editRec">
                  <option value="" disabled>{{ projectSearching ? '搜索中…' : (projects.length ? '请选择项目' : '无匹配项目') }}</option>
                  <option v-for="p in projects" :key="p.id" :value="p.id">
                    {{ p.project_no }} · {{ p.short_name || p.contract_name }}
                  </option>
                </select>
              </label>
              <label class="form-field">
                <span>运作年 <em>*</em></span>
                <select v-model.number="recForm.operation_year" :disabled="!!editRec">
                  <option v-for="y in years" :key="y" :value="y">{{ y }}</option>
                </select>
              </label>
              <label class="form-field">
                <span>运作月 <em>*</em></span>
                <select v-model.number="recForm.operation_month" :disabled="!!editRec">
                  <option v-for="m in months" :key="m" :value="m">{{ m }}月</option>
                </select>
              </label>
              <label class="form-field">
                <span>预估上账金额</span>
                <input v-model="recForm.estimated_amount" type="number" step="0.01" />
              </label>
              <label class="form-field">
                <span>实际开票金额</span>
                <input v-model="recForm.actual_invoice_amount" type="number" step="0.01" placeholder="开票后填写" />
              </label>
              <label class="form-field">
                <span>税额（差额模式手填）</span>
                <input v-model="recForm.tax_amount" type="number" step="0.01" placeholder="全额模式自动计算" />
              </label>
              <label class="form-field">
                <span>开票日期</span>
                <input v-model="recForm.invoice_date" type="date" />
              </label>
              <label class="form-field">
                <span>对账日期</span>
                <input v-model="recForm.reconciliation_date" type="date" />
              </label>
              <label class="form-field">
                <span>差额调整</span>
                <input v-model="recForm.account_diff_adjustment" type="number" step="0.01" />
              </label>
              <label class="form-field span2">
                <span>备注</span>
                <input v-model="recForm.notes" />
              </label>
            </div>
          </div>
          <div class="modal-footer">
            <button class="btn btn-ghost" @click="showModal = false">取消</button>
            <button class="btn btn-primary" :disabled="saving" @click="saveRec">{{ saving ? '保存中…' : '保存' }}</button>
          </div>
        </div>
      </div>

      <!-- Payment Modal -->
      <div v-if="showPayModal" class="modal-overlay" @click.self="showPayModal = false">
        <div class="modal-box" style="max-width:400px">
          <div class="modal-header">
            <div>
              <h3>录入回款</h3>
              <div style="font-size:12px;color:var(--muted);margin-top:2px">{{ payRec?.short_name || payRec?.contract_name }}</div>
            </div>
            <button class="modal-close" @click="showPayModal = false">✕</button>
          </div>
          <div class="modal-body">
            <div class="form-grid">
              <label class="form-field span2">
                <span>回款金额 <em>*</em></span>
                <input v-model="payForm.amount" type="number" step="0.01" autofocus />
              </label>
              <label class="form-field span2">
                <span>回款日期 <em>*</em></span>
                <input v-model="payForm.payment_date" type="date" />
              </label>
              <label class="form-field span2">
                <span>备注</span>
                <input v-model="payForm.notes" placeholder="可选" />
              </label>
            </div>
          </div>
          <div class="modal-footer">
            <button class="btn btn-ghost" @click="showPayModal = false">取消</button>
            <button class="btn btn-primary" :disabled="paySaving" @click="savePayment">{{ paySaving ? '保存中…' : '保存回款' }}</button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.act-btn {
  padding: 6px 12px; border-radius: 8px; font-size: 12.5px; font-weight: 500;
  border: 1px solid var(--border); background: rgba(255,252,250,0.8); color: var(--muted);
  cursor: pointer; transition: all 0.14s; white-space: nowrap;
}
.act-btn:hover { border-color: var(--primary); color: var(--primary); }
.act-btn:disabled { opacity: 0.4; cursor: default; }

/* Topbar: title + inline tabs */
.topbar-left { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }

/* Segment control */
.segment-ctrl { display: inline-flex; gap: 0; padding: 3px; background: rgba(0,0,0,0.04); border-radius: 11px; flex-wrap: wrap; }
.seg-btn { display: flex; align-items: center; gap: 5px; padding: 6px 14px; border-radius: 9px; border: none; font-size: 12.5px; font-weight: 500; color: var(--muted); background: transparent; cursor: pointer; transition: all 0.18s; }
.seg-btn .seg-dot { width: 6px; height: 6px; border-radius: 50%; background: rgba(155,128,112,0.3); transition: all 0.18s; }
.seg-btn.active { background: white; color: var(--primary); font-weight: 700; box-shadow: 0 2px 8px rgba(0,0,0,0.12); }
.seg-btn.active .seg-dot { background: var(--primary); box-shadow: 0 0 6px rgba(201,99,66,0.5); }

/* Collapsible filter bar */
.filter-bar { margin: 12px 0; }
.filter-main { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.filter-more { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-top: 8px; padding-top: 10px; border-top: 1px dashed var(--border); }
.filter-toggle { display: inline-flex; align-items: center; gap: 5px; padding: 6px 12px; border-radius: 8px; font-size: 12.5px; font-weight: 500; border: 1px solid var(--border); background: rgba(255,252,250,0.8); color: var(--muted); cursor: pointer; transition: all 0.14s; white-space: nowrap; }
.filter-toggle:hover, .filter-toggle.active { border-color: var(--primary); color: var(--primary); }
.filter-toggle svg { transition: transform 0.18s; }
.ft-badge { display: inline-flex; align-items: center; justify-content: center; min-width: 16px; height: 16px; padding: 0 4px; border-radius: 8px; background: var(--primary); color: #fff; font-size: 10.5px; font-weight: 700; }
.filter-chip { display: inline-flex; align-items: center; gap: 5px; font-size: 12px; font-weight: 500; padding: 3px 5px 3px 10px; border-radius: 14px; background: rgba(201,99,66,0.1); color: var(--primary); }
.filter-chip button { display: flex; align-items: center; border: none; background: none; padding: 0; cursor: pointer; color: inherit; opacity: 0.7; font-size: 11px; }
.filter-chip button:hover { opacity: 1; }
.clear-mini { border: none; background: none; color: var(--muted); font-size: 12.5px; cursor: pointer; padding: 4px 6px; text-decoration: underline; text-underline-offset: 2px; }
.clear-mini:hover { color: var(--primary); }

/* KPI bar */
.metrics-bar { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; margin-bottom: 4px; padding: 9px 16px; background: rgba(0,0,0,0.02); border-radius: 12px; }
.metrics-div { width: 1px; align-self: stretch; min-height: 20px; background: rgba(0,0,0,0.1); margin: 0 2px; }
.sum-section-lbl { font-size: 11px; color: var(--muted); letter-spacing: 0.5px; white-space: nowrap; cursor: default; }
.kpi-item { display: flex; align-items: baseline; gap: 6px; }
.kpi-k { font-size: 12px; color: var(--muted); }
.kpi-v { font-size: 15px; font-weight: 700; color: var(--text); }
.kpi-item.ok .kpi-v { color: #2e7d32; }
.kpi-item.warn .kpi-v { color: #e65100; }
.kpi-item.danger .kpi-v { color: #c62828; }
.kpi-progress { display: flex; align-items: center; gap: 10px; min-width: 240px; }
.kpi-track { flex: 1; height: 8px; background: rgba(0,0,0,0.08); border-radius: 99px; overflow: hidden; min-width: 90px; }
.kpi-fill { height: 100%; border-radius: 99px; transition: width 0.5s ease; }
.fill-blue { background: linear-gradient(90deg, #1565c0, #42a5f5); }
.fill-amber { background: linear-gradient(90deg, #e65100, #ffa726); }
.fill-green { background: linear-gradient(90deg, #2e7d32, #66bb6a); }
.kpi-pct { font-size: 15px; font-weight: 800; color: var(--text); min-width: 44px; text-align: right; }

/* 筛选合计 / 区间合计 strip */
.totals-strip { display: flex; align-items: center; gap: 20px; flex-wrap: wrap; margin-top: 12px; padding: 10px 16px; background: linear-gradient(90deg, rgba(201,99,66,0.05), rgba(0,0,0,0.015)); border: 1px solid rgba(201,99,66,0.12); border-radius: 10px; }
.tot-label { font-size: 11px; font-weight: 700; letter-spacing: 0.05em; color: var(--primary); text-transform: uppercase; }
.tot-item { display: inline-flex; align-items: baseline; gap: 5px; font-size: 15px; font-weight: 700; color: var(--text); }
.tot-item i { font-style: normal; font-size: 12px; font-weight: 400; color: var(--muted); }
.tot-item.tot-warn { color: #e65100; }
.tot-item.tot-green { color: #2e7d32; }
.pay-range-lbl { font-size: 12px; color: var(--muted); white-space: nowrap; }
/* 汇总下钻行 + 合计行 */
.row-drill { cursor: pointer; }
.row-drill:hover { background: rgba(201,99,66,0.07); }
.group-total-row td { border-top: 2px solid rgba(0,0,0,0.1); padding: 11px 12px; background: rgba(0,0,0,0.02); }

/* Table */
.rec-table { width: 100%; }
.rec-table th { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); padding: 9px 12px; background: rgba(0,0,0,0.02); white-space: nowrap; }
.rec-table td { padding: 10px 12px; vertical-align: middle; }
.data-row { transition: background 0.12s; }
.data-row:hover { background: rgba(201,99,66,0.03); }
.data-row:not(:last-child) td { border-bottom: 1px solid rgba(0,0,0,0.04); }
.row-overdue { background: rgba(198,40,40,0.04); }

.empty-cell { text-align: center; padding: 48px !important; color: var(--muted); font-size: 14px; }
.proj-name { font-weight: 600; font-size: 13.5px; }
.proj-sub { font-size: 11.5px; color: var(--muted); margin-top: 1px; max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.proj-no { font-family: monospace; font-size: 11px; color: var(--muted); margin-top: 2px; }
.notes-col { max-width: 140px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; }
.ym-chip { font-size: 12px; font-weight: 600; color: var(--muted); background: rgba(0,0,0,0.05); padding: 2px 8px; border-radius: 6px; white-space: nowrap; }
.ctr { text-align: center; }
.amt { text-align: right; }
.fw { font-weight: 700; }
.text-muted { color: var(--muted); }
.text-sm-muted { font-size: 12px; color: var(--muted); }
.amt-warn { color: #e65100; font-weight: 700; }
.amt-zero { color: var(--muted); }
.mode-tag { font-size: 11.5px; padding: 2px 8px; border-radius: 8px; background: rgba(0,0,0,0.05); color: var(--muted); font-weight: 500; }

/* Status pills */
.status-pill { font-size: 11.5px; padding: 3px 9px; border-radius: 20px; font-weight: 600; white-space: nowrap; }
.pill-ok     { background: rgba(46,125,50,0.1);  color: #2e7d32; }
.pill-warn   { background: rgba(245,127,23,0.12); color: #e65100; }
.pill-danger { background: rgba(198,40,40,0.1);  color: #c62828; }
.pill-blue   { background: rgba(21,101,192,0.1); color: #1565c0; }
.pill-muted  { background: rgba(0,0,0,0.06);     color: var(--muted); }

/* Payment rows */
.pay-toggle { display: inline-flex; align-items: center; gap: 4px; padding: 3px 8px; border-radius: 7px; border: 1px solid var(--border); background: rgba(255,252,250,0.8); cursor: pointer; transition: all 0.14s; font-size: 12.5px; }
.pay-toggle:hover { border-color: var(--primary); }
.pay-count { font-size: 11px; font-weight: 700; min-width: 16px; height: 16px; line-height: 16px; text-align: center; border-radius: 50%; }
.count-has { background: rgba(46,125,50,0.15); color: #2e7d32; }
.count-none { background: rgba(0,0,0,0.06); color: var(--muted); }
.add-pay-btn { margin-left: 6px; font-size: 12px; padding: 3px 9px; border-radius: 7px; border: 1px solid rgba(201,99,66,0.3); background: rgba(201,99,66,0.07); color: var(--primary); cursor: pointer; transition: all 0.14s; }
.add-pay-btn:hover { background: var(--primary); color: #fff; }
.pay-row td { background: rgba(0,0,0,0.015); padding: 7px 12px; }
.pay-empty { text-align: center; color: var(--muted); font-size: 12.5px; }
.pay-detail { display: flex; align-items: center; gap: 14px; padding-left: 20px; }
.pay-no { font-size: 11px; color: var(--muted); }
.pay-amt { font-weight: 700; color: #2e7d32; }
.pay-date { font-size: 12px; color: var(--muted); }
.pay-notes { font-size: 12px; color: var(--muted); font-style: italic; }
.pay-del { margin-left: auto; font-size: 11.5px; color: #c62828; background: none; border: none; cursor: pointer; }
.pay-del:hover { text-decoration: underline; }

.row-acts { display: flex; gap: 4px; justify-content: center; }
.icon-btn { width: 26px; height: 26px; border-radius: 6px; border: 1px solid var(--border); background: rgba(255,252,250,0.7); display: flex; align-items: center; justify-content: center; color: var(--muted); cursor: pointer; transition: all 0.13s; }
.icon-btn:hover { border-color: var(--primary); color: var(--primary); }
.icon-btn-del:hover { border-color: #c62828; color: #c62828; background: rgba(198,40,40,0.07); }

.pagination { display: flex; align-items: center; justify-content: center; gap: 14px; padding: 16px 0 4px; }
.page-btn { padding: 5px 14px; border: 1px solid var(--border); border-radius: 8px; background: rgba(255,252,250,0.7); color: var(--text); font-size: 13px; cursor: pointer; transition: all 0.14s; }
.page-btn:hover { border-color: var(--primary); color: var(--primary); }
.page-btn:disabled { opacity: 0.35; cursor: default; }
.page-info { font-size: 13px; color: var(--muted); }
</style>
