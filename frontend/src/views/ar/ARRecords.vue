<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
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
  reconciliation_status: '', invoice_status: '', q: '', project_id: '',
  due_start: '', due_end: '', manager: '', is_shared: '',
})

const showModal = ref(false)
const editRec = ref(null)
const saving = ref(false)
const recForm = reactive({
  project_id: '', operation_year: yearCST(), operation_month: monthCST(),
  estimated_amount: '', actual_invoice_amount: '', tax_amount: '',
  invoice_date: '', reconciliation_time: '', account_diff_adjustment: '', notes: '',
})

const projects = ref([])
const projectKeyword = ref('')
const filteredProjects = computed(() => {
  const kw = projectKeyword.value.trim().toLowerCase()
  if (!kw) return projects.value
  return projects.value.filter(p => (`${p.project_no} ${p.short_name || p.contract_name}`).toLowerCase().includes(kw))
})
const showPayModal = ref(false)
const payRec = ref(null)
const payForm = reactive({ amount: '', payment_date: '', notes: '' })
const paySaving = ref(false)
const expandedPayments = ref({})
const importing = ref(false)
const exporting = ref(false)
const fileInput = ref(null)

const accessibleDepts = computed(() =>
  auth.isSuperAdmin ? DEPARTMENTS : (auth.user?.departments || []).filter(d => DEPARTMENTS.includes(d)))
const years = Array.from({ length: 5 }, (_, i) => yearCST() - 2 + i)
const months = Array.from({ length: 12 }, (_, i) => i + 1)

// Field-permission column visibility
const show = k => auth.canArView(k)

const TABS = [
  { key: 'all', label: '全部明细' },
  { key: 'reconciliation', label: '对账跟踪' },
  { key: 'invoice', label: '开票跟踪' },
  { key: 'collection', label: '回款跟踪' },
]

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
    kpiData.value = kpi.data
  } finally { loading.value = false }
}

async function loadProjects() {
  const res = await ar.listProjects({ size: 200 })
  projects.value = res.data.items
}

function openCreate() {
  editRec.value = null
  Object.assign(recForm, {
    project_id: projects.value[0]?.id || '',
    operation_year: yearCST(), operation_month: monthCST(),
    estimated_amount: '', actual_invoice_amount: '', tax_amount: '',
    invoice_date: '', reconciliation_time: '', account_diff_adjustment: '', notes: '',
  })
  showModal.value = true
  projectKeyword.value = ''
}

function openEdit(rec) {
  editRec.value = rec
  Object.assign(recForm, {
    project_id: rec.project_id, operation_year: rec.operation_year, operation_month: rec.operation_month,
    estimated_amount: rec.estimated_amount, actual_invoice_amount: rec.actual_invoice_amount || '',
    tax_amount: rec.tax_amount || '', invoice_date: rec.invoice_date || '',
    reconciliation_time: rec.reconciliation_time ? rec.reconciliation_time.slice(0, 16) : '',
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
      reconciliation_time: recForm.reconciliation_time || null, account_diff_adjustment: recForm.account_diff_adjustment || 0, notes: recForm.notes,
    }
    if (editRec.value) await ar.updateRecord(editRec.value.id, payload)
    else await ar.createRecord(payload)
    showModal.value = false; await load()
  } catch (e) { alert(e?.response?.data?.msg || '保存失败')
  } finally { saving.value = false }
}

async function deleteRec(rec) {
  if (!confirm(`确定删除「${rec.short_name}」${rec.operation_year}年${rec.operation_month}月的应收记录？`)) return
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

onMounted(() => {
  // Pick up query params from router navigation (e.g., from Cashflow or Analytics)
  if (route.query.status) filters.status = route.query.status
  if (route.query.project_id) filters.project_id = route.query.project_id
  if (route.query.dept) filters.dept = route.query.dept
  load(); loadProjects()
})
function clearFilters() {
  Object.assign(filters, { dept: '', year: '', month: '', status: '', reconciliation_status: '', invoice_status: '', q: '', project_id: '', due_start: '', due_end: '', manager: '', is_shared: '' })
  load(true)
}
</script>

<template>
  <div>
    <div class="topbar">
      <div>
        <h1>应收明细</h1>
        <div style="font-size:13px;color:var(--muted);margin-top:2px">全部明细 · 对账 / 开票 / 回款 跟踪</div>
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

    <!-- Filter strip -->
    <div class="filter-strip">
      <select v-model="filters.dept" class="sel-bu" @change="load(true)">
        <option value="">全部事业部</option>
        <option v-for="d in accessibleDepts" :key="d" :value="d">{{ d }}</option>
      </select>
      <select v-model="filters.year" class="sel-yr" @change="load(true)">
        <option value="">全部年份</option>
        <option v-for="y in years" :key="y" :value="y">{{ y }}年</option>
      </select>
      <select v-model="filters.month" class="sel-mo" @change="load(true)">
        <option value="">全月</option>
        <option v-for="m in months" :key="m" :value="m">{{ m }}月</option>
      </select>
      <input v-model="filters.due_start" type="date" class="sel-mo" @change="load(true)" />
      <input v-model="filters.due_end" type="date" class="sel-mo" @change="load(true)" />
      <select v-model="filters.status" class="sel-mo" @change="load(true)">
        <option value="">全部状态</option>
        <option value="overdue">逾期</option>
        <option value="current">当期</option>
        <option value="not_due">未到期</option>
        <option value="settled">已结清</option>
      </select>
      <select v-model="filters.reconciliation_status" class="sel-mo" @change="load(true)">
        <option value="">对账(全部)</option>
        <option value="已对账">已对账</option>
        <option value="未对账">未对账</option>
      </select>
      <select v-model="filters.invoice_status" class="sel-mo" @change="load(true)">
        <option value="">开票(全部)</option>
        <option value="未开票">未开票</option>
        <option value="已开票">已开票</option>
        <option value="已结清">已结清</option>
      </select>
      <select v-model="filters.is_shared" class="sel-mo" @change="load(true)">
        <option value="">共享(全部)</option>
        <option value="1">共享</option>
        <option value="0">非共享</option>
      </select>
      <input v-model="filters.manager" placeholder="负责人" class="search-input" @input="load(true)" />
      <input v-model="filters.q" placeholder="搜索项目" class="search-input" @input="load(true)" />
      <button class="act-btn" @click="Object.assign(filters, { status: 'outstanding' }); load(true)">未结清</button>
      <button class="act-btn" @click="clearFilters">清空筛选</button>
    </div>

    <!-- Tab + table card -->
    <div class="card" :class="{ 'data-reloading': loading && items.length }">
      <!-- Segment tab control -->
      <div class="segment-ctrl">
        <button v-for="t in TABS" :key="t.key"
          :class="['seg-btn', activeTab === t.key ? 'active' : '']" @click="activeTab = t.key">
          <span class="seg-dot"></span>{{ t.label }}
        </button>
      </div>

      <!-- Per-tab completion KPI bar -->
      <div v-if="kpiData" class="kpi-bar">
        <template v-if="activeTab === 'all'">
          <div class="kpi-item"><span class="kpi-k">总记录</span><span class="kpi-v">{{ kpiData.total }}</span></div>
          <div class="kpi-item danger"><span class="kpi-k">逾期</span><span class="kpi-v">{{ kpiData.overdue.count }} 笔 / {{ fmtAmt(kpiData.overdue.amount) }}</span></div>
          <div class="kpi-item warn"><span class="kpi-k">未结清</span><span class="kpi-v">{{ kpiData.collection.outstanding_count }} 笔 / {{ fmtAmt(kpiData.collection.outstanding_amount) }}</span></div>
        </template>
        <template v-else-if="activeTab === 'reconciliation'">
          <div class="kpi-progress">
            <div class="kpi-k">对账完成度</div>
            <div class="kpi-track"><div class="kpi-fill fill-blue" :style="`width:${kpiData.reconciliation.rate}%`"></div></div>
            <div class="kpi-pct">{{ kpiData.reconciliation.rate }}%</div>
          </div>
          <div class="kpi-item ok"><span class="kpi-k">已对账</span><span class="kpi-v">{{ kpiData.reconciliation.done }}</span></div>
          <div class="kpi-item warn"><span class="kpi-k">待对账</span><span class="kpi-v">{{ kpiData.reconciliation.pending }} 笔 / {{ fmtAmt(kpiData.reconciliation.pending_amount) }}</span></div>
        </template>
        <template v-else-if="activeTab === 'invoice'">
          <div class="kpi-progress">
            <div class="kpi-k">开票完成度</div>
            <div class="kpi-track"><div class="kpi-fill fill-amber" :style="`width:${kpiData.invoice.rate}%`"></div></div>
            <div class="kpi-pct">{{ kpiData.invoice.rate }}%</div>
          </div>
          <div class="kpi-item ok"><span class="kpi-k">已开票</span><span class="kpi-v">{{ kpiData.invoice.done }}</span></div>
          <div class="kpi-item warn"><span class="kpi-k">待开票</span><span class="kpi-v">{{ kpiData.invoice.pending }} 笔</span></div>
        </template>
        <template v-else>
          <div class="kpi-progress">
            <div class="kpi-k">回款结清率</div>
            <div class="kpi-track"><div class="kpi-fill fill-green" :style="`width:${kpiData.collection.rate}%`"></div></div>
            <div class="kpi-pct">{{ kpiData.collection.rate }}%</div>
          </div>
          <div class="kpi-item ok"><span class="kpi-k">已结清</span><span class="kpi-v">{{ kpiData.collection.settled }}</span></div>
          <div class="kpi-item warn"><span class="kpi-k">未收</span><span class="kpi-v">{{ kpiData.collection.outstanding_count }} 笔 / {{ fmtAmt(kpiData.collection.outstanding_amount) }}</span></div>
          <div class="kpi-item danger"><span class="kpi-k">其中逾期</span><span class="kpi-v">{{ kpiData.overdue.count }} 笔</span></div>
        </template>
      </div>

      <div class="table-wrap" style="margin-top:12px">
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
              </template>
              <!-- reconciliation -->
              <template v-else-if="activeTab === 'reconciliation'">
                <th v-if="show('r_estimated_amount')" class="amt">预估金额</th>
                <th v-if="show('r_reconciliation')" class="ctr">对账状态</th>
                <th v-if="show('r_reconciliation')" class="ctr">对账时间</th>
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
                  <td v-if="show('r_account_diff')" class="amt" :class="parseFloat(rec.account_diff_adjustment) !== 0 ? 'amt-warn' : 'amt-zero'">{{ parseFloat(rec.account_diff_adjustment) !== 0 ? fmtAmt(rec.account_diff_adjustment) : '—' }}</td>
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
                </template>

                <!-- reconciliation -->
                <template v-else-if="activeTab === 'reconciliation'">
                  <td v-if="show('r_estimated_amount')" class="amt fw">{{ fmtAmt(rec.estimated_amount) }}</td>
                  <td v-if="show('r_reconciliation')" class="ctr">
                    <span :class="['status-pill', rec.reconciliation_status === '已对账' ? 'pill-ok' : 'pill-warn']">{{ rec.reconciliation_status }}</span>
                  </td>
                  <td v-if="show('r_reconciliation')" class="ctr text-sm-muted">{{ rec.reconciliation_time ? rec.reconciliation_time.slice(0,10) : '—' }}</td>
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
                  <td v-if="show('r_account_diff')" class="amt" :class="parseFloat(rec.account_diff_adjustment) !== 0 ? 'amt-warn' : 'amt-zero'">{{ parseFloat(rec.account_diff_adjustment) !== 0 ? fmtAmt(rec.account_diff_adjustment) : '—' }}</td>
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

      <div v-if="total > size" class="pagination">
        <button :disabled="page <= 1" class="page-btn" @click="page--; load()">‹ 上一页</button>
        <span class="page-info">{{ page }} / {{ Math.ceil(total / size) }} 页 · 共 {{ total }} 条</span>
        <button :disabled="page * size >= total" class="page-btn" @click="page++; load()">下一页 ›</button>
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
                <input v-model="projectKeyword" placeholder="输入项目编号/简称模糊搜索" :disabled="!!editRec" />
                <select v-model="recForm.project_id" :disabled="!!editRec">
                  <option value="" disabled>请选择项目</option>
                  <option v-for="p in filteredProjects" :key="p.id" :value="p.id">
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
                <span>对账时间</span>
                <input v-model="recForm.reconciliation_time" type="datetime-local" />
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

/* Segment control */
.segment-ctrl { display: inline-flex; gap: 0; padding: 4px; background: rgba(0,0,0,0.04); border-radius: 12px; }
.seg-btn { display: flex; align-items: center; gap: 6px; padding: 7px 18px; border-radius: 9px; border: none; font-size: 13px; font-weight: 500; color: var(--muted); background: transparent; cursor: pointer; transition: all 0.18s; }
.seg-btn .seg-dot { width: 6px; height: 6px; border-radius: 50%; background: rgba(155,128,112,0.3); transition: all 0.18s; }
.seg-btn.active { background: white; color: var(--primary); font-weight: 700; box-shadow: 0 2px 8px rgba(0,0,0,0.12); }
.seg-btn.active .seg-dot { background: var(--primary); box-shadow: 0 0 6px rgba(201,99,66,0.5); }

/* KPI bar */
.kpi-bar { display: flex; align-items: center; gap: 18px; flex-wrap: wrap; margin-top: 14px; padding: 12px 16px; background: rgba(0,0,0,0.02); border-radius: 12px; }
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
.proj-no { font-family: monospace; font-size: 11px; color: var(--muted); margin-top: 2px; }
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
