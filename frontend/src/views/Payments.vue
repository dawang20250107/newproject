<script setup>
import { ref, onMounted, onBeforeUnmount, reactive, computed, watch } from 'vue'
import { useToast } from '../composables/useToast.js'
import api from '../api/index.js'
import { useAuthStore } from '../stores/auth.js'
import { todayCST } from '../constants.js'
import { fmtMoney, fmtTime } from '../utils/format.js'
import { downloadBlob } from '../utils/download.js'
import StatusBadge from '../components/StatusBadge.vue'
import PaymentModal from '../components/PaymentModal.vue'
import ImportResultModal from '../components/ImportResultModal.vue'
import ImportPrecheckModal from '../components/ImportPrecheckModal.vue'
import EmptyState from '../components/EmptyState.vue'
import ColumnFilter from '../components/ColumnFilter.vue'
import SkeletonRow from '../components/SkeletonRow.vue'
import SchemePicker from '../components/SchemePicker.vue'
import { useTableSchemes } from '../composables/useTableSchemes.js'
import { useColWidths } from '../composables/useColWidths.js'
import ContextMenu from '../components/ContextMenu.vue'
import { useContextMenu } from '../composables/useContextMenu.js'
import { copyText, copyRowTSV } from '../utils/clipboard.js'
import { useAsyncExport } from '../composables/useAsyncExport.js'
import { useRangeSelection } from '../composables/useRangeSelection.js'
import { createRequestLane } from '../utils/requestLane.js'
import { cachedGet } from '../api/refCache.js'

const toast = useToast()
const auth = useAuthStore()
const { exporting: bgExporting, startExport } = useAsyncExport()
// Excel 式区域选择 + 复制（忽略首列复选框）
const rangeSel = useRangeSelection({ ignoreCols: [0], onCopy: n => toast.success(`已复制 ${n} 个单元格，可粘贴进 Excel`) })

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
  { key: 'g7_number',          label: 'G7编号',   perm: () => true },
  { key: 'project_desc',       label: '付款事项', perm: () => auth.canView('project_desc') },
  { key: 'payee',              label: '收款方',   perm: () => auth.canView('payee') },
  { key: 'planned_date',       label: '计划日期', perm: () => auth.canView('planned_date') },
  { key: 'total_amount',       label: '计划额',   perm: () => auth.canView('total_amount') },
  { key: 'paid',               label: '已付',     perm: () => showPaid.value },
  { key: 'remaining',          label: '剩余',     perm: () => showRemaining.value },
  { key: 'status',             label: '状态',     perm: () => true },
  { key: 'overdue',            label: '逾期',     perm: () => true },
  { key: 'plan_adjustment',    label: '计划调整', perm: () => auth.canView('plan_adjustment') },
  { key: 'notes',              label: '备注',     perm: () => true },
]
// 业务默认列可见性：默认隐藏「G7编号」「计划调整」（一次性应用，合并进用户已有偏好，
// 不清除其它选择；用户之后手动显示则保留其选择）。
const PK_COL_DEFAULTS_VER = '1'
const hiddenCols = ref(new Set())
try {
  const raw = localStorage.getItem('pk_pay_hidden_cols')
  const s = new Set(Array.isArray(JSON.parse(raw || 'null')) ? JSON.parse(raw) : [])
  if (localStorage.getItem('pk_pay_col_defaults_ver') !== PK_COL_DEFAULTS_VER) {
    s.add('g7_number'); s.add('plan_adjustment')
    localStorage.setItem('pk_pay_hidden_cols', JSON.stringify([...s]))
    localStorage.setItem('pk_pay_col_defaults_ver', PK_COL_DEFAULTS_VER)
  }
  hiddenCols.value = s
} catch {}
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

// ── 行明细展开：计划明细（分批排款）+ 付款明细（分期实付）─────────────────────
// 列表为轻量态（不含明细），展开时按需拉 GET /payments/<id> 补齐 plan_items/installments。
const expandedRows = ref(new Set())
async function hydrateRowDetail(id) {
  const p = items.value.find(x => x.id === id)
  if (!p) return
  try {
    const res = await api.get(`/payments/${id}`)
    p.plan_items = res.data.plan_items || []
    p.installments = res.data.installments || []
  } catch { /* 拉取失败保持展开，显示空明细即可 */ }
}
function toggleRowDetail(id) {
  const s = new Set(expandedRows.value)
  if (s.has(id)) {
    s.delete(id)
    // 收起正在编辑/追加批次的行时复位编辑态，避免全局 planEdit 残留把所有行的批次按钮隐藏
    if (planEdit.id === `new:${id}` || rowOwnsPlanEdit(id)) cancelEditPlan()
  } else {
    s.add(id)
    hydrateRowDetail(id)   // 展开即补拉明细
  }
  expandedRows.value = s
}
// planEdit.id 是否属于该付款行（其某条计划批次正在编辑，或正在向该行追加批次）
function rowOwnsPlanEdit(paymentId) {
  if (!planEdit.id) return false
  if (planEdit.id === `new:${paymentId}`) return true
  const p = items.value.find(x => x.id === paymentId)
  return !!(p && p.plan_items?.some(pi => pi.id === planEdit.id))
}
function isRowEditing(p) { return rowOwnsPlanEdit(p.id) }
// 双击行 → 展开/收起 计划+付款明细（点在控件或计划日期单元格上不重复触发）
function onRowDblClick(p, e) {
  if (e.target.closest('input, button, select, textarea, a, .plan-cell')) return
  toggleRowDetail(p.id)
}
async function removePlanItem(p, pi) {
  if (!confirm(`撤销第${pi.seq}批计划（${pi.planned_date} · ${pi.amount} 元）？\n汇总金额回退；来源审批的已排款同步扣减、可继续分批排款。`)) return
  try {
    const res = await api.delete(`/payments/${p.id}/plan-items/${pi.id}`)
    toast.success(res.data?.message || '已撤销')
    load()
  } catch (e) { toast.error(e?.msg || e?.error || '撤销失败') }
}

// ── 排款管理：编辑 / 追加 计划批次（与来源审批已排款双向同步）────────────────────
// planEdit.id：正在编辑的批次id（'new:'+paymentId 表示该付款正在追加新批次）
const planEdit = reactive({ id: null, planned_date: '', amount: '', notes: '', busy: false })
function startEditPlan(pi) {
  planEdit.id = pi.id
  planEdit.planned_date = pi.planned_date
  planEdit.amount = pi.amount
  planEdit.notes = pi.notes || ''
  planEdit.busy = false
}
function startAddPlan(p) {
  planEdit.id = `new:${p.id}`
  planEdit.planned_date = todayCST()
  planEdit.amount = ''
  planEdit.notes = ''
  planEdit.busy = false
}
function cancelEditPlan() { planEdit.id = null }
async function saveEditPlan(p, pi) {
  const amt = parseFloat(planEdit.amount)
  if (!planEdit.planned_date) { toast.warn('请填写计划日期'); return }
  if (!(amt > 0)) { toast.warn('计划金额必须大于0'); return }
  planEdit.busy = true
  try {
    const body = { planned_date: planEdit.planned_date, amount: amt, notes: planEdit.notes }
    const res = await api.put(`/payments/${p.id}/plan-items/${pi.id}`, body)
    toast.success(res.data?.message || '已调整')
    planEdit.id = null
    load()
  } catch (e) { toast.error(e?.msg || e?.error || '调整失败') }
  finally { planEdit.busy = false }
}
async function saveAddPlan(p) {
  const amt = parseFloat(planEdit.amount)
  if (!planEdit.planned_date) { toast.warn('请填写计划日期'); return }
  if (!(amt > 0)) { toast.warn('计划金额必须大于0'); return }
  planEdit.busy = true
  try {
    const body = { planned_date: planEdit.planned_date, amount: amt, notes: planEdit.notes }
    const res = await api.post(`/payments/${p.id}/plan-items`, body)
    toast.success(res.data?.message || '已追加批次')
    planEdit.id = null
    load()
  } catch (e) { toast.error(e?.msg || e?.error || '追加失败') }
  finally { planEdit.busy = false }
}
const items = ref([])
const total = ref(0)
const outstandingTotal = ref('0')
const outstandingCount = ref(0)
const plannedTotal = ref('0')
const paidTotal = ref('0')
const loading = ref(true)   // 挂载即进入加载态：直接显示骨架屏，避免方案/数据拉取期间闪现空状态
const departments = ref([])
const showModal = ref(false)
const editItem = ref(null)
const loadErr = ref('')
const listLane = createRequestLane()   // 列表请求竞态车道：新请求自动取消旧请求
const today = todayCST()  // UTC+8，与服务端 Asia/Shanghai 保持一致

const filters = reactive({
  q: '', pay_date_start: '', pay_date_end: '',
  page: 1, size: 50,
})

// 列宽持久化
const cw = useColWidths('pk_payments', {
  project_desc: 200, payee: 130, department: 70, secondary_dept: 80,
  project_short_name: 100, applicant: 70, approval_number: 110, g7_number: 110,
  planned_date: 88, total_amount: 96, paid: 92, remaining: 92, status: 96, notes: 84,
})

// ── Excel 风格列头筛选 + 排序 ───────────────────────────────────────────────
// 计划状态为计算口径，单独走既有 status 查询参数（单选）；其余真实列走 colFilters JSON。
const PAY_STATUS_OPTS = [
  { value: 'pending', label: '⏳ 待付款' }, { value: 'partial', label: '⚡ 部分付款' },
  { value: 'settled', label: '✅ 已付清' }, { value: 'adjusted', label: '📋 计划调整' },
  { value: 'overdue', label: '⚠ 已逾期' },
]
// 逾期列：派生是/否（计划日期已过且未结清）
const OVERDUE_OPTS = [{ value: '是', label: '是（已逾期）' }, { value: '否', label: '否' }]
const colFilters = reactive({})    // field -> {op, value}（不含 status）
const statusSel = ref([])          // 计划状态多选 → status 查询参数（逗号分隔并集）
const payDeptFilter = ref('')      // 筛选栏事业部快选
const hideSettled = ref(true)      // 默认隐藏已付清（进入页面默认展示非已付清）
const sortField = ref('')
const sortOrder = ref('')
const activeFilterCount = computed(() =>
  Object.keys(colFilters).length + (statusSel.value.length ? 1 : 0) + (payDeptFilter.value ? 1 : 0))
function setColFilter(field, val) {
  if (val == null) delete colFilters[field]
  else colFilters[field] = val
  filters.page = 1; clearSelection(); load()
}
function setStatusFilter(val) {
  // 状态列多选，ColumnFilter 以 {op:'in',value:[...]} 上抛
  statusSel.value = (val && Array.isArray(val.value)) ? val.value.filter(Boolean) : []
  filters.page = 1; clearSelection(); load()
}
const statusColModel = computed(() => statusSel.value.length ? { op: 'in', value: [...statusSel.value] } : null)
function setSort(field, order) {
  sortField.value = order ? field : ''
  sortOrder.value = order || ''
  filters.page = 1; load()
}
// 通用筛选方案（表格方案基座）：保存列头筛选 + 排序 + 计划状态单选为命名方案
const schemes = useTableSchemes('pk_payments', {
  colFilters, sortField, sortOrder,
  extra: {
    get: () => ({ status: statusSel.value.join(',') || '', dept: payDeptFilter.value || '', hide_settled: hideSettled.value }),
    set: (p) => {
      statusSel.value = p.status ? String(p.status).split(',').filter(Boolean) : []
      payDeptFilter.value = p.dept || ''
      hideSettled.value = p.hide_settled !== false
    },
  },
  onApply: () => { filters.page = 1; clearSelection(); load() },
})
// 重点付款筛选 + 批量单号筛选
const priorityOnly = ref(false)   // 只看重点
const numbersFilter = ref('')     // 已应用的批量单号（逗号连接）
function buildParams() {
  const p = { page: filters.page, size: filters.size }
  if (filters.q.trim()) p.q = filters.q.trim()
  if (payDeptFilter.value) p.dept = payDeptFilter.value
  if (statusSel.value.length) p.status = statusSel.value.join(',')
  if (hideSettled.value && !statusSel.value.length) p.hide_settled = '1'
  if (Object.keys(colFilters).length) p.filters = JSON.stringify(colFilters)
  if (sortField.value && sortOrder.value) { p.sort = sortField.value; p.order = sortOrder.value }
  if (priorityOnly.value) p.priority = '1'
  if (numbersFilter.value) p.numbers = numbersFilter.value
  return p
}
// activeFilterCount 已含列头/状态/部门；这里把重点与单号也并入提示（不影响原逻辑）
const extraFilterCount = computed(() => (priorityOnly.value ? 1 : 0) + (numbersFilter.value ? 1 : 0))

// ── tab control: 台账 | 付款流水 ─────────────────────────────────────────────
const activeTab = ref('ledger')  // 'ledger' | 'flow'

// 付款流水 state
const flowItems = ref([])
const flowTotal = ref(0)
const flowTotalAmount = ref('0')
const flowLoading = ref(false)
const flowPage = ref(1)
const flowFilters = reactive({ q: '', dept: '', pay_date_start: '', pay_date_end: '', g7_number: '' })
const flowDatePreset = ref('')

async function loadFlow() {
  flowLoading.value = true
  try {
    const params = Object.fromEntries(Object.entries({
      ...flowFilters, page: flowPage.value, size: 50,
    }).filter(([, v]) => v !== ''))
    const res = await api.get('/payments/installments', { params })
    flowItems.value = res.data.items
    flowTotal.value = res.data.total
    flowTotalAmount.value = res.data.total_amount ?? '0'
  } catch (e) { console.error(e) }
  finally { flowLoading.value = false }
}

function searchFlow() { flowPage.value = 1; loadFlow() }
function resetFlowFilters() {
  Object.assign(flowFilters, { q: '', dept: '', pay_date_start: '', pay_date_end: '', g7_number: '' })
  flowDatePreset.value = ''; flowPage.value = 1; loadFlow()
}

function applyFlowDatePreset() {
  if (flowDatePreset.value === '') { flowFilters.pay_date_start = ''; flowFilters.pay_date_end = '' }
  else if (flowDatePreset.value !== 'custom') {
    const [s, e] = dateRangeFor(flowDatePreset.value)
    flowFilters.pay_date_start = s; flowFilters.pay_date_end = e
  }
  flowPage.value = 1; loadFlow()
}

function switchTab(t) {
  activeTab.value = t
  if (t === 'flow' && !flowItems.value.length && !flowLoading.value) loadFlow()
}

// ── date preset selector ──────────────────────────────────────────────────────
const payDatePreset = ref('')

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

function applyPayDatePreset() {
  // 回款日期跨关联表，无对应可视列 → 仍走顶部预设，统一落到 colFilters.pay_date
  if (payDatePreset.value === '' ) {
    filters.pay_date_start = ''; filters.pay_date_end = ''
    delete colFilters.pay_date
  } else if (payDatePreset.value === 'custom') {
    // 自定义：由下方两个日期框驱动（@change 调 applyPayDateCustom）
  } else {
    const [s, e] = dateRangeFor(payDatePreset.value)
    filters.pay_date_start = s; filters.pay_date_end = e
    colFilters.pay_date = { op: 'between', value: [s, e] }
  }
  filters.page = 1; load()
}
function applyPayDateCustom() {
  const s = filters.pay_date_start, e = filters.pay_date_end
  if (s || e) colFilters.pay_date = { op: 'between', value: [s, e] }
  else delete colFilters.pay_date
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
  } catch { toast.error('模板下载失败') }
}

function triggerImport() {
  importResult.value = null
  precheckResult.value = null
  importInputRef.value.click()
}

// ── 智能导入：选文件 → 先做规则+AI 预检（只读不落库）。发现「需关注」的行才让 AI
//    介入弹窗、协助就地修正后再导入；全部通过 / 超大文件跳过预检则直接导入 ──────────
const precheckResult = ref(null)
const precheckBusy = ref(false)

async function onImportFile(e) {
  const file = e.target.files[0]
  if (!file) return
  e.target.value = ''
  importing.value = true
  importResult.value = null
  precheckResult.value = null
  try {
    // 第一步：预检（规则校验 + AI 复核）
    const fd = new FormData()
    fd.append('file', file)
    const report = (await api.post('/payments/import/precheck', fd, {
      headers: { 'Content-Type': 'multipart/form-data' }, timeout: 120000,
    })).data
    // 发现问题 → AI 介入：弹窗展示问题并协助就地修正后再导入
    if (report && !report.skipPrecheck && report.attention > 0) {
      precheckResult.value = report
      return
    }
    // 全部通过（或超大文件跳过预检）→ 直接导入
    const fd2 = new FormData()
    fd2.append('file', file)
    const res = await api.post('/payments/import', fd2, {
      headers: { 'Content-Type': 'multipart/form-data' }, timeout: 60000,
    })
    importResult.value = res.data
    if (res.data.created > 0) load()
  } catch (ex) {
    importResult.value = { error: ex?.msg || '导入失败，请检查文件格式' }
  } finally {
    importing.value = false
  }
}

async function onPrecheckApply({ mode, rows, okRows }) {
  precheckBusy.value = true
  try {
    if (mode === 'download') {
      const blob = await api.post('/payments/import/apply',
        { rows, okRows, mode: 'download' }, { responseType: 'blob', timeout: 90000 })
      triggerDownload(blob, '付款管理_修正版.xlsx')
    } else {
      const res = await api.post('/payments/import/apply', { rows, okRows, mode: 'import' }, { timeout: 90000 })
      precheckResult.value = null
      importResult.value = res.data
      if (res.data.created > 0) load()
    }
  } catch (ex) {
    toast.error(ex?.msg || ex?.error || '处理失败')
  } finally {
    precheckBusy.value = false
  }
}

async function exportExcel() {
  exportingXlsx.value = true
  try {
    const params = buildParams()
    delete params.page; delete params.size
    const blob = await api.get('/payments/export', { params, responseType: 'blob', timeout: 60000 })
    const date = new Date().toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' }).replace('/', '月') + '日'
    triggerDownload(blob, `排款记录_${date}.xlsx`)
  } catch (e) {
    // 同步导出超出上限（>5000 行）→ 自动转后台异步导出
    const msg = e?.msg || e?.error || ''
    if (/超出导出上限|后台导出|导出超过/.test(msg)) {
      const params = buildParams(); delete params.page; delete params.size
      startExport('payments', params)
    } else {
      toast.error(msg || '导出失败，请稍后重试')
    }
  }
  finally { exportingXlsx.value = false }
}

// ── 运输事业部对账单导出（付款管理侧）：已排款付款记录 → 原表格式零误差还原 ──
// 导入口在「审批管理」（建已通过审批记录），此处仅保留导出。仅对可写运输事业部用户展示。
const canTransport = computed(() =>
  auth.canCreate && (auth.isSuperAdmin || auth.effectiveDepts.includes('运输事业部')))
const exportingTransport = ref(false)

async function exportTransport() {
  exportingTransport.value = true
  try {
    // 勾选优先：选中行按 ids 导出；未勾选则导出当前可见范围内全部运输对账记录
    const params = {}
    if (selectedIds.value.size) {
      params.ids = [...selectedIds.value].join(',')
    } else {
      const p = buildParams(); delete p.page; delete p.size
      Object.assign(params, p)
    }
    const blob = await api.get('/payments/transport/export', { params, responseType: 'blob', timeout: 60000 })
    const date = new Date().toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' }).replace('/', '月') + '日'
    triggerDownload(blob, `运输对账单_已结算_${date}.xlsx`)
  } catch (e) { toast.error(e?.msg || '运输对账单导出失败') }
  finally { exportingTransport.value = false }
}

// 运输专用 对账单号（= 审批编号）批量复制到剪贴板 —— 服务端取数，跨页全量。
// 来源：有勾选取勾选（跨页 ids），否则取当前筛选口径全部；后端去重。
// 普通点击用「+」连接，Shift+点击用空格连接。
const copyingG7 = ref(false)
async function copyG7Numbers(e) {
  if (copyingG7.value) return
  const sep = e?.shiftKey ? ' ' : '+'
  copyingG7.value = true
  try {
    const params = {}
    if (selectedIds.value.size) {
      params.ids = [...selectedIds.value].join(',')
    } else {
      const p = buildParams(); delete p.page; delete p.size
      Object.assign(params, p)
    }
    const res = await api.get('/payments/transport/g7-numbers', { params, timeout: 60000 })
    const nums = res.data?.numbers || []
    if (!nums.length) { toast.warn('当前范围内没有对账单号（审批编号）可复制'); return }
    const ok = await copyText(nums.join(sep))
    if (!ok) { toast.error('复制失败，请手动复制'); return }
    let msg = `已复制 ${nums.length} 个对账单号（${sep === '+' ? '+ 连接' : '空格连接'}）`
    if (res.data?.capped) msg += `，已达上限 ${nums.length} 条，请缩小筛选`
    toast.success(msg)
  } catch (err) {
    toast.error(err?.msg || err?.error || '复制对账单号失败')
  } finally { copyingG7.value = false }
}

// 跨页全选：拉取当前筛选口径下全部记录 ID 填入选择集（供跨页批量操作）
const selectingAll = ref(false)
async function selectAllFiltered() {
  if (selectingAll.value) return
  selectingAll.value = true
  try {
    const p = buildParams(); delete p.page; delete p.size
    const res = await api.get('/payments/select-ids', { params: p, timeout: 60000 })
    const ids = res.data?.ids || []
    selectedIds.value = new Set(ids)
    if (res.data?.capped) toast.warn(`已选前 ${ids.length} 条（达单次上限 ${res.data.cap}）；批量操作请分批或缩小筛选`)
    else toast.success(`已跨页选中全部 ${ids.length} 条筛选结果`)
  } catch (err) {
    toast.error(err?.msg || err?.error || '全选失败')
  } finally { selectingAll.value = false }
}

const triggerDownload = downloadBlob

async function load() {
  loading.value = true
  loadErr.value = ''
  const sig = listLane.signal()
  try {
    const res = await api.get('/payments', { params: buildParams(), signal: sig })
    items.value = res.data.items
    total.value = res.data.total
    outstandingTotal.value = res.data.outstanding_total ?? '0'
    outstandingCount.value = res.data.outstanding_count ?? 0
    plannedTotal.value = res.data.planned_total ?? '0'
    paidTotal.value = res.data.paid_total ?? '0'
    loading.value = false
    // 轻量列表不含明细：为仍展开的行补拉分批/分期明细，保持展开态内容正确
    if (expandedRows.value.size) {
      for (const id of expandedRows.value) hydrateRowDetail(id)
    }
  } catch (e) {
    // 被新请求取消：保持 loading，交由接管的新请求收尾
    if (e?.__canceled || sig.aborted) return
    loadErr.value = e?.msg || '加载失败，请刷新重试'
    loading.value = false
  }
}

async function loadDepts() {
  try {
    const res = await cachedGet('/departments')
    departments.value = res.data
  } catch {}
}

// Reload list when the global active-dept scope changes.
const onScopeChange = () => {
  const sel = colFilters.department
  if (sel && Array.isArray(sel.value) && sel.value.some(d => !auth.effectiveDepts.includes(d))) {
    delete colFilters.department
  }
  filters.page = 1
  load()
}
onMounted(async () => {
  loadDepts()
  // 有默认方案则套用并由其 onApply 触发加载；否则常规加载。
  // 方案接口异常也要兜底加载数据，避免卡在骨架屏（loading 初始为 true）。
  try {
    const applied = await schemes.loadAndApplyDefault()
    if (!applied) load()
  } catch { load() }
  window.addEventListener('pk:depts-changed', onScopeChange)
})
onBeforeUnmount(() => window.removeEventListener('pk:depts-changed', onScopeChange))

function openAdd() { editItem.value = null; showModal.value = true }
function openEdit(p) { editItem.value = p; showModal.value = true }

// ── 右键上下文菜单 ────────────────────────────────────────────────────────────
const ctx = useContextMenu()
const ROW_COPY_COLS = [
  { key: 'department', label: '事业部' },
  { key: 'project_short_name', label: '项目' },
  { key: 'payee', label: '收款方' },
  { key: 'approval_number', label: '审批单号' },
  { key: 'planned_date', label: '计划日期' },
  { key: 'total_amount', label: '计划额', format: v => fmtMoney(v) },
  { key: 'total_paid', label: '已付', format: v => fmtMoney(v) },
  { key: 'remaining', label: '剩余', format: v => fmtMoney(v) },
  { key: 'status', label: '状态' },
]
async function copyField(val, label) {
  const ok = await copyText(val)
  ok ? toast.success(`已复制${label ? '：' + label : ''}`) : toast.error('复制失败')
}
async function copyWholeRow(p) {
  const ok = await copyRowTSV(p, ROW_COPY_COLS, { header: true })
  ok ? toast.success('已复制整行（含表头，可粘贴到 Excel）') : toast.error('复制失败')
}
async function returnPayment(p) {
  const label = [p.payee, p.project_short_name || p.project_desc].filter(Boolean).join(' · ') || `#${p.id}`
  const approvalHint = p.approval_id ? `\n来源审批已排款将归零（¥${p.total_amount}），可重新排款。` : ''
  if (!confirm(`退回排款「${label}」（计划 ¥${p.total_amount}）？${approvalHint}\n此操作不可撤销。`)) return
  try {
    await api.delete(`/payments/${p.id}`)
    toast.success('已退回排款，来源审批已排款同步归零')
    load()
  } catch (e) { toast.error(e?.msg || e?.error || '退回失败') }
}

const ctxItems = computed(() => {
  const p = ctx.menu.payload
  if (!p) return []
  const canOffset = auth.canAction('wo_prepaid') && (p.project_short_name || p.project_no)
  return [
    { key: 'detail', label: expandedRows.value.has(p.id) ? '收起明细' : '展开计划/付款明细', icon: 'eye', action: r => toggleRowDetail(r.id) },
    { key: 'priority', label: p.is_priority ? '取消重点标记' : '标记为重点付款', icon: 'star', action: r => togglePriorityOne(r) },
    { key: 'edit', label: '编辑', icon: 'edit', shortcut: 'E', hidden: !auth.canWrite, action: r => openEdit(r) },
    { key: 'return', label: p.approval_id ? '退回排款（还原至审批）' : '退回排款（删除）', icon: 'trash', danger: true, hidden: !auth.canDelete, action: r => returnPayment(r) },
    { key: 'offset', label: '预付核销', icon: 'refresh', hidden: !canOffset, action: r => openOffset(r) },
    { key: 'logs', label: '变更日志', icon: 'history', shortcut: 'L', action: r => openLogs(r) },
    { divider: true },
    {
      key: 'copy', label: '复制', icon: 'copy',
      children: [
        { key: 'copy-row', label: '复制整行', icon: 'copy', shortcut: '⌘C', action: r => copyWholeRow(r) },
        { divider: true },
        { key: 'copy-proj', label: '项目', icon: 'cell', hidden: !p.project_short_name, action: r => copyField(r.project_short_name, r.project_short_name) },
        { key: 'copy-payee', label: '收款方', icon: 'customer', hidden: !p.payee, action: r => copyField(r.payee, r.payee) },
        { key: 'copy-appr', label: '审批单号', icon: 'invoice', hidden: !p.approval_number, action: r => copyField(r.approval_number, r.approval_number) },
        { key: 'copy-remain', label: '剩余应付', icon: 'cell', action: r => copyField(fmtMoney(r.remaining), fmtMoney(r.remaining)) },
      ],
    },
    { divider: true },
    { key: 'del', label: '删除', icon: 'trash', danger: true, hidden: !auth.canDelete, action: r => onDelete(r) },
  ]
})

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
  } catch (e) { toast.error(e?.msg || e?.error || '反向核销失败') }
  finally { offsetBusy.value = false }
}
const offsetRoom = computed(() => parseFloat(offsetTarget.value?.remaining) || 0)
async function doOffset() {
  const amt = parseFloat(offsetForm.amount)
  if (!offsetForm.advance_id) { toast.error('请选择要核销的预付'); return }
  if (!(amt > 0)) { toast.error('冲抵金额必须大于0'); return }
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
  } catch (e) { toast.error(e?.msg || e?.error || '核销失败') }
  finally { offsetBusy.value = false }
}

async function onDelete(p) {
  if (!confirm(`确定删除「${p.project_desc}」？此操作不可撤销。`)) return
  try {
    await api.delete(`/payments/${p.id}`)
    load()
  } catch (e) {
    toast.error(e?.msg || '删除失败')
  }
}

// At module level (not inside setup, before the function)
let _qTimer = null
watch(() => filters.q, () => {
  clearTimeout(_qTimer)
  _qTimer = setTimeout(() => { filters.page = 1; clearSelection(); load() }, 350)
})

function search() { filters.page = 1; clearSelection(); load() }
function resetFilters() {
  Object.assign(filters, { q: '', pay_date_start: '', pay_date_end: '', page: 1 })
  Object.keys(colFilters).forEach(k => delete colFilters[k])
  statusSel.value = []
  payDeptFilter.value = ''
  hideSettled.value = true
  sortField.value = ''; sortOrder.value = ''
  payDatePreset.value = ''
  priorityOnly.value = false
  numbersFilter.value = ''; numbersText.value = ''
  clearSelection()
  load()
}

const totalPages = computed(() => Math.ceil(total.value / filters.size) || 1)
const jumpPage = ref(1)
function setPage(p) { filters.page = p; load() }
function doJump() {
  const p = Math.max(1, Math.min(totalPages.value, jumpPage.value || 1))
  setPage(p)
}

// ── 单选/多选：批量删除 + 批量付款（批量编辑）─────────────────────────────────
const selectedIds = ref(new Set())                       // 跨页按 id 记忆选择
const remOf = (p) => parseFloat(p.remaining) || 0
const pageAllSelected = computed(() => items.value.length > 0 && items.value.every(p => selectedIds.value.has(p.id)))
const selectedCount = computed(() => selectedIds.value.size)
const hasSelection = computed(() => selectedIds.value.size > 0)
function toggleRow(id) { const s = new Set(selectedIds.value); s.has(id) ? s.delete(id) : s.add(id); selectedIds.value = s }
function toggleSelectPage() { const s = new Set(selectedIds.value); if (pageAllSelected.value) items.value.forEach(p => s.delete(p.id)); else items.value.forEach(p => s.add(p.id)); selectedIds.value = s }
function clearSelection() { selectedIds.value = new Set() }
// 批量付款只统计「有剩余应付」的记录（默认付款金额=剩余应付=计划金额）
const selectedPayable = computed(() => items.value.filter(p => selectedIds.value.has(p.id) && remOf(p) > 0))
const batchPaySummary = computed(() => ({
  count: selectedPayable.value.length,
  total: selectedPayable.value.reduce((s, p) => s + remOf(p), 0),
}))
// 选择集是否含当前页之外的记录（决定批量付款是否跨页模式）
const isCrossPageSelection = computed(() =>
  [...selectedIds.value].some(id => !items.value.some(p => p.id === id)))

// 批量删除（含单选）
const bulkDeleting = ref(false)
const showDelConfirm = ref(false)
const delConfirmText = ref('')
const delConfirmCount = ref(0)
const delConfirmOk = computed(() => delConfirmText.value.trim() === String(delConfirmCount.value))
function bulkDelete() { if (!selectedCount.value) return; delConfirmCount.value = selectedCount.value; delConfirmText.value = ''; showDelConfirm.value = true }
async function confirmBulkDelete() {
  if (!delConfirmOk.value) return
  bulkDeleting.value = true
  try {
    const r = await api.post('/payments/bulk-delete', { ids: [...selectedIds.value] })
    showDelConfirm.value = false; clearSelection(); load()
    const d = r.data || {}
    if (d.skipped?.length) toast.error(`${d.message}\n\n未删除明细：\n` + d.skipped.map(s => `#${s.id} ${s.reason}`).slice(0, 15).join('\n'))
  } catch (e) { toast.error(e?.msg || e?.error || '删除失败') }
  finally { bulkDeleting.value = false }
}

// 批量退回排款（=软删付款 + 来源审批已排款归零，可重新排款；含跳过预付核销项）
const bulkReturning = ref(false)
async function bulkReturn() {
  if (!selectedCount.value) return
  if (!confirm(`批量退回排款 ${selectedCount.value} 条？\n所选付款将退回、来源审批已排款归零可重新排款；已关联预付核销的将自动跳过。`)) return
  bulkReturning.value = true
  try {
    const body = isCrossPageSelection.value ? { all: true } : { ids: [...selectedIds.value] }
    const r = await api.post('/payments/bulk-delete', body)
    clearSelection(); load()
    const d = r.data || {}
    let msg = `已退回 ${d.deleted ?? 0} 条排款，来源审批已归零`
    if (d.skipped?.length) { toast.warn(msg + '\n\n跳过：\n' + d.skipped.map(s => `#${s.id} ${s.reason}`).slice(0, 15).join('\n')) }
    else toast.success(msg)
  } catch (e) { toast.error(e?.msg || e?.error || '退回失败') }
  finally { bulkReturning.value = false }
}

// ── 重点付款标记：右键/批量打标、列内角标、一键筛选、一键清除 ──
const markingPriority = ref(false)
async function setPriority(ids, value) {
  if (!ids.length) return
  markingPriority.value = true
  try {
    const r = await api.post('/payments/mark-priority', { ids, value })
    // 本地即时反映，避免整表重拉
    const set = new Set(ids)
    items.value.forEach(p => { if (set.has(p.id)) p.is_priority = value })
    toast.success(`已${value ? '标记' : '取消'} ${r.data.count} 条重点付款`)
  } catch (e) { toast.error(e?.msg || e?.error || '操作失败') }
  finally { markingPriority.value = false }
}
function togglePriorityOne(p) { setPriority([p.id], !p.is_priority) }
function bulkMarkPriority(value) { setPriority([...selectedIds.value], value) }
function togglePriorityFilter() { priorityOnly.value = !priorityOnly.value; filters.page = 1; clearSelection(); load() }
async function clearAllPriority() {
  if (!confirm('清除当前事业部范围内「全部」重点付款标记？')) return
  try {
    const r = await api.post('/payments/mark-priority', { all: true })
    toast.success(`已清除 ${r.data.count} 个重点标记`)
    if (priorityOnly.value) priorityOnly.value = false
    load()
  } catch (e) { toast.error(e?.msg || e?.error || '清除失败') }
}

// ── 批量单号筛选：粘贴多单号（任意分隔）→ 归一化为逗号连接 → 后端 in 命中 ──
const showNumbersBox = ref(false)
const numbersText = ref('')
const parsedNumbers = computed(() =>
  [...new Set(numbersText.value.split(/[\s,+;|，、；／/]+/).map(s => s.trim()).filter(Boolean))])
function applyNumbers() {
  numbersFilter.value = parsedNumbers.value.join(',')
  showNumbersBox.value = false
  filters.page = 1; clearSelection(); load()
}
function clearNumbers() {
  numbersText.value = ''; numbersFilter.value = ''
  showNumbersBox.value = false
  filters.page = 1; clearSelection(); load()
}

// 批量付款（批量编辑）：默认日期=今天，默认金额=各记录剩余应付=计划金额；卡片内可逐条调整金额
const showBatchPay = ref(false)
const batchPayForm = reactive({ pay_date: '' })
const batchPayBusy = ref(false)
const batchPayRows = ref([])   // [{ id, label, remaining, amount }]
const batchPayTotal = computed(() =>
  batchPayRows.value.reduce((s, r) => s + (parseFloat(r.amount) || 0), 0))
const batchPayValid = computed(() => batchPayRows.value.length > 0 &&
  batchPayRows.value.every(r => !payRowError(r)))
// 行内即时校验：返回该行付款金额的错误文案（空 = 合法）
function payRowError(r) {
  if (r.amount === '' || r.amount == null) return '请填写金额'
  const a = parseFloat(r.amount)
  if (isNaN(a)) return '金额格式有误'
  if (a <= 0) return '金额需大于 0'
  if (a > r.remaining + 1e-6) return `超过剩余应付 ${r.remaining.toFixed(2)}`
  return ''
}
const batchPayErrCount = computed(() =>
  batchPayRows.value.filter(r => payRowError(r)).length)
function openBatchPay() {
  batchPayForm.pay_date = todayCST()
  if (isCrossPageSelection.value) {
    // 跨页模式：不展示逐条金额，后端各取剩余应付
    batchPayRows.value = []
  } else {
    if (!batchPaySummary.value.count) { toast.error('所选记录中没有「有剩余应付」的可付款记录（已结清的已自动排除）'); return }
    batchPayRows.value = selectedPayable.value.map(p => {
      const rem = remOf(p)
      return { id: p.id, label: [p.payee, p.project_short_name || p.project_desc].filter(Boolean).join(' · ') || `#${p.id}`,
               remaining: rem, amount: rem }
    })
  }
  showBatchPay.value = true
}
function batchPayResetAll() { batchPayRows.value.forEach(r => { r.amount = r.remaining }) }
async function doBatchPay() {
  if (batchPayBusy.value) return
  if (!isCrossPageSelection.value && !batchPayValid.value) return
  batchPayBusy.value = true
  try {
    let body
    if (isCrossPageSelection.value) {
      body = { ids: [...selectedIds.value], pay_date: batchPayForm.pay_date }
    } else {
      const items = batchPayRows.value.map(r => ({ id: r.id, amount: r.amount }))
      body = { items, pay_date: batchPayForm.pay_date }
    }
    const r = await api.post('/payments/bulk-pay', body)
    showBatchPay.value = false; clearSelection(); load()
    const d = r.data || {}
    let msg = d.message || '批量付款完成'
    if (d.skipped?.length) msg += '\n\n跳过明细：\n' + d.skipped.map(s => `#${s.id} ${s.reason}`).slice(0, 15).join('\n')
    toast.success(msg)
  } catch (e) { toast.error(e?.msg || e?.error || '批量付款失败') }
  finally { batchPayBusy.value = false }
}
</script>

<template>
  <div>
    <div class="topbar">
      <div style="display:flex;align-items:center;gap:14px">
        <h1>付款管理</h1>
        <div class="tab-bar">
          <button :class="['tab-btn', activeTab==='ledger' ? 'active' : '']" @click="switchTab('ledger')">台账</button>
          <button :class="['tab-btn', activeTab==='flow' ? 'active' : '']" @click="switchTab('flow')">付款流水</button>
        </div>
      </div>
      <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
        <button class="btn btn-ghost btn-sm" @click="downloadTemplate" title="下载Excel导入模板">
          <span style="margin-right:4px">⬇</span>模板
        </button>
        <button class="btn btn-ghost btn-sm" :disabled="importing" @click="triggerImport"
                title="导入会自动做规则校验 + AI 智能复核；发现问题时 AI 会介入，协助你就地修正后再导入">
          <span v-if="importing" class="btn-spin"></span>
          <span v-else style="margin-right:4px">📥</span>{{ importing ? '导入中…' : '导入' }}
        </button>
        <button class="btn btn-ghost btn-sm" :disabled="exportingXlsx || bgExporting" @click="exportExcel"
                title="导出当前筛选结果；超过 5000 行自动转后台导出，完成后自动下载">
          <span v-if="exportingXlsx || bgExporting" class="btn-spin"></span>
          <span v-else style="margin-right:4px">📤</span>{{ exportingXlsx ? '导出中…' : (bgExporting ? '后台导出中…' : '导出') }}
        </button>
        <template v-if="canTransport">
          <span class="tp-divider" title="运输事业部对账单专用通道（导入在审批管理）"></span>
          <button class="btn btn-ghost btn-sm tp-btn" :disabled="exportingTransport" @click="exportTransport"
                  :title="selectedCount ? `导出勾选的 ${selectedCount} 条已排款运输付款（已结算行状态列改为已结算，其余原样还原）` : '导出全部已排款运输付款，原表格式零误差还原；已结算行状态列改为已结算'">
            <span v-if="exportingTransport" class="btn-spin"></span>
            <span v-else style="margin-right:4px">🚚</span>{{ exportingTransport ? '导出中…' : (selectedCount ? `运输导出(${selectedCount})` : '运输导出') }}
          </button>
          <button class="btn btn-ghost btn-sm tp-btn" :disabled="copyingG7" @click="copyG7Numbers($event)"
                  :title="(selectedCount ? `复制勾选 ${selectedCount} 条的` : '复制当前筛选全部') + ' 对账单号（= 审批编号），跨页全量；以「+」连接，Shift+点击改用空格连接'">
            <span v-if="copyingG7" class="btn-spin"></span>
            <span v-else style="margin-right:2px">📋</span>{{ copyingG7 ? '复制中…' : '复制单号' }}
          </button>
        </template>
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
    <input ref="importInputRef" type="file" accept=".xlsx,.xls,.csv" style="display:none" @change="onImportFile" />

    <div v-if="activeTab === 'ledger'" class="card fh-fill" style="margin-bottom:16px">
      <div class="filter-bar">
        <input v-model="filters.q" class="global-search" placeholder="🔍 全局搜索：事项 / 收款方 / 单号 / 申请人 / G7…" @keyup.enter="search" />
        <button class="btn btn-ghost btn-sm" @click="search">搜索</button>
        <select v-model="payDeptFilter" @change="search" style="min-width:90px">
          <option value="">全部事业部</option>
          <option v-for="d in deptChoices" :key="d" :value="d">{{ d }}</option>
        </select>
        <label class="filter-toggle" :class="{ active: !hideSettled }" title="切换是否显示已付清记录">
          <input type="checkbox" :checked="!hideSettled" @change="hideSettled = !hideSettled; filters.page=1; clearSelection(); load()" />
          含已付清
        </label>
        <!-- 只看重点 + 清除全部标记 -->
        <button class="filter-toggle prio-toggle" :class="{ active: priorityOnly }" @click="togglePriorityFilter"
                title="只显示标记为重点的付款">★ 只看重点</button>
        <button v-if="priorityOnly" class="btn btn-sm" @click="clearAllPriority" title="清除当前事业部范围内全部重点标记">清除全部标记</button>
        <!-- 批量单号筛选 -->
        <div class="numfilter-wrap">
          <button class="btn btn-ghost btn-sm" :class="{ on: !!numbersFilter }" @click="showNumbersBox = !showNumbersBox"
                  title="粘贴多个单号（空格/换行/+/逗号等任意分隔）批量筛选">
            🔖 批量单号{{ numbersFilter ? `（${parsedNumbers.length || numbersFilter.split(',').length}）` : '' }}
          </button>
          <div v-if="showNumbersBox" class="numfilter-pop">
            <div class="nf-title">粘贴单号批量筛选 <span>对账单号/G7/审批编号，任意分隔符</span></div>
            <textarea v-model="numbersText" class="nf-area" rows="6"
                      placeholder="例如：&#10;ZD202606260055 ZD202606260133&#10;ZD202606260092+ZD202606260134&#10;逗号、空格、换行、+ 都行"></textarea>
            <div class="nf-foot">
              <span class="nf-count">识别 {{ parsedNumbers.length }} 个</span>
              <div style="display:flex;gap:6px">
                <button class="btn btn-sm" @click="clearNumbers">清除</button>
                <button class="btn btn-sm btn-primary" :disabled="!parsedNumbers.length" @click="applyNumbers">应用筛选</button>
              </div>
            </div>
          </div>
        </div>
        <span class="filter-group-lbl">回款日</span>
        <select v-model="payDatePreset" @change="applyPayDatePreset" style="min-width:100px">
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
          <optgroup label="近期">
            <option value="last7">近 7 天</option>
            <option value="last30">近 30 天</option>
            <option value="last90">近 90 天</option>
          </optgroup>
          <option value="custom">自定义…</option>
        </select>
        <template v-if="payDatePreset === 'custom'">
          <input v-model="filters.pay_date_start" type="date" style="min-width:120px" @change="applyPayDateCustom" />
          <span style="color:var(--muted);font-size:12px;flex-shrink:0">~</span>
          <input v-model="filters.pay_date_end" type="date" style="min-width:120px" @change="applyPayDateCustom" />
        </template>
        <span v-else-if="payDatePreset && filters.pay_date_start" class="date-range-hint">
          {{ filters.pay_date_start }} ~ {{ filters.pay_date_end }}
        </span>
        <button v-if="activeFilterCount || filters.q || sortField || extraFilterCount" class="btn btn-sm clear-all-btn" @click="resetFilters">清除全部筛选<span v-if="activeFilterCount + extraFilterCount">（{{ activeFilterCount + extraFilterCount }}）</span></button>
        <SchemePicker :ctl="schemes" :can-public="auth.canCreate" :is-super-admin="auth.isSuperAdmin" />
        <span class="filter-hint" title="点击列名旁 ⏷ 可按列筛选 / 排序" style="cursor:default">?</span>
      </div>

      <EmptyState v-if="loadErr" :error="loadErr" />

      <div v-if="!loadErr" class="table-wrap pk-pay-tbl page-scroll" :ref="rangeSel.setRoot">
        <table>
          <thead>
            <tr>
              <th class="sel-col sticky-col"><input type="checkbox" :checked="pageAllSelected" :indeterminate.prop="hasSelection && !pageAllSelected" title="全选本页" @change="toggleSelectPage" /></th>
              <th v-if="colVisible('department')" :style="cw.thStyle('department')"><ColumnFilter label="部门" field="department" type="enum" :options="deptChoices" :model-value="colFilters.department" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('department',v)" @sort="o=>setSort('department',o)" /></th>
              <th v-if="colVisible('secondary_dept')" style="width:5%"><ColumnFilter label="二级部门" field="secondary_dept" type="text" :model-value="colFilters.secondary_dept" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('secondary_dept',v)" @sort="o=>setSort('secondary_dept',o)" /></th>
              <th v-if="colVisible('project_short_name')" style="width:6%"><ColumnFilter label="项目简称" field="project_short_name" type="text" :model-value="colFilters.project_short_name" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('project_short_name',v)" @sort="o=>setSort('project_short_name',o)" /></th>
              <th v-if="colVisible('applicant')" style="width:4%"><ColumnFilter label="申请人" field="applicant" type="text" :model-value="colFilters.applicant" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('applicant',v)" @sort="o=>setSort('applicant',o)" /></th>
              <th v-if="colVisible('approval_number')" style="width:12%"><ColumnFilter label="审批单号" field="approval_number" type="text" :model-value="colFilters.approval_number" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('approval_number',v)" @sort="o=>setSort('approval_number',o)" /></th>
              <th v-if="colVisible('g7_number')" style="width:8%"><ColumnFilter label="G7编号" field="g7_number" type="text" :model-value="colFilters.g7_number" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('g7_number',v)" @sort="o=>setSort('g7_number',o)" /></th>
              <th v-if="colVisible('project_desc')" :style="cw.thStyle('project_desc')"><ColumnFilter label="付款事项" field="project_desc" type="text" :model-value="colFilters.project_desc" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('project_desc',v)" @sort="o=>setSort('project_desc',o)" /></th>
              <th v-if="colVisible('payee')" style="width:8%"><ColumnFilter label="收款方" field="payee" type="text" :model-value="colFilters.payee" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('payee',v)" @sort="o=>setSort('payee',o)" /></th>
              <th v-if="colVisible('planned_date')" style="width:9%"><ColumnFilter label="计划日期" field="planned_date" type="date" :model-value="colFilters.planned_date" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('planned_date',v)" @sort="o=>setSort('planned_date',o)" /></th>
              <th v-if="colVisible('total_amount')" style="width:8%"><ColumnFilter label="计划额" field="total_amount" type="number" :model-value="colFilters.total_amount" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('total_amount',v)" @sort="o=>setSort('total_amount',o)" /></th>
              <th v-if="colVisible('paid')" style="width:7%"><ColumnFilter label="已付" field="paid" type="number" :model-value="colFilters.paid" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('paid',v)" @sort="o=>setSort('paid',o)" /></th>
              <th v-if="colVisible('remaining')" style="width:6%"><ColumnFilter label="剩余" field="remaining" type="number" :model-value="colFilters.remaining" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('remaining',v)" @sort="o=>setSort('remaining',o)" /></th>
              <th v-if="colVisible('status')" style="width:9%"><ColumnFilter label="状态" field="status" type="enum" :options="PAY_STATUS_OPTS" :no-exclude="true" :sortable="false" :model-value="statusColModel" @update:model-value="setStatusFilter" /></th>
              <th v-if="colVisible('overdue')" style="width:6%"><ColumnFilter label="逾期" field="overdue" type="enum" :options="OVERDUE_OPTS" :sortable="false" :model-value="colFilters.overdue" @update:model-value="v=>setColFilter('overdue',v)" /></th>
              <th v-if="colVisible('plan_adjustment')" style="width:6%"><ColumnFilter label="计划调整" field="plan_adjustment" type="number" :model-value="colFilters.plan_adjustment" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('plan_adjustment',v)" @sort="o=>setSort('plan_adjustment',o)" /></th>
              <th v-if="colVisible('notes')" :style="cw.thStyle('notes')"><ColumnFilter label="备注" field="notes" type="text" :model-value="colFilters.notes" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('notes',v)" @sort="o=>setSort('notes',o)" /></th>
            </tr>
          </thead>
          <tbody>
            <template v-if="loading">
              <SkeletonRow v-for="n in 8" :key="n" :cols="10" />
            </template>
            <tr v-else-if="!items.length" class="empty-row">
              <td :colspan="99" class="empty-cell">
                <EmptyState :variant="activeFilterCount ? 'search' : 'empty'" :text="activeFilterCount ? '没有符合当前筛选条件的付款记录' : '暂无付款记录'" />
              </td>
            </tr>
            <template v-else>
            <template v-for="p in items" :key="p.id">
            <tr :class="{ 'overdue-row': p.status !== 'settled' && p.planned_date && p.planned_date < today, 'row-sel': selectedIds.has(p.id), 'row-priority': p.is_priority }"
                @contextmenu.prevent="ctx.open($event, p)" @dblclick="onRowDblClick(p, $event)">
              <td class="sel-col"><input type="checkbox" :checked="selectedIds.has(p.id)" @change="toggleRow(p.id)" /></td>
              <td v-if="colVisible('department')" class="cell-clip" :title="p.department">{{ p.department }}</td>
              <td v-if="colVisible('secondary_dept')" class="cell-clip" :title="p.secondary_dept">{{ p.secondary_dept || '—' }}</td>
              <td v-if="colVisible('project_short_name')" class="cell-clip" :title="p.project_short_name">{{ p.project_short_name || '—' }}</td>
              <td v-if="colVisible('applicant')" class="cell-clip" :title="p.applicant">{{ p.applicant || '—' }}</td>
              <td v-if="colVisible('approval_number')" class="cell-clip" :title="p.approval_number">{{ p.approval_number || '—' }}</td>
              <td v-if="colVisible('g7_number')" class="cell-clip cell-muted" :title="p.g7_number">{{ p.g7_number || '—' }}</td>
              <td v-if="colVisible('project_desc')" class="cell-clip cell-desc"
                @mouseenter="showTip($event, p.project_desc)" @mousemove="moveTip" @mouseleave="hideTip">
                <span v-if="p.project_no" class="proj-no">{{ p.project_no }}</span>{{ p.project_desc }}
              </td>
              <td v-if="colVisible('payee')" class="cell-clip cell-payee"
                @mouseenter="showTip($event, p.payee)" @mousemove="moveTip" @mouseleave="hideTip">
                {{ p.payee }}
              </td>
              <td v-if="colVisible('planned_date')" class="plan-cell" title="点击展开 计划明细 / 付款明细" @click="toggleRowDetail(p.id)">
                {{ p.planned_date }}
                <span v-if="p.plan_count > 1" class="plan-badge">×{{ p.plan_count }}批</span>
                <span class="plan-caret">{{ expandedRows.has(p.id) ? '▲' : '▼' }}</span>
              </td>
              <td v-if="colVisible('total_amount')" class="amt" :title="dash(p.total_amount)">{{ dash(p.total_amount) }}</td>
              <td v-if="colVisible('paid')" class="amt amt-green" :title="dash(p.total_paid)">{{ dash(p.total_paid) }}</td>
              <td v-if="colVisible('remaining')" class="amt" :class="parseFloat(p.remaining) > 0 ? 'amt-red' : ''" :title="dash(p.remaining)">{{ dash(p.remaining) }}</td>
              <td v-if="colVisible('status')" class="status-cell">
                <span class="status-wrap">
                  <button class="prio-star" :class="{ on: p.is_priority }" @click.stop="togglePriorityOne(p)"
                          :title="p.is_priority ? '重点付款（点击取消标记）' : '标记为重点付款'">★</button>
                  <StatusBadge :status="p.status" />
                </span>
              </td>
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
              <td v-if="colVisible('notes')" class="cell-clip" :title="p.notes"
                  @mouseenter="showTip($event, p.notes)" @mousemove="moveTip" @mouseleave="hideTip">{{ p.notes || '—' }}</td>
            </tr>
            <!-- 行明细：计划明细（分批）/ 付款明细（分期实付）并排 -->
            <tr v-if="expandedRows.has(p.id)" class="pp-detail-row" data-skiprange>
              <td :colspan="99">
                <div class="pp-detail">
                  <div class="ppd-col">
                    <div class="ppd-head plan">计划明细 · {{ p.plan_count || 0 }} 批<i>排款管理：编辑/撤销/追加，均与来源审批已排款同步</i></div>
                    <div v-if="!p.plan_items?.length" class="ppd-empty">无计划明细</div>
                    <template v-for="pi in p.plan_items" :key="pi.id">
                      <!-- 编辑态 -->
                      <div v-if="planEdit.id === pi.id" class="ppd-item editing">
                        <span class="ppd-seq">第{{ pi.seq }}批</span>
                        <input v-model="planEdit.planned_date" type="date" class="ppd-edit-date" />
                        <input v-model="planEdit.amount" type="number" step="0.01" class="ppd-edit-amt" placeholder="金额" />
                        <input v-model="planEdit.notes" type="text" class="ppd-edit-note" placeholder="备注" />
                        <button class="ppd-save" :disabled="planEdit.busy" @click="saveEditPlan(p, pi)">保存</button>
                        <button class="ppd-cancel" :disabled="planEdit.busy" @click="cancelEditPlan">取消</button>
                      </div>
                      <!-- 展示态 -->
                      <div v-else class="ppd-item">
                        <span class="ppd-seq">第{{ pi.seq }}批</span>
                        <span class="ppd-date">{{ pi.planned_date }}</span>
                        <b class="ppd-amt plan">{{ fmt(pi.amount) }}</b>
                        <span class="ppd-note">{{ pi.notes }}</span>
                        <button v-if="auth.canWrite && !isRowEditing(p)" class="ppd-edit-btn"
                          title="编辑该批计划（审批已排款同步）" @click="startEditPlan(pi)">编辑</button>
                        <button v-if="auth.canWrite && p.plan_items.length > 1 && !isRowEditing(p)" class="ppd-del"
                          title="撤销该批计划（审批已排款同步回退）" @click="removePlanItem(p, pi)">撤销</button>
                      </div>
                    </template>
                    <!-- 追加批次态 -->
                    <div v-if="planEdit.id === `new:${p.id}`" class="ppd-item editing">
                      <span class="ppd-seq">追加</span>
                      <input v-model="planEdit.planned_date" type="date" class="ppd-edit-date" />
                      <input v-model="planEdit.amount" type="number" step="0.01" class="ppd-edit-amt" placeholder="金额" />
                      <input v-model="planEdit.notes" type="text" class="ppd-edit-note" placeholder="备注" />
                      <button class="ppd-save" :disabled="planEdit.busy" @click="saveAddPlan(p)">保存</button>
                      <button class="ppd-cancel" :disabled="planEdit.busy" @click="cancelEditPlan">取消</button>
                    </div>
                    <button v-if="auth.canWrite && !isRowEditing(p)" class="ppd-add" @click="startAddPlan(p)">+ 追加计划批次</button>
                  </div>
                  <div class="ppd-col">
                    <div class="ppd-head paid">付款明细 · {{ p.installments?.length || 0 }} 笔<i>实际付款分期</i></div>
                    <div v-if="!p.installments?.length" class="ppd-empty">尚无实付记录</div>
                    <div v-for="i in p.installments" :key="i.id" class="ppd-item">
                      <span class="ppd-seq">第{{ i.seq }}次</span>
                      <span class="ppd-date">{{ i.pay_date }}</span>
                      <b class="ppd-amt paid">{{ fmt(i.pay_amount) }}</b>
                      <span class="ppd-note">{{ i.notes }}</span>
                    </div>
                  </div>
                </div>
              </td>
            </tr>
            </template>
            </template>
          </tbody>
        </table>
      </div>

      <!-- 浮动批量操作条：Teleport 到 body 固定在视口底部，全选后无需下拉即可操作 -->
      <Teleport to="body">
        <div v-if="!loading && items.length && hasSelection && !showBatchPay && !showDelConfirm && (auth.canDelete || auth.canEdit('installments'))" class="bulk-bar">
          <span class="bulk-n">已选 <strong>{{ selectedCount }}</strong> 条</span>
          <button v-if="selectedCount < total" class="bulk-selall" :disabled="selectingAll" @click="selectAllFiltered"
                  :title="`跨页选中当前筛选下全部 ${total} 条（上限 5000，供批量操作）`">{{ selectingAll ? '全选中…' : `选择全部 ${total} 条` }}</button>
          <button v-if="auth.canEdit('installments')" class="bulk-act" :disabled="!isCrossPageSelection && !batchPaySummary.count" @click="openBatchPay">{{ isCrossPageSelection ? `批量付款（${selectedCount} 条）` : `批量付款（可付 ${batchPaySummary.count} 条）` }}</button>
          <button class="bulk-star" :disabled="markingPriority" @click="bulkMarkPriority(true)" title="标记为重点付款">★ 标记重点</button>
          <button class="bulk-star-off" :disabled="markingPriority" @click="bulkMarkPriority(false)" title="取消重点标记">取消重点</button>
          <button v-if="auth.canDelete" class="bulk-return" :disabled="bulkReturning" @click="bulkReturn" title="退回排款（来源审批已排款归零，可重新排款）">{{ bulkReturning ? '退回中…' : `批量退回(${selectedCount})` }}</button>
          <button v-if="auth.canDelete" class="bulk-del" :disabled="bulkDeleting" @click="bulkDelete">{{ bulkDeleting ? '删除中…' : `批量删除(${selectedCount})` }}</button>
          <button v-if="canTransport" class="bulk-act" :disabled="copyingG7" @click="copyG7Numbers($event)"
                  title="复制所选记录的 对账单号（审批编号），「+」连接；Shift+点击改用空格连接">📋 复制单号</button>
          <button class="bulk-cancel" @click="clearSelection">取消</button>
        </div>
      </Teleport>

      <!-- 吸底合计 + 翻页：Teleport 到 body 以逃脱 .card transform 产生的 fixed 包含块 -->
      <Teleport to="body">
        <div v-if="!loading && items.length && !hasSelection && !showModal && !showBatchPay && !showDelConfirm" class="bottom-bar">
          <div class="bb-summary">
            <span class="bb-item"><i>合计</i><b>{{ total }}</b> 条</span>
            <span v-if="auth.canView('total_amount')" class="bb-item"><i>计划总额</i><b>{{ fmt(plannedTotal) }}</b></span>
            <span v-if="showPaid" class="bb-item ok"><i>已付</i><b>{{ fmt(paidTotal) }}</b></span>
            <span v-if="showRemaining" class="bb-item warn"><i>未结清</i><b>{{ fmt(outstandingTotal) }}</b>（{{ outstandingCount }} 笔）</span>
          </div>
          <div v-if="total > filters.size" class="bb-pager">
            <button :disabled="filters.page <= 1" class="page-btn" @click="setPage(filters.page - 1)">‹ 上一页</button>
            <span class="page-info">{{ filters.page }} / {{ totalPages }} 页 · 共 {{ total }} 条</span>
            <button :disabled="filters.page * filters.size >= total" class="page-btn" @click="setPage(filters.page + 1)">下一页 ›</button>
            <span class="pg-jump">到第<input type="number" v-model.number="jumpPage" :min="1" :max="totalPages" class="pg-jump-input" :placeholder="`1-${totalPages}`" @keyup.enter="doJump" />页</span>
          </div>
        </div>
      </Teleport>
    </div>

    <!-- ══ 付款流水 Tab ══ -->
    <div v-if="activeTab === 'flow'" class="card fh-fill" style="margin-bottom:16px">
      <div class="filter-bar" style="flex-wrap:wrap;gap:8px;margin-bottom:12px">
        <input v-model="flowFilters.q" placeholder="搜索事项/收款方/单号…" style="min-width:180px" @keyup.enter="searchFlow" />
        <input v-model="flowFilters.g7_number" placeholder="G7编号" style="width:120px" @keyup.enter="searchFlow" />
        <select v-model="flowFilters.dept" @change="searchFlow">
          <option value="">全部部门</option>
          <option v-for="d in deptChoices" :key="d" :value="d">{{ d }}</option>
        </select>
        <span class="filter-group-lbl">付款日</span>
        <select v-model="flowDatePreset" @change="applyFlowDatePreset" style="min-width:100px">
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
          <optgroup label="近期">
            <option value="last7">近 7 天</option>
            <option value="last30">近 30 天</option>
            <option value="last90">近 90 天</option>
          </optgroup>
          <option value="custom">自定义…</option>
        </select>
        <template v-if="flowDatePreset === 'custom'">
          <input v-model="flowFilters.pay_date_start" type="date" style="min-width:120px" @change="searchFlow" />
          <span style="color:var(--muted);font-size:12px;flex-shrink:0">~</span>
          <input v-model="flowFilters.pay_date_end" type="date" style="min-width:120px" @change="searchFlow" />
        </template>
        <span v-else-if="flowDatePreset && flowFilters.pay_date_start" class="date-range-hint">
          {{ flowFilters.pay_date_start }} ~ {{ flowFilters.pay_date_end }}
        </span>
        <button class="btn btn-ghost btn-sm" @click="searchFlow">筛选</button>
        <button class="btn btn-sm" style="background:var(--bg2);border:none" @click="resetFlowFilters">重置</button>
      </div>
      <EmptyState v-if="flowLoading" loading />
      <EmptyState v-else-if="!flowItems.length" empty text="暂无付款流水" />
      <div v-else class="table-wrap page-scroll">
        <table class="flow-tbl">
          <thead>
            <tr>
              <th style="width:6%">部门</th>
              <th style="width:8%">项目简称</th>
              <th>付款事项</th>
              <th style="width:10%">收款方</th>
              <th style="width:10%">审批单号</th>
              <th style="width:8%">G7编号</th>
              <th style="width:7%">计划日期</th>
              <th style="width:7%">付款日期</th>
              <th style="width:8%">付款金额</th>
              <th style="width:12%">备注</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="inst in flowItems" :key="inst.id" class="flow-row">
              <td>{{ inst.department }}</td>
              <td class="cell-clip" :title="inst.project_short_name">{{ inst.project_short_name || '—' }}</td>
              <td class="cell-clip">
                <span v-if="inst.project_short_name" class="proj-no">{{ inst.project_short_name }}</span>
                {{ inst.project_desc }}
              </td>
              <td class="cell-clip" :title="inst.payee">{{ inst.payee }}</td>
              <td style="font-size:11.5px;color:var(--muted)">{{ inst.approval_number || '—' }}</td>
              <td style="font-size:11.5px;color:var(--muted)">{{ inst.g7_number || '—' }}</td>
              <td>{{ inst.planned_date || '—' }}</td>
              <td style="font-weight:600;color:#1565c0">{{ inst.pay_date }}</td>
              <td class="amt amt-green">{{ inst.pay_amount != null ? fmt(inst.pay_amount) : '—' }}</td>
              <td class="cell-clip" style="color:var(--muted);font-size:11.5px">{{ inst.notes || '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <Teleport to="body">
        <div v-if="!flowLoading && flowItems.length" class="bottom-bar">
          <div class="bb-summary">
            <span class="bb-item"><i>合计</i><b>{{ flowTotal }}</b> 笔</span>
            <span v-if="auth.canView('total_amount') && flowTotalAmount" class="bb-item ok"><i>付款总额</i><b>{{ fmt(flowTotalAmount) }}</b></span>
          </div>
          <div v-if="flowTotal > 50" class="bb-pager">
            <button :disabled="flowPage <= 1" class="page-btn" @click="flowPage--; loadFlow()">‹ 上一页</button>
            <span class="page-info">{{ flowPage }} / {{ Math.ceil(flowTotal / 50) || 1 }} 页 · 共 {{ flowTotal }} 笔</span>
            <button :disabled="flowPage * 50 >= flowTotal" class="page-btn" @click="flowPage++; loadFlow()">下一页 ›</button>
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
              <button v-if="auth.canAction('wo_prepaid')" class="po-reverse" :disabled="offsetBusy"
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
    <ImportResultModal :result="importResult" @close="importResult = null" />

    <!-- AI 导入预检 -->
    <ImportPrecheckModal :report="precheckResult" :busy="precheckBusy"
      @close="precheckResult = null" @apply="onPrecheckApply" />

    <!-- 右键上下文菜单 -->
    <ContextMenu :ctx="ctx" :items="ctxItems" />

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

    <!-- 批量付款（批量编辑）：点击卡片外部不关闭 -->
    <Teleport to="body">
      <div v-if="showBatchPay" class="overlay">
        <div class="modal" style="width:520px">
          <div class="modal-header"><h3>批量付款</h3><button class="modal-close" @click="showBatchPay = false">×</button></div>
          <div style="padding:4px 2px 0">
            <template v-if="isCrossPageSelection">
              <div class="batch-summary">
                <span>已选记录 <b>{{ selectedCount }}</b> 条（无剩余应付的自动跳过）</span>
              </div>
              <p style="font-size:12px;color:var(--muted);margin:10px 0 12px">
                跨页批量付款：各记录按各自「剩余应付（=计划金额 − 已付 − 预付冲抵）」登记付款明细，已结清（无剩余）的记录自动跳过。
              </p>
            </template>
            <template v-else>
              <div class="batch-summary">
                <span>可付记录 <b>{{ batchPayRows.length }}</b> 条</span>
                <span>合计金额 <b style="color:#2e7d32">{{ batchPayTotal.toFixed(2) }}</b> 元</span>
              </div>
              <p style="font-size:12px;color:var(--muted);margin:10px 0 12px">
                默认按各记录「剩余应付（=计划金额 − 已付 − 预付冲抵）」各登记一笔付款明细，可逐条调小做分次付款（不得超过剩余应付）；已结清（无剩余）的记录已自动排除。
              </p>
            </template>
            <label class="batch-field" style="margin-bottom:10px"><span>付款日期*</span><input v-model="batchPayForm.pay_date" type="date" /></label>
            <template v-if="!isCrossPageSelection">
              <div class="batch-rows-head">
                <span>本次付款金额（共 {{ batchPayRows.length }} 条）</span>
                <button type="button" class="batch-reset" @click="batchPayResetAll">全部设为剩余应付</button>
              </div>
              <div v-if="batchPayErrCount" class="batch-err-banner">
                ⚠ {{ batchPayErrCount }} 行金额有误，请修正后再提交
              </div>
              <div class="batch-rows">
                <div v-for="r in batchPayRows" :key="r.id" class="batch-row" :class="{ 'row-bad': payRowError(r) }">
                  <span class="batch-row-label" :title="r.label">{{ r.label }}</span>
                  <span class="batch-row-rem">剩余 {{ r.remaining.toFixed(2) }}</span>
                  <div class="batch-amt-wrap">
                    <input v-model="r.amount" type="number" step="0.01" min="0" :max="r.remaining"
                           class="batch-row-amt" :class="{ bad: !!payRowError(r) }"/>
                    <span v-if="payRowError(r)" class="batch-row-err">{{ payRowError(r) }}</span>
                  </div>
                </div>
              </div>
            </template>
          </div>
          <div style="display:flex;justify-content:flex-end;gap:8px;margin-top:14px">
            <button class="btn btn-ghost" @click="showBatchPay = false">取消</button>
            <button class="btn btn-primary" :disabled="batchPayBusy || (!isCrossPageSelection && !batchPayValid)" @click="doBatchPay">{{ batchPayBusy ? '付款中…' : (isCrossPageSelection ? `确认付款 ${selectedCount} 条` : `确认付款 ${batchPayRows.length} 条`) }}</button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- 批量删除二次确认 -->
    <Teleport to="body">
      <div v-if="showDelConfirm" class="overlay">
        <div class="modal" style="width:420px">
          <div class="modal-header"><h3>确认删除 {{ delConfirmCount }} 条排款</h3><button class="modal-close" @click="showDelConfirm = false">×</button></div>
          <div style="padding:4px 2px 0">
            <p class="del-warn">⚠ 删除后不可恢复；已关联预付核销的记录将自动跳过。</p>
            <p class="del-tip">请输入待删条数 <strong>{{ delConfirmCount }}</strong> 以确认：</p>
            <input v-model="delConfirmText" class="del-input" :placeholder="`输入 ${delConfirmCount}`" @keyup.enter="confirmBulkDelete" />
          </div>
          <div style="display:flex;justify-content:flex-end;gap:8px;margin-top:14px">
            <button class="btn btn-ghost" @click="showDelConfirm = false">取消</button>
            <button class="btn-danger-solid" :disabled="!delConfirmOk || bulkDeleting" @click="confirmBulkDelete">{{ bulkDeleting ? '删除中…' : '确认删除' }}</button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
/* 运输事业部专用通道：分隔符 + 按钮强调色（与普通导入导出区分）*/
.tp-divider { width: 1px; height: 18px; background: var(--border); margin: 0 2px; display: inline-block; }
.tp-btn { border-color: rgba(201,99,66,0.4); color: var(--primary); }
.tp-btn:hover:not(:disabled) { background: rgba(201,99,66,0.08); border-color: var(--primary); }

/* Tab bar */
.tab-bar { display: flex; gap: 2px; background: rgba(0,0,0,0.05); border-radius: 10px; padding: 3px; }
.tab-btn { border: none; background: none; padding: 5px 14px; border-radius: 8px; font-size: 13px; font-weight: 600; color: var(--muted); cursor: pointer; transition: none; }
.tab-btn.active { background: #fff; color: var(--text); box-shadow: 0 1px 4px rgba(0,0,0,0.12); }

/* 付款日期 label in filter bar */
.filter-group-lbl { font-size: 11.5px; font-weight: 600; color: var(--muted); white-space: nowrap; flex-shrink: 0; }

/* 含已付清 toggle */
.filter-toggle {
  display: inline-flex; align-items: center; gap: 4px; padding: 4px 10px;
  border: 1px solid var(--border); border-radius: 8px; font-size: 12px;
  color: var(--muted); cursor: pointer; white-space: nowrap; flex-shrink: 0;
  background: transparent; user-select: none;
}
.filter-toggle input { margin: 0; cursor: pointer; }
.filter-toggle.active { border-color: var(--primary); color: var(--primary); }

/* 付款流水 table */
.flow-tbl { width: 100%; table-layout: fixed; }
.flow-tbl th, .flow-tbl td { padding: 8px 8px; font-size: 12.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.flow-row:hover { background: rgba(21,101,192,0.03); }

.date-range-hint {
  font-size: 11.5px; color: var(--muted); white-space: nowrap; flex-shrink: 0;
  padding: 4px 8px; background: rgba(201,99,66,0.06); border-radius: 7px;
  border: 1px solid rgba(201,99,66,0.18);
}

/* 固定视口布局：卡片在底部为吸底合计条预留空间，表头随滚动吸顶 */
.card.fh-fill { padding-bottom: 40px; }
.table-wrap.page-scroll thead th { position: sticky; top: 0; z-index: 5; background: #f4f1ef; }

/* 付款管理：固定布局，不超出卡片宽度（table-layout:fixed 已防横向溢出，无需 overflow-x:hidden） */
.table-wrap.pk-pay-tbl { padding-bottom: 70px; }
.pk-pay-tbl table { table-layout: fixed; }
/* 列多、字段密：本表用更紧凑的字号/横向内边距，尽量让各列内容完整展示 */
.pk-pay-tbl { --td-fs: 12px; --td-px: 6px; }
.pk-pay-tbl th, .pk-pay-tbl td { padding: var(--td-py) var(--td-px); font-size: var(--td-fs); }
.pk-pay-tbl td:not(.ops-cell) { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 0; }
/* 空状态整行：跨列居中，取消定宽/裁剪，表头留在顶部、提示紧贴其下（不再把表头挤到页面中间） */
.pk-pay-tbl td.empty-cell { max-width: none; overflow: visible; white-space: normal; text-align: center; padding: 20px 8px; }
/* Excel 式区域选择高亮（useRangeSelection 直接给 td 加类） */
.pk-pay-tbl td.cell-range-sel { background: rgba(21,101,192,0.14) !important; box-shadow: inset 0 0 0 1px rgba(21,101,192,0.28); }
.pk-pay-tbl tbody { user-select: none; }
/* 列头：字段名完整展示，空间不足时换行成两行（不挤压、不截断），漏斗不裁切 */
.pk-pay-tbl thead th {
  overflow: visible; white-space: normal; vertical-align: middle;
  line-height: 1.25; padding-top: 5px; padding-bottom: 5px;
  font-size: 12px; letter-spacing: -0.2px;
}
.pk-pay-tbl thead :deep(.colf) { align-items: center; }
/* 换行时两行字数尽量均衡，避免头重脚轻 */
.pk-pay-tbl thead :deep(.colf-label) { white-space: normal; text-wrap: balance; }
.global-search { min-width: 300px; flex: 0 1 380px; }
.clear-all-btn { background: var(--bg2); border: none; color: var(--primary); }
.filter-hint { font-size: 11.5px; color: var(--muted); margin-left: auto; white-space: nowrap; }
/* 操作列：不裁剪，按钮正常显示，更紧凑 */
.pk-pay-tbl .ops-cell { white-space: nowrap; text-align: center; }
.pk-pay-tbl .ops-cell .btn-sm { padding: 3px 7px; font-size: 11px; border-radius: 6px; }
.pk-pay-tbl .badge { font-size: 10.5px; padding: 2px 7px; }

/* 计划/付款明细展开行 */
.plan-cell { cursor: pointer; white-space: nowrap; }
.plan-cell:hover { color: var(--primary); }
.plan-badge { font-size: 10px; font-weight: 700; color: #1565c0; background: rgba(21,101,192,.1);
  border-radius: 5px; padding: 0 5px; margin-left: 3px; }
.plan-caret { font-size: 9px; color: var(--muted); margin-left: 2px; }
.pp-detail-row td { background: rgba(250,246,241,.75); padding: 8px 14px !important;
  overflow: visible !important; white-space: normal !important; max-width: none !important; }
.pp-detail { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
@media (max-width: 860px) { .pp-detail { grid-template-columns: 1fr; } }
.ppd-col { background: #fff; border: 1px solid rgba(180,140,110,.16); border-radius: 9px; padding: 6px 12px; }
.ppd-head { font-size: 11.5px; font-weight: 700; margin-bottom: 3px; }
.ppd-head.plan { color: #1565c0; } .ppd-head.paid { color: #2e7d32; }
.ppd-head i { font-style: normal; font-weight: 400; font-size: 10.5px; color: var(--muted); margin-left: 8px; }
.ppd-empty { font-size: 12px; color: var(--muted); padding: 3px 0; }
.ppd-item { display: flex; align-items: center; gap: 10px; font-size: 12.5px; padding: 3px 0;
  border-top: 1px dashed rgba(180,140,110,.12); }
.ppd-item:first-of-type { border-top: none; }
.ppd-seq { font-size: 11px; color: var(--muted); min-width: 44px; }
.ppd-date { color: var(--text); font-variant-numeric: tabular-nums; min-width: 84px; }
.ppd-amt { font-variant-numeric: tabular-nums; min-width: 90px; text-align: right; }
.ppd-amt.plan { color: #1565c0; } .ppd-amt.paid { color: #2e7d32; }
.ppd-note { flex: 1; font-size: 11px; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ppd-del { border: 1px solid rgba(198,40,40,.4); color: #c62828; background: none; border-radius: 6px;
  padding: 1px 8px; font-size: 11px; cursor: pointer; white-space: nowrap; }
.ppd-del:hover { background: rgba(198,40,40,.08); }
/* 排款管理：编辑/追加批次 */
.ppd-edit-btn { border: 1px solid rgba(21,101,192,.4); color: #1565c0; background: none; border-radius: 6px;
  padding: 1px 8px; font-size: 11px; cursor: pointer; white-space: nowrap; }
.ppd-edit-btn:hover { background: rgba(21,101,192,.08); }
.ppd-item.editing { gap: 6px; flex-wrap: wrap; }
.ppd-edit-date, .ppd-edit-amt, .ppd-edit-note {
  border: 1px solid var(--border-strong); border-radius: 6px; padding: 2px 6px; font-size: 12px;
  background: var(--surface-1); color: var(--text); }
.ppd-edit-date { width: 130px; } .ppd-edit-amt { width: 96px; text-align: right; } .ppd-edit-note { flex: 1; min-width: 90px; }
.ppd-save { border: 1px solid var(--primary); background: var(--primary); color: #fff; border-radius: 6px;
  padding: 1px 10px; font-size: 11px; cursor: pointer; white-space: nowrap; }
.ppd-save:disabled { opacity: .55; cursor: not-allowed; }
.ppd-cancel { border: 1px solid var(--border-strong); background: none; color: var(--text-2); border-radius: 6px;
  padding: 1px 8px; font-size: 11px; cursor: pointer; white-space: nowrap; }
.ppd-add { margin-top: 5px; border: 1px dashed rgba(21,101,192,.45); color: #1565c0; background: none;
  border-radius: 6px; padding: 2px 10px; font-size: 11px; cursor: pointer; }
.ppd-add:hover { background: rgba(21,101,192,.06); }

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

/* 多选列 + 批量操作条 + 删除二次确认 */
.pk-pay-tbl th.sel-col, .pk-pay-tbl td.sel-col { width: 30px; text-align: center; padding: 9px 4px; max-width: none; overflow: visible; }
.pk-pay-tbl td.sel-col input, .pk-pay-tbl th.sel-col input { cursor: pointer; }
.pk-pay-tbl tr.row-sel td { background: rgba(201,99,66,0.06); }
/* 批量操作条：固定浮动在视口底部居中，全选后无需下拉即可操作 */
.bulk-bar { position: fixed; left: 50%; bottom: 22px; transform: translateX(-50%); z-index: 1200;
  display: flex; align-items: center; gap: 12px; padding: 10px 18px;
  border-radius: 12px; background: var(--card); border: 1px solid rgba(198,40,40,0.35);
  box-shadow: 0 8px 28px rgba(0,0,0,0.18); }
.bulk-n { font-size: 13px; color: var(--text); }
.bulk-selall { border: 1px solid var(--primary); background: rgba(201,99,66,0.08); color: var(--primary); border-radius: 8px; padding: 5px 12px; font-size: 12.5px; font-weight: 700; cursor: pointer; }
.bulk-selall:disabled { opacity: .5; cursor: default; }
.bulk-act { margin-left: auto; border: none; border-radius: 8px; padding: 6px 14px; font-size: 13px; font-weight: 700; cursor: pointer; background: var(--primary); color: #fff; }
.bulk-act:disabled { opacity: .5; cursor: default; }
.bulk-del { border: none; border-radius: 8px; padding: 6px 14px; font-size: 13px; font-weight: 700; cursor: pointer; background: var(--danger); color: #fff; }
.bulk-del:disabled { opacity: .6; cursor: default; }
/* 批量退回（橙）/ 标记重点（金）/ 取消重点（描边）*/
.bulk-return { border: none; border-radius: 8px; padding: 6px 14px; font-size: 13px; font-weight: 700; cursor: pointer; background: var(--c-warn); color: #fff; }
.bulk-return:disabled { opacity: .6; cursor: default; }
.bulk-star { border: none; border-radius: 8px; padding: 6px 12px; font-size: 13px; font-weight: 700; cursor: pointer; background: #f5a623; color: #fff; }
.bulk-star-off { border: 1px solid var(--border); border-radius: 8px; padding: 6px 12px; font-size: 13px; font-weight: 600; cursor: pointer; background: #fff; color: var(--muted); }
.bulk-star:disabled, .bulk-star-off:disabled { opacity: .5; cursor: default; }

/* 重点付款：状态列内嵌星标（不占独立列）+ 行金色左缘 */
/* 状态列：td 保持 table-cell（垂直对齐/列宽不破），flex 收进内层 wrapper */
.status-cell { white-space: nowrap; }
.status-wrap { display: inline-flex; align-items: center; gap: 6px; }
.prio-star { border: none; background: none; cursor: pointer; font-size: 14px; line-height: 1; padding: 0;
  color: #d9cfc2; transition: color .12s, transform .12s; flex-shrink: 0; }
.prio-star:hover { color: #f5a623; transform: scale(1.18); }
.prio-star.on { color: #f5a623; text-shadow: 0 0 6px rgba(245,166,35,.5); }
.row-priority td { background: rgba(245,166,35,0.06) !important; }
.row-priority td:first-child { box-shadow: inset 3px 0 0 #f5a623; }
.prio-toggle.active { border-color: #f5a623; color: #b8761a; background: rgba(245,166,35,0.12); }

/* 批量单号筛选弹层 */
.numfilter-wrap { position: relative; }
.numfilter-wrap .on { border-color: var(--primary); color: var(--primary); background: rgba(201,99,66,0.07); }
.numfilter-pop { position: absolute; top: calc(100% + 6px); left: 0; z-index: 60; width: 320px;
  background: var(--surface-2); border: 1px solid var(--border); border-radius: 12px; box-shadow: var(--shadow-lg); padding: 12px; }
.nf-title { font-size: 12.5px; font-weight: 700; color: var(--text); margin-bottom: 8px; }
.nf-title span { font-weight: 400; color: var(--muted); font-size: 11px; }
.nf-area { width: 100%; box-sizing: border-box; border: 1px solid var(--border); border-radius: 8px; padding: 8px;
  font-size: 12.5px; font-family: ui-monospace, Menlo, monospace; resize: vertical; }
.nf-area:focus { outline: none; border-color: var(--primary); }
.nf-foot { display: flex; align-items: center; justify-content: space-between; margin-top: 8px; }
.nf-count { font-size: 12px; color: var(--muted); }
.bulk-cancel { border: none; background: none; color: var(--muted); font-size: 12.5px; cursor: pointer; }
.batch-summary { display: flex; gap: 18px; font-size: 13px; color: var(--muted);
  background: rgba(201,99,66,.05); border-radius: 9px; padding: 10px 12px; }
.batch-summary b { font-variant-numeric: tabular-nums; color: var(--text); }
.batch-field { display: flex; flex-direction: column; gap: 5px; font-size: 13px; }
.batch-field span { color: var(--muted); }
.batch-field input { padding: 7px 10px; border: 1.5px solid var(--border); border-radius: 8px; font-size: 14px; }
.batch-rows-head { display: flex; align-items: center; justify-content: space-between;
  font-size: 12px; color: var(--muted); margin: 0 0 6px; }
.batch-reset { border: none; background: none; color: var(--primary); font-size: 12px; cursor: pointer; padding: 0; }
.batch-rows { max-height: 42vh; overflow-y: auto; border: 1px solid var(--border); border-radius: 9px; }
.batch-row { display: flex; align-items: center; gap: 10px; padding: 7px 10px; border-bottom: 1px solid var(--border); }
.batch-row:last-child { border-bottom: none; }
.batch-row-label { flex: 1; min-width: 0; font-size: 12.5px; color: var(--text);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.batch-row-rem { font-size: 11.5px; color: var(--muted); font-variant-numeric: tabular-nums; white-space: nowrap; }
.batch-row-amt { width: 120px; height: 30px; padding: 0 8px; border: 1.5px solid var(--border);
  border-radius: 7px; font-size: 13px; text-align: right; font-variant-numeric: tabular-nums; box-sizing: border-box; }
.batch-row-amt:focus { border-color: var(--primary); outline: none; }
.batch-row-amt.bad { border-color: var(--danger); background: rgba(198,40,40,0.05); }
.batch-row.row-bad { background: rgba(198,40,40,0.035); }
.batch-amt-wrap { display: flex; flex-direction: column; align-items: flex-end; gap: 1px; }
.batch-row-err { font-size: 10.5px; color: var(--danger); white-space: nowrap; line-height: 1.2; }
.batch-err-banner { font-size: 12px; color: var(--danger); background: rgba(198,40,40,0.07);
  border: 1px solid rgba(198,40,40,0.22); border-radius: 7px; padding: 6px 10px; margin-bottom: 8px; }
.del-warn { font-size: 13px; color: var(--danger); margin: 0 0 12px; line-height: 1.6; }
.del-tip { font-size: 13px; color: var(--text); margin: 0 0 8px; }
.del-input { width: 100%; padding: 8px 12px; border: 1.5px solid var(--border); border-radius: 8px; font-size: 14px; box-sizing: border-box; }
.del-input:focus { border-color: var(--danger); outline: none; }
.btn-danger-solid { border: none; border-radius: 8px; padding: 8px 18px; font-size: 14px; font-weight: 700; cursor: pointer; background: var(--danger); color: #fff; }
.btn-danger-solid:disabled { opacity: .5; cursor: default; }

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
/* 统一弱化色列（G7编号等），字号随全表 --td-fs，不再单独缩小，保证字体统一 */
.cell-muted { color: var(--muted); }
/* 金额列：右对齐 + 等宽数字，数值完整展示、位数对齐；超长仍可 hover(title) 查看 */
.pk-pay-tbl td.amt { text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }
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

/* import result popup → 见 components/ImportResultModal.vue */
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

.pg-jump { display: inline-flex; align-items: center; gap: 4px; font-size: 13px; color: var(--muted); margin-left: 8px; }
.pg-jump-input { width: 46px; text-align: center; padding: 2px 4px; border: 1px solid var(--border); border-radius: 6px; font-size: 13px; }

/* 列宽拖拽柄 + 冻结列 */
.pk-pay-tbl table th { position: relative; }
.col-rh {
  position: absolute; right: 0; top: 0; bottom: 0; width: 5px;
  cursor: col-resize; opacity: 0; transition: opacity 0.15s;
}
.col-rh:hover, .col-rh:active { opacity: 1; background: rgba(201,99,66,0.4); }
.pk-pay-tbl table th:hover .col-rh { opacity: 0.35; }
.sticky-col { position: sticky; left: 0; z-index: 3; background: #f8f4f0; }
.pk-pay-tbl table thead th.sticky-col { z-index: 6; background: #f8f4f0; }
.pk-pay-tbl table tbody td.sticky-col { background: #fff; }
/* 冻结首列悬停 / 选中态用实色，避免右滚时透出下层内容 */
.pk-pay-tbl table tbody tr:hover td.sticky-col { background: #f4f1ec; }
.pk-pay-tbl table tbody tr.row-sel td.sticky-col { background: #f3ebe6; }

@media print {
  .pk-pay-tbl table th, .pk-pay-tbl table td { font-size: 9pt !important; padding: 3px 6px !important; }
}
</style>
