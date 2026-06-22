<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount, provide } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../../stores/auth.js'
import { DEPARTMENTS, yearCST, monthCST, todayCST } from '../../constants.js'
import ar from '../../api/ar.js'
import { fmtCompact, fmtMoney } from '../../utils/format.js'
import { downloadBlob } from '../../utils/download.js'
import { useServerSort } from '../../composables/useServerSort.js'
import { useToast } from '../../composables/useToast.js'
import SortTh from '../../components/ar/SortTh.vue'
import FilterPanel from '../../components/ar/FilterPanel.vue'
import { describeCondition, STATUS_OPTS, RECON_OPTS, INVOICE_OPTS, RESP_OPTS } from '../../composables/arConditions.js'
import ImportPrecheckModal from '../../components/ImportPrecheckModal.vue'
import ColumnFilter from '../../components/ColumnFilter.vue'
import SkeletonRow from '../../components/SkeletonRow.vue'

const route = useRoute()
const router = useRouter()

const auth = useAuthStore()
const toast = useToast()
const items = ref([])
const total = ref(0)
const kpiData = ref(null)
const healthData = ref(null)
const showHealthModal = ref(false)
const healthFixing = ref(false)
const loading = ref(false)
const loadErr = ref('')
const page = ref(1)
const size = 50
const activeTab = ref('all')   // all | reconciliation | invoice | collection

// 统一筛选：所有维度/日期/金额都是 conditions 里的一条；matchMode 决定 且/或。
// 直接序列化为后端 conditions(JSON) + match 参数，前端不再有零散 flat 筛选。
const conditions = ref([])
const matchMode = ref('all')   // 'all'(且) | 'any'(或)
const showFilterPanel = ref(false)
// 请求参数：仅在有条件时下发 conditions/match（后端无条件时返回全集）
const reqParams = () => (conditions.value.length
  ? { conditions: JSON.stringify(conditions.value), match: matchMode.value }
  : {})
// 体检接口需要部门维度：从条件里取第一个 dept 维度（没有则不限部门）
const deptOfConditions = () => {
  const c = conditions.value.find(x => x.t === 'dim' && x.field === 'dept')
  return c ? c.value : ''
}

// ── 多选 + 批量删除 ─────────────────────────────────────────────────────────
const selectedIds = ref(new Set())          // 跨页按 id 记忆选择
const selectAllMatching = ref(false)        // 勾选整个筛选集（跨所有分页）
const bulkDeleting = ref(false)
// 二次输入确认：需手动输入待删条数才放行（删除规模越大摩擦越大，防误删）
const showDelConfirm = ref(false)
const delConfirmText = ref('')
const delConfirmCount = ref(0)
const delConfirmOk = computed(() => delConfirmText.value.trim() === String(delConfirmCount.value))
const pageAllSelected = computed(() =>
  items.value.length > 0 && items.value.every(r => selectedIds.value.has(r.id)))
const selectedCount = computed(() => selectAllMatching.value ? total.value : selectedIds.value.size)
const hasSelection = computed(() => selectAllMatching.value || selectedIds.value.size > 0)
function toggleRow(id) {
  const s = new Set(selectedIds.value)
  if (s.has(id)) { s.delete(id); selectAllMatching.value = false } else s.add(id)
  selectedIds.value = s
}
function toggleSelectPage() {
  const s = new Set(selectedIds.value)
  if (pageAllSelected.value) { items.value.forEach(r => s.delete(r.id)); selectAllMatching.value = false }
  else items.value.forEach(r => s.add(r.id))
  selectedIds.value = s
}
function clearSelection() { selectedIds.value = new Set(); selectAllMatching.value = false }
function bulkDelete() {
  const n = selectedCount.value
  if (!n) return
  delConfirmCount.value = n
  delConfirmText.value = ''
  showDelConfirm.value = true
}
async function confirmBulkDelete() {
  if (!delConfirmOk.value) return
  bulkDeleting.value = true
  try {
    if (selectAllMatching.value) await ar.bulkDeleteRecords({ all: true }, reqParams())
    else await ar.bulkDeleteRecords({ ids: [...selectedIds.value] })
    showDelConfirm.value = false
    clearSelection()
    await load(true)
  } catch (e) { toast.error(e?.msg || e?.error || '操作失败') }
  finally { bulkDeleting.value = false }
}

// 服务端排序（点表头）——状态机经 provide 下放给各 <SortTh>，变化即回首页重拉。
// SortTh 排序生效即清掉列头排序，保证两套排序互斥、sort 参数单一来源。
const sorter = useServerSort(() => {
  if (sorter.sort.value) { sortField.value = ''; sortOrder.value = '' }
  load(true)
})
provide('arSort', sorter)

// ── Excel 风格列头筛选 + 排序（真实列）──────────────────────────────────────
// 与既有 conditions / SortTh 并存：列头筛选走独立 filters(JSON) 参数下发；列头排序
// 与 SortTh 互斥（任一生效即清空另一方），统一序列化为后端 sort/order。仅作用于
// 应收明细列表 + 导出，不进 KPI / 分组汇总 / 批量等其它接口。
const colFilters = reactive({})    // field -> {op, value}
const sortField = ref('')
const sortOrder = ref('')          // 'asc' | 'desc' | ''
// 部门枚举选项复用页面既有可访问部门列表
function setColFilter(field, val) {
  if (val == null) delete colFilters[field]
  else colFilters[field] = val
  clearSelection()
  load(true)
}
function setSort(field, order) {
  sortField.value = order ? field : ''
  sortOrder.value = order || ''
  // 列头排序生效即清掉 SortTh 排序，避免两套排序争用 sort 参数
  if (order && sorter.sort.value) sorter.sort.value = ''
  load(true)
}
function buildParams(base = {}) {
  const p = { ...base }
  if (Object.keys(colFilters).length) p.filters = JSON.stringify(colFilters)
  // 排序优先级：列头排序 > SortTh 排序
  if (sortField.value && sortOrder.value) {
    p.sort = sortField.value
    p.order = sortOrder.value
  } else if (sorter.sort.value) {
    p.sort = sorter.sort.value
  }
  return p
}

const showModal = ref(false)
const editRec = ref(null)
const saving = ref(false)
const recForm = reactive({
  project_id: '', operation_date: todayCST(),
  estimated_amount: '', actual_invoice_amount: '', tax_amount: '',
  invoice_date: '', reconciliation_date: '', account_diff_adjustment: '',
  adjustment_reason: '',
  target_collection_date: '', invoice_batch_no: '', notes: '',
})

// ── 差额调整明细（编辑态管理器）─────────────────────────────────────────────
// 一条应收可多次调整，各带原因与金额；合计与未收由后端派生，前端只管明细。
const adjList = ref([])
const adjForm = reactive({ amount: '', reason: '' })
const adjBusy = ref(false)
const adjTotal = computed(() =>
  adjList.value.reduce((s, a) => s + (parseFloat(a.amount) || 0), 0))
async function addAdjustment() {
  if (!parseFloat(adjForm.amount)) { toast.error('调整金额不能为0（可正可负）'); return }
  if (!adjForm.reason.trim()) { toast.error('请填写调整原因（如：运费差、客户扣款、补付）'); return }
  adjBusy.value = true
  try {
    const res = await ar.addAdjustment(editRec.value.id, { amount: adjForm.amount, reason: adjForm.reason })
    adjList.value = res.data.items
    adjForm.amount = ''; adjForm.reason = ''
    await load()
  } catch (e) { toast.error(e?.msg || e?.error || '操作失败') }
  finally { adjBusy.value = false }
}
async function removeAdjustment(a) {
  if (!confirm(`删除调整「${a.reason || '未填原因'}：${a.amount}」？差额合计与未收金额将随之回退。`)) return
  adjBusy.value = true
  try {
    const res = await ar.deleteAdjustment(editRec.value.id, a.id)
    adjList.value = res.data.items
    await load()
  } catch (e) { toast.error(e?.msg || e?.error || '操作失败') }
  finally { adjBusy.value = false }
}

// ── 开票批次号批量设置 ──────────────────────────────────────────────────────────
const showBatchModal = ref(false)
const batchNoInput = ref('')
const batchAssigning = ref(false)

const projects = ref([])
const projectKeyword = ref('')
const projectSearching = ref(false)
let projectSearchTimer = null
// Server-side search by project_no / short_name / customer_name (debounced).
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
const payForm = reactive({ amount: '', payment_date: '', notes: '', source: '回款', counterparty_dept: '' })
const paySaving = ref(false)
// 录入回款时联动：该项目可用预收（只读提示，便于判断是否以预收冲抵应收）
const payAdvance = ref(null)
const expandedPayments = ref({})
const importing = ref(false)
const exporting = ref(false)
const fileInput = ref(null)
const importResult = ref(null)   // { ok: bool, title, lines: [] }
const precheckResult = ref(null)
const precheckBusy = ref(false)
const pendingFile = ref(null)

const accessibleDepts = computed(() => auth.effectiveDepts.filter(d => DEPARTMENTS.includes(d)))
const years = Array.from({ length: 5 }, (_, i) => yearCST() - 2 + i)
const months = Array.from({ length: 12 }, (_, i) => i + 1)

// Field-permission column visibility
const show = k => auth.canArView(k)

const TABS = [
  { key: 'all', label: '全部明细' },
  { key: 'reconciliation', label: '对账跟踪' },
  { key: 'invoice', label: '开票跟踪' },
  { key: 'batch', label: '批次管理' },
  { key: 'collection', label: '回款跟踪' },
  { key: 'offset', label: '预收核销' },
  { key: 'dunning', label: '催款' },
  { key: 'payments', label: '回款流水' },
  { key: 'summary', label: '汇总' },
]
const DATA_TABS = ['all', 'reconciliation', 'invoice', 'collection']
const isDataTab = computed(() => DATA_TABS.includes(activeTab.value))
const summaryData = ref(null)

// ── 筛选 chip 栏 ─────────────────────────────────────────────────────────────
const hasAnyFilter = computed(() =>
  conditions.value.length > 0 || Object.keys(colFilters).length > 0 || !!sortField.value)
// chip 文案统一由 describeCondition 生成（与面板单一来源）
const chipText = describeCondition
function removeCondition(i) {
  const l = conditions.value.slice(); l.splice(i, 1)
  conditions.value = l; onFilterChange()
}

// ── 快捷模糊搜索（项目 / 负责人 / 编号）──────────────────────────────────────
// 独立常驻搜索框，驱动统一条件引擎里的 q 维度；带防抖、不整页闪烁。
// chip 栏隐藏 q 维度（由搜索框承载），避免重复展示。
const quickQ = ref('')
let quickTimer = null
const chipConditions = computed(() =>
  conditions.value.map((c, i) => ({ c, i })).filter(x => !(x.c.t === 'dim' && x.c.field === 'q')))
function applyQuickQ() {
  const v = quickQ.value.trim()
  const rest = conditions.value.filter(c => !(c.t === 'dim' && c.field === 'q'))
  conditions.value = v ? [...rest, { t: 'dim', field: 'q', value: v }] : rest
  onFilterChange()
}
function onQuickSearch() {
  clearTimeout(quickTimer)
  quickTimer = setTimeout(applyQuickQ, 300)   // 停顿 300ms 才查，避免逐键闪频
}
function clearQuickQ() { quickQ.value = ''; clearTimeout(quickTimer); applyQuickQ() }

// ── 回款流水 (payment ledger) ───────────────────────────────────────────────
const payFilters = reactive({ pay_start: '', pay_end: '', dept: '', q: '', source: '' })
const payItems = ref([])
const paySummary = ref(null)
const payTotal = ref(0)
const payPage = ref(1)
const payLoading = ref(false)
const payExporting = ref(false)

// 回款日期快捷区间（UTC+8 口径，与 todayCST 一致）。当前选中项用于高亮；
// 手动改任一日期输入即转「自定义」，清空高亮。
const payRangePreset = ref('')
const PAY_RANGE_PRESETS = [
  { key: 'today', label: '今天' },
  { key: 'week', label: '本周' },
  { key: 'month', label: '本月' },
  { key: 'quarter', label: '本季度' },
  { key: 'year', label: '本年' },
  { key: '', label: '全部' },
]
function setPayRange(key) {
  payRangePreset.value = key
  const iso = (d) => d.toISOString().slice(0, 10)
  const base = new Date(todayCST() + 'T00:00:00Z')   // CST 当天 00:00，用 UTC 方法运算避免本地时区漂移
  let start = '', end = iso(base)
  if (key === '') { start = ''; end = '' }
  else if (key === 'today') { start = iso(base) }
  else if (key === 'week') {
    const dow = (base.getUTCDay() + 6) % 7            // 周一=0
    const s = new Date(base); s.setUTCDate(base.getUTCDate() - dow); start = iso(s)
  }
  else if (key === 'month') start = iso(new Date(Date.UTC(base.getUTCFullYear(), base.getUTCMonth(), 1)))
  else if (key === 'quarter') start = iso(new Date(Date.UTC(base.getUTCFullYear(), Math.floor(base.getUTCMonth() / 3) * 3, 1)))
  else if (key === 'year') start = iso(new Date(Date.UTC(base.getUTCFullYear(), 0, 1)))
  payFilters.pay_start = start
  payFilters.pay_end = end
  loadPayments(true)
}
function onPayDateChange() { payRangePreset.value = ''; loadPayments(true) }

// ── 催款工作台 (collection workbench) ───────────────────────────────────────
const dunFilters = reactive({ dept: '', q: '', bucket: '', contact: '' })
const dunBuckets = ref([])
const dunContacts = ref([])
const dunItems = ref([])
const dunSummary = ref(null)
const dunTotal = ref(0)
const dunPage = ref(1)
const dunLoading = ref(false)
const dunSelected = ref(new Set())
const dunCreating = ref(false)
let dunQTimer = null

async function loadDunning(reset = false) {
  if (reset) { dunPage.value = 1; dunSelected.value = new Set() }
  dunLoading.value = true
  try {
    const res = await ar.collectionWorkbench({ ...dunFilters, page: dunPage.value, size })
    dunBuckets.value = res.data.buckets
    dunContacts.value = res.data.by_contact
    dunItems.value = res.data.items
    dunTotal.value = res.data.total
    dunSummary.value = res.data.summary
  } finally { dunLoading.value = false }
}
function onDunSearch() {
  clearTimeout(dunQTimer)
  dunQTimer = setTimeout(() => loadDunning(true), 300)
}
function toggleDunBucket(key) {
  dunFilters.bucket = dunFilters.bucket === key ? '' : key
  loadDunning(true)
}
function toggleDunContact(name) {
  dunFilters.contact = dunFilters.contact === name ? '' : name
  loadDunning(true)
}
function toggleDunRow(id) {
  const s = new Set(dunSelected.value)
  if (s.has(id)) s.delete(id); else s.add(id)
  dunSelected.value = s
}
// 已有未关闭催款任务的记录不可再选（生成时也会被后端跳过）
const dunSelectable = computed(() => dunItems.value.filter(r => !r.open_action_id))
const dunPageAllSelected = computed(() =>
  dunSelectable.value.length > 0 && dunSelectable.value.every(r => dunSelected.value.has(r.id)))
function toggleDunSelectPage() {
  const s = new Set(dunSelected.value)
  if (dunPageAllSelected.value) dunSelectable.value.forEach(r => s.delete(r.id))
  else dunSelectable.value.forEach(r => s.add(r.id))
  dunSelected.value = s
}
async function createDunningTasks() {
  const ids = [...dunSelected.value]
  if (!ids.length) return
  if (!confirm(`将为 ${ids.length} 条逾期应收生成催款任务（出现在财务驾驶舱·决策行动），确定？`)) return
  dunCreating.value = true
  try {
    const res = await ar.createDunning({ ids })
    const d = res.data
    let msg = `已生成 ${d.created} 条催款任务`
    if (d.skipped) msg += `，${d.skipped} 条已有未关闭任务（跳过）`
    toast.success(msg)
    await loadDunning(true)
  } catch (e) { toast.error(e?.msg || e?.error || '操作失败') }
  finally { dunCreating.value = false }
}
// 逾期天数着色：≤30 橙、>30 红
const overdueClass = d => (d > 30 ? 'od-danger' : 'od-warn')

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

// 亿/万 两级单位（无空格），万元以下两位小数；空值显示 0.00（保持原表现）
const fmtAmt = (v) => fmtCompact(v, { dash: '0.00' })
// 表格内金额：精确数值、千分位、不带单位（KPI 指标条仍用 fmtAmt 带单位）
const fmtCell = (v) => fmtMoney(v, '—')

// ── 分页跳转 ────────────────────────────────────────────────────────────────
const jumpPage = ref(1)
function doJump() {
  const tp = Math.ceil(total.value / size)
  const p = Math.max(1, Math.min(tp, jumpPage.value || 1))
  page.value = p; load(false)
}

async function load(reset = false) {
  if (reset) page.value = 1
  loading.value = true
  loadErr.value = ''
  try {
    const [recs, kpi] = await Promise.all([
      ar.listRecords(buildParams({ ...reqParams(),
        include_payments: 1, page: page.value, size })),
      ar.recordsKpi(buildParams(reqParams())),
    ])
    items.value = recs.data.items
    total.value = recs.data.total
    summaryData.value = recs.data.summary
    kpiData.value = kpi.data
  } catch (e) { loadErr.value = e?.error || e?.message || '加载失败，请刷新重试'
  } finally { loading.value = false }
  loadHealth()
}

async function loadHealth() {
  try {
    const res = await ar.dataHealth({ dept: deptOfConditions() })
    healthData.value = res.data
  } catch { healthData.value = null }
}

async function fixStaleRecords() {
  const ids = (healthData.value?.stale || []).map(r => r.id)
  if (!ids.length) return
  if (!confirm(`将按现规则重算 ${ids.length} 条未收金额不一致的记录，确定继续？`)) return
  healthFixing.value = true
  try {
    const res = await ar.recomputeRecords(ids)
    const failed = res.data.failed || []
    let msg = `已重算修复 ${res.data.fixed} 条`
    if (failed.length) msg += `\n${failed.length} 条仍需人工处理（累计回款超过上账口径）`
    toast.success(msg)
    await loadHealth(); await load()
  } catch (e) { toast.error(e?.msg || e?.error || '操作失败') }
  finally { healthFixing.value = false }
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
    downloadBlob(res, '回款流水.xlsx')
  } catch (e) { toast.error(e?.msg || e?.error || '操作失败')
  } finally { payExporting.value = false }
}

async function loadGroupSummary() {
  groupLoading.value = true
  try {
    const res = await ar.recordsSummary({ ...reqParams(), group_by: summaryGroupBy.value })
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
  else if (key === 'dunning') loadDunning(true)
  else if (key === 'offset') loadOffsetWorkbench()
  else if (key === 'batch') loadBatches()
  else if (!DATA_TABS.includes(prev)) load()  // returning from a non-data tab
}

// Shared-filter change → refresh whichever tab consumes those filters.
function onFilterChange() {
  clearSelection()
  if (activeTab.value === 'summary') loadGroupSummary()
  else if (activeTab.value === 'batch') loadBatches()
  else load(true)
}

// 汇总行下钻：把该维度作为条件追加（替换同字段旧条件），切到全部明细
function upsertDim(field, value) {
  const list = conditions.value.filter(c => !(c.t === 'dim' && c.field === field))
  list.push({ t: 'dim', field, value })
  conditions.value = list
}

// ── 状态类列头筛选（计算列）：复用既有 dim/conditions 机制，与筛选面板/chip 同源 ──
// 这些状态（状态/对账/开票/责任）后端已有成熟的 dim 过滤口径，列头只做单选 dim 的增删，
// 不新增任何 SQL 注解，避免与 @property 显示口径出现偏差。
const _toOpts = arr => arr.map(o => ({ value: o.v, label: o.l }))
const DIM_OPTS = {
  status: _toOpts(STATUS_OPTS),
  reconciliation_status: _toOpts(RECON_OPTS),
  invoice_status: _toOpts(INVOICE_OPTS),
  responsibility: _toOpts(RESP_OPTS),
}
function setDimFilter(field, value) {
  const list = conditions.value.filter(c => !(c.t === 'dim' && c.field === field))
  if (value) list.push({ t: 'dim', field, value })
  conditions.value = list
  onFilterChange()
}
function dimModel(field) {
  const c = conditions.value.find(x => x.t === 'dim' && x.field === field)
  return c ? { op: 'in', value: [c.value] } : null
}
function onDimCol(field, val) {
  const v = (val && Array.isArray(val.value) && val.value.length) ? val.value[0] : ''
  setDimFilter(field, v)
}
function drillIntoGroup(row) {
  if (!DRILLABLE_DIMS.includes(summaryGroupBy.value)) return
  const gb = summaryGroupBy.value
  if (gb === 'dept') upsertDim('dept', row.key)
  else if (gb === 'invoice_status') upsertDim('invoice_status', row.key)
  else if (gb === 'month') upsertDim('operation_ym', `${row.year}-${String(row.month).padStart(2, '0')}`)
  else if (gb === 'manager') upsertDim('manager', row.key)
  switchTab('all')
  load(true)
}

function openCreate() {
  editRec.value = null
  Object.assign(recForm, {
    project_id: '',
    operation_date: todayCST(),
    estimated_amount: '', actual_invoice_amount: '', tax_amount: '',
    invoice_date: '', reconciliation_date: '', account_diff_adjustment: '',
    adjustment_reason: '',
    target_collection_date: '', invoice_batch_no: '', notes: '',
  })
  adjList.value = []
  showModal.value = true
  projectKeyword.value = ''
  searchProjects('')  // initial page of projects
}

function openEdit(rec) {
  editRec.value = rec
  Object.assign(recForm, {
    project_id: rec.project_id, operation_date: rec.operation_date || '',
    estimated_amount: rec.estimated_amount, actual_invoice_amount: rec.actual_invoice_amount || '',
    tax_amount: rec.tax_amount || '', invoice_date: rec.invoice_date || '',
    reconciliation_date: rec.reconciliation_date || '',
    account_diff_adjustment: rec.account_diff_adjustment || '',
    adjustment_reason: '',
    target_collection_date: rec.target_collection_date || '',
    invoice_batch_no: rec.invoice_batch_no || '',
    notes: rec.notes,
  })
  adjList.value = rec.adjustments || []
  Object.assign(adjForm, { amount: '', reason: '' })
  showModal.value = true
}

// 批次号三种来源：auto=系统生成（客户简称-日期-序号，默认推荐，免人为编码）；
// existing=并入已有批次（下拉选，不用记号）；custom=自定义/清空（保留兜底）
const batchMode = ref('auto')
const batchExisting = ref('')
const batchExistingList = ref([])

async function openBatchAssign() {
  batchNoInput.value = ''
  batchMode.value = 'auto'
  batchExisting.value = ''
  showBatchModal.value = true
  try {
    const res = await ar.listInvoiceBatches({})
    batchExistingList.value = res.data.batches || []
  } catch (_) { batchExistingList.value = [] }
}

async function confirmBatchAssign() {
  const body = {}
  if (batchMode.value === 'auto') body.auto = true
  else if (batchMode.value === 'existing') {
    if (!batchExisting.value) { toast.error('请选择要并入的批次'); return }
    body.invoice_batch_no = batchExisting.value
  } else body.invoice_batch_no = batchNoInput.value
  batchAssigning.value = true
  try {
    let res
    if (selectAllMatching.value) {
      res = await ar.batchAssignBatchNo({ all: true, ...body }, reqParams())
    } else {
      res = await ar.batchAssignBatchNo({ ids: [...selectedIds.value], ...body })
    }
    const bn = res.data?.invoice_batch_no
    toast.success(bn ? `已合并 ${selectedCount.value} 条记录到批次「${bn}」`
             : `已为 ${selectedCount.value} 条记录清空批次`)
    showBatchModal.value = false
    clearSelection()
    await load()
    if (activeTab.value === 'batch') loadBatches()
  } catch (e) { toast.error(e?.msg || e?.error || '操作失败')
  } finally { batchAssigning.value = false }
}

// ── 合并开票批次工作台（开票跟踪 Tab）─────────────────────────────────────────
// 同批次号的记录合并开一张发票；差额调整落在具体记录上；回款按批次录入，
// 系统按运作日期先进先出自动分摊到成员记录——不再手工拆账。
const batches = ref([])
const batchesLoading = ref(false)
const showBatchPanel = ref(true)
const batchDetail = ref({})        // batch_no -> detail（成员明细，懒加载缓存）
const expandedBatch = ref('')
const showBatchInvoice = ref(false)
const showBatchPay = ref(false)
const batchTarget = ref(null)
const batchInvForm = reactive({ invoice_date: todayCST(), amount: '', tax_amount: '', notes: '' })
const batchPayForm = reactive({ amount: '', payment_date: todayCST(), notes: '' })
const batchActing = ref(false)
const batchPayResult = ref(null)   // 分摊结果回执

async function loadBatches() {
  batchesLoading.value = true
  try {
    const res = await ar.listInvoiceBatches(reqParams())
    batches.value = res.data.batches
  } catch (_) { batches.value = [] }
  finally { batchesLoading.value = false }
}
async function fetchBatchDetail(bn, force = false) {
  if (!force && batchDetail.value[bn]) return batchDetail.value[bn]
  const res = await ar.getInvoiceBatch(bn)
  batchDetail.value = { ...batchDetail.value, [bn]: res.data }
  return res.data
}
function toggleBatchExpand(bn) {
  expandedBatch.value = expandedBatch.value === bn ? '' : bn
  if (expandedBatch.value) fetchBatchDetail(bn).catch(() => {})
}
async function refreshAfterBatchAction(bn) {
  await Promise.all([loadBatches(), load(), fetchBatchDetail(bn, true).catch(() => {})])
}
// 金额级分批开票：每次开票一个事件（日期+金额+税额），先进先出分摊到成员
// 可开余额，累计 ≤ 上账+差额 合计即可多次开票；事件可整次撤销
const invDetail = computed(() => batchDetail.value[batchTarget.value?.batch_no])
const invRoom = computed(() => parseFloat(invDetail.value?.summary?.invoice_room) || 0)
async function openBatchInvoice(b) {
  batchTarget.value = b
  Object.assign(batchInvForm, { invoice_date: todayCST(), amount: '', tax_amount: '', notes: '' })
  showBatchInvoice.value = true
  fetchBatchDetail(b.batch_no, true).catch(() => {})
}
async function doBatchInvoice() {
  if (!(parseFloat(batchInvForm.amount) > 0)) { toast.error('请填写本次开票金额（价税合计）'); return }
  batchActing.value = true
  try {
    const res = await ar.batchInvoice(batchTarget.value.batch_no, { ...batchInvForm })
    toast.success(res.data?.message || '开票已落账')
    Object.assign(batchInvForm, { invoice_date: todayCST(), amount: '', tax_amount: '', notes: '' })
    await refreshAfterBatchAction(batchTarget.value.batch_no)
  } catch (e) { toast.error(e?.msg || e?.error || '操作失败') }
  finally { batchActing.value = false }
}
async function undoBatchInvoice(ev) {
  if (!confirm(`撤销 ${ev.invoice_date} 的开票 ${ev.amount} 元？各记录开票额将整体回退。`)) return
  batchActing.value = true
  try {
    const res = await ar.batchInvoiceUndo(batchTarget.value.batch_no, { event_id: ev.id })
    toast.success(res.data?.message || '已撤销')
    await refreshAfterBatchAction(batchTarget.value.batch_no)
  } catch (e) { toast.error(e?.msg || e?.error || '操作失败') }
  finally { batchActing.value = false }
}
function openBatchPay(b) {
  batchTarget.value = b
  Object.assign(batchPayForm, { amount: '', payment_date: todayCST(), notes: '' })
  batchPayResult.value = null
  fetchBatchDetail(b.batch_no).catch(() => {})
  showBatchPay.value = true
}
async function doBatchPay() {
  batchActing.value = true
  try {
    const res = await ar.batchPayment(batchTarget.value.batch_no, { ...batchPayForm })
    batchPayResult.value = res.data   // 留在弹窗里展示分摊回执
    await refreshAfterBatchAction(batchTarget.value.batch_no)
  } catch (e) { toast.error(e?.msg || e?.error || '操作失败') }
  finally { batchActing.value = false }
}
async function undoBatchPay(b, ev) {
  if (!confirm(`撤销 ${ev.payment_date} 的批次回款 ${ev.total} 元（分摊 ${ev.count} 笔）？\n各记录未收金额将整体恢复。`)) return
  batchActing.value = true
  try {
    const res = await ar.batchPaymentUndo(b.batch_no, { payment_ids: ev.payment_ids })
    toast.success(res.data?.message || '已撤销')
    await refreshAfterBatchAction(b.batch_no)
  } catch (e) { toast.error(e?.msg || e?.error || '操作失败') }
  finally { batchActing.value = false }
}

async function saveRec() {
  if (!recForm.project_id) { toast.error('请选择项目'); return }
  saving.value = true
  try {
    if (!recForm.operation_date) { toast.error('请选择运作日期'); saving.value = false; return }
    const payload = {
      project_id: recForm.project_id, operation_date: recForm.operation_date,
      estimated_amount: recForm.estimated_amount || 0,
      actual_invoice_amount: recForm.actual_invoice_amount || null,
      tax_amount: recForm.tax_amount || null, invoice_date: recForm.invoice_date || null,
      reconciliation_date: recForm.reconciliation_date || null,
      target_collection_date: recForm.target_collection_date || null,
      invoice_batch_no: recForm.invoice_batch_no || '',
      notes: recForm.notes,
    }
    // 差额调整走明细：新建时把初始差额+原因一并提交；编辑态由调整管理器单独维护
    if (!editRec.value) {
      payload.account_diff_adjustment = recForm.account_diff_adjustment || 0
      payload.adjustment_reason = recForm.adjustment_reason || ''
    }
    if (editRec.value) await ar.updateRecord(editRec.value.id, payload)
    else await ar.createRecord(payload)
    showModal.value = false; await load()
  } catch (e) { toast.error(e?.msg || e?.error || '操作失败')
  } finally { saving.value = false }
}

async function deleteRec(rec) {
  const amt = parseFloat(rec.estimated_amount || 0).toFixed(2)
  if (!confirm(`确定删除「${rec.short_name || rec.customer_name}」${rec.operation_date || (rec.operation_year + '年' + rec.operation_month + '月')}的应收记录（${amt} 元）？同期可能存在多条记录，请确认。`)) return
  try { await ar.deleteRecord(rec.id); await load() }
  catch (e) { toast.error(e?.msg || e?.error || '操作失败') }
}

function togglePayments(id) { expandedPayments.value[id] = !expandedPayments.value[id] }
// 预收冲抵次数（source='预收抵扣' 的回款数）——列表「预收冲抵」列用
const offsetCount = rec => (rec.payments || []).filter(p => p.source === '预收抵扣').length
// 内部往来核销次数（source='内部往来'）——列表「内部往来」列用
const internalCount = rec => (rec.payments || []).filter(p => p.source === '内部往来').length

// ── 预收核销工作台（预收核销 Tab）────────────────────────────────────────────
// 按客户聚合「有预收余额 × 名下有未收应收」，勾选多条应收后用一笔预收
// 按运作日期先进先出批量冲抵——解决一个客户多项目逐条核销太繁的问题。
const owGroups = ref([])
const owLoading = ref(false)
const owQ = ref('')
let owTimer = null
const owSel = ref({})              // customer -> Set(record ids)
const showWoModal = ref(false)
const woTarget = ref(null)         // { customer, advances, records }（records=已勾选）
const woForm = reactive({ advance_id: '', amount: '', writeoff_date: todayCST() })
const woBusy = ref(false)
const woResult = ref(null)

async function loadOffsetWorkbench() {
  owLoading.value = true
  try {
    const res = await ar.offsetWorkbench({ q: owQ.value.trim() || undefined, dept: deptOfConditions() || undefined })
    owGroups.value = res.data.groups
    owSel.value = {}
  } catch (e) { owGroups.value = []; toast.error(e?.msg || e?.error || '操作失败') }
  finally { owLoading.value = false }
}
function onOwSearch() { clearTimeout(owTimer); owTimer = setTimeout(loadOffsetWorkbench, 300) }
function owToggle(cust, id) {
  const s = new Set(owSel.value[cust] || [])
  s.has(id) ? s.delete(id) : s.add(id)
  owSel.value = { ...owSel.value, [cust]: s }
}
function owToggleAll(g) {
  const s = new Set(owSel.value[g.customer] || [])
  const all = g.records.every(r => s.has(r.id))
  g.records.forEach(r => { all ? s.delete(r.id) : s.add(r.id) })
  owSel.value = { ...owSel.value, [g.customer]: s }
}
const owSelCount = cust => (owSel.value[cust]?.size || 0)
const woSelRecords = computed(() => {
  if (!woTarget.value) return []
  const s = owSel.value[woTarget.value.customer] || new Set()
  return woTarget.value.records.filter(r => s.has(r.id))
})
const woSelOutstanding = computed(() =>
  woSelRecords.value.reduce((t, r) => t + (parseFloat(r.outstanding) || 0), 0))
const woAdvBalance = computed(() => {
  const a = (woTarget.value?.advances || []).find(x => x.id === woForm.advance_id)
  return a ? parseFloat(a.balance_amount) || 0 : 0
})
const woDefaultAmount = computed(() => Math.min(woAdvBalance.value, woSelOutstanding.value))

function openBatchWriteoff(g) {
  if (!owSelCount(g.customer)) { toast.error('请先勾选要冲抵的应收明细'); return }
  woTarget.value = g
  Object.assign(woForm, {
    advance_id: g.advances[0]?.id || '',
    amount: '', writeoff_date: todayCST(),
  })
  woResult.value = null
  showWoModal.value = true
}
async function doBatchWriteoff() {
  const amt = parseFloat(woForm.amount) || woDefaultAmount.value
  if (!(amt > 0)) { toast.error('核销金额必须大于0'); return }
  woBusy.value = true
  try {
    const res = await ar.batchWriteoff(woForm.advance_id, {
      record_ids: woSelRecords.value.map(r => r.id),
      amount: amt, writeoff_date: woForm.writeoff_date,
    })
    woResult.value = res.data
    await loadOffsetWorkbench()
  } catch (e) { toast.error(e?.msg || e?.error || '操作失败') }
  finally { woBusy.value = false }
}

function openAddPayment(rec) {
  payRec.value = rec
  Object.assign(payForm, { amount: '', payment_date: todayCST(), notes: '', source: '回款', counterparty_dept: '' })
  payAdvance.value = null
  advWoSel.value = null
  showPayModal.value = true
  loadPayAdvance(rec)
}

// 拉取可用预收：本项目的预收 ∪ 未挂项目但客户名匹配的散单预收。
// 无权限或无数据时静默隐藏提示。
async function loadPayAdvance(rec) {
  if (!rec?.project_id && !rec?.customer_name) return
  try {
    const params = { direction: '预收' }
    if (rec.project_id) params.project_id = rec.project_id
    if (rec.customer_name) params.customer = rec.customer_name
    const res = await ar.advancesAvailable(params)
    if (res.data?.count > 0) payAdvance.value = res.data
  } catch (_) { /* 无预收预付权限时静默 */ }
}

// ── 用预收直接给本笔应收下账（核销预收 + 生成预收抵扣回款，一步完成）──────────
const advWoSel = ref(null)              // 选中的预收
const advWoForm = reactive({ amount: '' })
const advWoSaving = ref(false)

function selectAdvForWriteoff(a) {
  advWoSel.value = a
  // 默认抵扣额 = min(预收余额, 应收未收)
  const bal = parseFloat(a.balance_amount) || 0
  const out = parseFloat(payRec.value?.outstanding_amount) || 0
  advWoForm.amount = Math.min(bal, out).toFixed(2)
}

async function applyAdvanceWriteoff() {
  const amt = parseFloat(advWoForm.amount)
  if (!(amt > 0)) { toast.error('下账金额必须大于0'); return }
  advWoSaving.value = true
  try {
    await ar.addWriteoff(advWoSel.value.id, {
      amount: amt,
      writeoff_date: payForm.payment_date || todayCST(),
      ar_record_id: payRec.value.id,
    })
    showPayModal.value = false
    await load()
  } catch (e) { toast.error(e?.msg || e?.error || '操作失败')
  } finally { advWoSaving.value = false }
}

// 跳转到预收预付页，预筛该项目的预收，便于在那里做核销冲抵。
function gotoAdvance() {
  const pid = payRec.value?.project_id
  showPayModal.value = false
  router.push({ path: '/ar/advances', query: { project_id: pid, direction: '预收' } })
}

async function savePayment() {
  if (!payForm.amount || !payForm.payment_date) { toast.error('金额和日期必填'); return }
  if (payForm.source === '内部往来' && !payForm.counterparty_dept) {
    toast.error('内部往来核销请选择往来部门'); return
  }
  paySaving.value = true
  try {
    await ar.addPayment(payRec.value.id, payForm)
    showPayModal.value = false; await load()
  } catch (e) { toast.error(e?.msg || e?.error || '操作失败')
  } finally { paySaving.value = false }
}

async function deletePayment(rec, pay) {
  const tip = pay.source === '预收抵扣'
    ? `撤销该笔预收核销（${pay.amount} 元）？\n预收余额将恢复，本应收未收金额相应回升。`
    : pay.source === '内部往来'
      ? `确定删除该笔内部往来核销（${pay.amount} 元 · 往来部门 ${pay.counterparty_dept || '—'}）？\n本应收未收金额相应回升。`
      : `确定删除第${pay.payment_no}次回款 ${pay.amount} 元？`
  if (!confirm(tip)) return
  try { await ar.deletePayment(rec.id, pay.id); await load() }
  catch (e) { toast.error(e?.msg || e?.error || '操作失败') }
}

async function downloadTemplate() {
  try {
    const res = await ar.recordTemplate()
    downloadBlob(res, '应收账款明细导入模板.xlsx')
  } catch (e) { toast.error(e?.msg || e?.error || '操作失败') }
}

async function handleImport(e) {
  const f = e.target.files?.[0]; if (!f) return
  pendingFile.value = f
  precheckResult.value = null
  importing.value = true
  try {
    const fd = new FormData(); fd.append('file', f)
    const pr = await ar.precheckRecords(fd); const pd = pr.data
    if (pd.skipPrecheck) { await doImport(f); return }
    if ((pd.attention || 0) > 0) { precheckResult.value = pd; return }
    await doImport(f)
  } catch (err) {
    importResult.value = { ok: false, title: '导入失败', sections: [{ label: '错误信息', items: [err?.msg || err?.error || err?.message || '服务器错误，请联系管理员'] }] }
  } finally { importing.value = false; if (fileInput.value) fileInput.value.value = '' }
}

async function doImport(f) {
  importing.value = true
  try {
    const fd = new FormData(); fd.append('file', f)
    const res = await ar.importRecords(fd); const d = res.data
    if (d.rejected) {
      importResult.value = {
        ok: false,
        title: d.message || '导入未执行，请修正后重新导入',
        sections: [{ label: '错误明细', items: d.errors || [] }],
      }
    } else {
      const sections = []
      const md = d.match_detail || {}
      if (md.exact?.length) sections.push({ label: `精确匹配项目（${md.exact.length} 个）`, items: md.exact.map(x => `${x.short_name}（${x.count} 条）`) })
      if (md.exact_multi?.length) sections.push({ label: `⚠ 精确匹配但同名多个（${md.exact_multi.length} 个，已取最新，请核查）`, warn: true, items: md.exact_multi.map(x => `${x.short_name} → 匹配到「${x.matched_to}」（${x.count} 条）${x.warn ? '  ' + x.warn : ''}`) })
      if (md.fuzzy?.length) sections.push({ label: `模糊匹配项目（${md.fuzzy.length} 个，请核查）`, warn: true, items: md.fuzzy.map(x => `"${x.short_name}" → 匹配到「${x.matched_to}」（${x.count} 条）`) })
      if (md.fuzzy_multi?.length) sections.push({ label: `⚠ 模糊匹配且多候选（${md.fuzzy_multi.length} 个，请核查）`, warn: true, items: md.fuzzy_multi.map(x => `"${x.short_name}" → 匹配到「${x.matched_to}」（${x.count} 条）${x.warn ? '  ' + x.warn : ''}`) })
      if (md.created?.length) sections.push({ label: `新建草稿项目（${md.created.length} 个，请到项目台账补充完善）`, items: md.created.map(x => `${x.short_name}（${x.count} 条记录已关联）`) })
      if (d.warnings?.length) sections.push({ label: `导入提示（${d.warnings.length} 条）`, warn: true, items: d.warnings.slice(0, 80), more: d.warnings.length > 80 ? `…共 ${d.warnings.length} 条，已截断` : '' })
      importResult.value = {
        ok: true,
        title: `导入完成：创建 ${d.created} 条`,
        sections,
      }
      await load()
    }
  } catch (err) {
    importResult.value = { ok: false, title: '导入失败', sections: [{ label: '错误信息', items: [err?.msg || err?.error || err?.message || '服务器错误，请联系管理员'] }] }
  } finally { importing.value = false }
}

async function onPrecheckApply({ mode }) {
  if (mode !== 'import') return
  precheckBusy.value = true
  try {
    await doImport(pendingFile.value)
    precheckResult.value = null
  } finally { precheckBusy.value = false; importing.value = false }
}

async function exportData() {
  exporting.value = true
  try {
    const res = await ar.exportRecords(buildParams(reqParams()))
    downloadBlob(res, '应收账款明细.xlsx')
  } catch (e) { toast.error(e?.msg || e?.error || '操作失败')
  } finally { exporting.value = false }
}

const onScopeChange = () => {
  // 部门范围变化：移除不再可访问的 dept 条件
  const before = conditions.value.length
  conditions.value = conditions.value.filter(
    c => !(c.t === 'dim' && c.field === 'dept' && !accessibleDepts.value.includes(c.value)))
  if (payFilters.dept && !accessibleDepts.value.includes(payFilters.dept)) payFilters.dept = ''
  if (dunFilters.dept && !accessibleDepts.value.includes(dunFilters.dept)) dunFilters.dept = ''
  if (activeTab.value === 'payments') loadPayments(true)
  else if (activeTab.value === 'summary') loadGroupSummary()
  else if (activeTab.value === 'dunning') loadDunning(true)
  else load(true)
  void before
}
onMounted(() => {
  // 路由跳转带入的筛选（来自现金流/分析/项目台账等）→ 转成条件
  if (route.query.status) conditions.value.push({ t: 'dim', field: 'status', value: route.query.status })
  if (route.query.project_id) conditions.value.push({ t: 'dim', field: 'project_id', value: route.query.project_id })
  if (route.query.dept) conditions.value.push({ t: 'dim', field: 'dept', value: route.query.dept })
  // 默认只看「未结清」（应收明细/对账/开票/回款都先聚焦没收完的）；可点掉该条件看全部
  if (!conditions.value.some(c => c.t === 'dim' && c.field === 'status')) {
    conditions.value.push({ t: 'dim', field: 'status', value: 'outstanding' })
  }
  load()
  window.addEventListener('pk:depts-changed', onScopeChange)
})
onBeforeUnmount(() => window.removeEventListener('pk:depts-changed', onScopeChange))
function clearFilters() {
  conditions.value = []
  matchMode.value = 'all'
  quickQ.value = ''
  // 一并清掉 Excel 风格列头筛选 + 列头排序
  Object.keys(colFilters).forEach(k => delete colFilters[k])
  sortField.value = ''
  sortOrder.value = ''
  onFilterChange()
}
</script>

<template>
  <div>
    <div class="topbar">
      <div class="topbar-left">
        <h1>应收账款</h1>
        <div class="segment-ctrl">
          <button v-for="t in TABS" :key="t.key"
            :class="['seg-btn', activeTab === t.key ? 'active' : '']" @click="switchTab(t.key)">
            <span class="seg-dot"></span>{{ t.label }}
          </button>
        </div>
        <!-- 筛选 chip 栏紧跟 Tab 之后，省去独立一行 -->
        <div v-if="activeTab !== 'payments' && activeTab !== 'dunning' && activeTab !== 'offset'" class="filter-chipbar">
          <!-- 常驻快捷搜索：项目 / 负责人 / 编号，模糊匹配，防抖不闪 -->
          <div class="quick-search">
            <svg class="qs-ico" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>
            <input v-model="quickQ" class="qs-input" placeholder="搜项目 / 负责人 / 编号"
                   @input="onQuickSearch" @keyup.enter="applyQuickQ" />
            <button v-if="quickQ" class="qs-clear" title="清除" @click="clearQuickQ">✕</button>
          </div>
          <div class="fb-trigger-wrap">
            <button class="fb-trigger" :class="{ on: showFilterPanel }" @click="showFilterPanel = !showFilterPanel">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 3H2l8 9.46V19l4 2v-8.54z"/></svg>
              筛选<span v-if="conditions.length" class="fb-badge">{{ conditions.length }}</span>
            </button>
            <div v-if="showFilterPanel" class="fb-backdrop" @click="showFilterPanel = false"></div>
            <div v-if="showFilterPanel" class="fb-pop">
              <FilterPanel
                v-model="conditions" v-model:match="matchMode"
                :accessible-depts="accessibleDepts" :years="years"
                @change="onFilterChange" @close="showFilterPanel = false" />
            </div>
          </div>
          <span v-if="chipConditions.length > 1" class="fb-match" :title="matchMode === 'any' ? '满足任一条件' : '满足全部条件'">
            {{ matchMode === 'any' ? '或' : '且' }}
          </span>
          <span v-for="{ c, i } in chipConditions" :key="i" class="filter-chip" :class="c.t" @click="showFilterPanel = true">
            {{ chipText(c) }}
            <button title="移除" @click.stop="removeCondition(i)">✕</button>
          </span>
          <button v-if="hasAnyFilter" class="clear-mini" @click="clearFilters">清空</button>
        </div>
      </div>
      <div class="ctrl-row">
        <button class="btn btn-ghost btn-sm" @click="downloadTemplate">↓ 模板</button>
        <label class="btn btn-ghost btn-sm" style="cursor:pointer">
          {{ importing ? '导入中…' : '↑ 导入' }}
          <input ref="fileInput" type="file" accept=".xlsx,.xls" style="display:none" @change="handleImport" />
        </label>
        <button class="btn btn-ghost btn-sm" :disabled="exporting" @click="exportData">↓ 导出</button>
        <button v-if="auth.canArWrite" class="btn btn-primary btn-sm" @click="openCreate">+ 新增应收</button>
      </div>
    </div>

    <!-- 数据体检提示：检测到旧模板导入等造成的口径异常记录 -->
    <div v-if="healthData?.has_issues" class="health-alert">
      <span class="health-icon">⚠</span>
      <span class="health-text">
        检测到 <strong>{{ (healthData.negative_count || 0) + (healthData.stale_count || 0) }}</strong> 条数据口径异常（多为旧模板导入产生）：
        <template v-if="healthData.stale_count">未收金额需重算 <strong>{{ healthData.stale_count }}</strong> 条</template>
        <template v-if="healthData.stale_count && healthData.negative_count"> · </template>
        <template v-if="healthData.negative_count">累计回款超过上账口径 <strong>{{ healthData.negative_count }}</strong> 条需人工核对</template>
      </span>
      <button class="health-btn" @click="showHealthModal = true">查看并修正</button>
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
            <div class="kpi-item ok" title="应收口径：含预收抵扣（以预收冲减应收也算已收）；纯现金口径见 现金流分析 / 资金池"><span class="kpi-k">已收</span><span class="kpi-v">{{ fmtAmt(kpiData.collection.collected_amount) }}</span></div>
            <div class="kpi-item danger"><span class="kpi-k">其中逾期</span><span class="kpi-v">{{ kpiData.overdue.count }} 笔</span></div>
          </template>
        </template>

        <span v-if="kpiData && summaryData" class="metrics-div"></span>

        <!-- 汇总区：时段合计（本月+本周）；筛选集列合计见表格底部吸底合计行 -->
        <div v-if="summaryData" class="metrics-summary">
          <!-- 时段合计——月/周应收已收，文案随基准日期联动 -->
          <div class="metrics-sum-row">
            <span class="sum-section-lbl alt" :title="`基准日 ${summaryData.ref_date}（取筛选中最晚日期，无筛选则今天）；按应收到期日/回款日期归入对应月、周区间`">时段合计</span>
            <!-- 当期：due_date 落在基准月内 -->
            <div class="kpi-item" :title="`${summaryData.ref_month}内 due_date 到期的预估应收`">
              <span class="kpi-k">{{ summaryData.ref_month }}当期应收</span>
              <span class="kpi-v">{{ fmtAmt(summaryData.month_curr_est) }}</span>
            </div>
            <div class="kpi-item ok" :title="`${summaryData.ref_month}内 payment_date，且到期日在本月及以后的回款`">
              <span class="kpi-k">{{ summaryData.ref_month }}当期已收</span>
              <span class="kpi-v">{{ fmtAmt(summaryData.month_curr_collected) }}</span>
            </div>
            <!-- 逾期：due_date 早于基准月且仍有未收余额 / 回款中对应逾期记录的部分 -->
            <div class="kpi-item warn" :title="`due_date 早于 ${summaryData.ref_month} 且仍有未收余额的记录，outstanding_amount 之和`">
              <span class="kpi-k">{{ summaryData.ref_month }}逾期应收</span>
              <span class="kpi-v">{{ fmtAmt(summaryData.month_overdue_est) }}</span>
            </div>
            <div class="kpi-item ok" :title="`${summaryData.ref_month}内 payment_date，且到期日早于本月（逾期后补收）的回款`">
              <span class="kpi-k">{{ summaryData.ref_month }}逾期已收</span>
              <span class="kpi-v">{{ fmtAmt(summaryData.month_overdue_collected) }}</span>
            </div>
            <span class="metrics-div"></span>
            <div class="kpi-item" :title="`应收到期在 ${summaryData.ref_week} 这一周内的预估金额`">
              <span class="kpi-k">{{ summaryData.ref_week_label }}应收<span class="kpi-sub">{{ summaryData.ref_week }}</span></span>
              <span class="kpi-v">{{ fmtAmt(summaryData.week_est) }}</span>
            </div>
            <div class="kpi-item ok" :title="`回款日期在 ${summaryData.ref_week} 这一周内的实际回款额`">
              <span class="kpi-k">{{ summaryData.ref_week_label }}已收<span class="kpi-sub">{{ summaryData.ref_week }}</span></span>
              <span class="kpi-v">{{ fmtAmt(summaryData.week_collected) }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- ══ 数据明细表（全部/对账/开票/回款 跟踪）══ -->
      <!-- 选择 + 批量操作工具条（选中后出现） -->
      <div v-if="isDataTab && hasSelection && (auth.canDelete || auth.canArWrite)" class="bulk-bar">
        <span class="bulk-n">已选 <strong>{{ selectedCount }}</strong> 条</span>
        <button v-if="pageAllSelected && !selectAllMatching && total > items.length"
          class="bulk-all" @click="selectAllMatching = true">选择全部 {{ total }} 条</button>
        <span v-if="selectAllMatching" class="bulk-all-on">已选中整个筛选集</span>
        <button v-if="auth.canArWrite" class="btn btn-ghost btn-sm" style="margin-left:4px" @click="openBatchAssign">
          设置批次号
        </button>
        <button v-if="auth.canDelete" class="bulk-del" :disabled="bulkDeleting" @click="bulkDelete">
          {{ bulkDeleting ? '删除中…' : `删除选中(${selectedCount})` }}
        </button>
        <button class="bulk-cancel" @click="clearSelection">取消</button>
      </div>

      <!-- ══ 批次管理：合并开票 + 批次回款 一体工作台 ══ -->
      <div v-if="activeTab === 'batch'" class="batch-panel">
        <div class="bp-head">
          <span class="bp-title">🧾 合并开票批次<i v-if="batches.length">{{ batches.length }}</i></span>
          <span class="bp-tip">同批次合并开一张发票 · 回款按批次录入，自动按运作日期先进先出分摊到各记录</span>
          <button class="bp-toggle" @click="showBatchPanel = !showBatchPanel">{{ showBatchPanel ? '收起 ▲' : '展开 ▼' }}</button>
        </div>
        <template v-if="showBatchPanel">
          <div v-if="batchesLoading" class="bp-empty">加载中…</div>
          <div v-else-if="!batches.length" class="bp-empty">
            暂无开票批次——在「全部明细」勾选要合并开票的记录，点「设置批次号」即可
          </div>
          <div v-else class="bp-list">
            <div v-for="b in batches" :key="b.batch_no" class="bp-item">
              <div class="bp-row" @click="toggleBatchExpand(b.batch_no)">
                <span class="bp-no">{{ b.batch_no }}</span>
                <span v-if="b.customers?.length" class="bp-cust" :title="(b.customers || []).join('、')">{{ (b.customers || []).join('、') }}</span>
                <span class="bp-cnt">{{ b.count }} 条</span>
                <span class="bp-amt"><i>上账</i><b>{{ fmtCell(b.estimated) }}</b></span>
                <span class="bp-amt"><i>已开票</i><b>{{ parseFloat(b.invoiced) ? fmtCell(b.invoiced) : '—' }}</b></span>
                <span class="bp-amt ok"><i>已回款</i><b>{{ parseFloat(b.collected) ? fmtCell(b.collected) : '—' }}</b></span>
                <span class="bp-amt warn"><i>未收</i><b>{{ parseFloat(b.outstanding) ? fmtCell(b.outstanding) : '✓ 结清' }}</b></span>
                <span class="bp-acts" @click.stop>
                  <button v-if="auth.canArWrite" class="bp-btn" @click="openBatchInvoice(b)">批次开票</button>
                  <button v-if="auth.canAction('ar_collect') && parseFloat(b.outstanding) > 0" class="bp-btn primary" @click="openBatchPay(b)">批次回款</button>
                  <span class="bp-caret">{{ expandedBatch === b.batch_no ? '▲' : '▼' }}</span>
                </span>
              </div>
              <div v-if="expandedBatch === b.batch_no" class="bp-members">
                <div v-if="batchDetail[b.batch_no]?.collections?.length" class="bp-colls">
                  <div class="bp-colls-head">批次回款记录<i>每行是一次到账的整体分摊，可整次撤销</i></div>
                  <div v-for="(ev, i) in batchDetail[b.batch_no].collections" :key="i" class="bp-coll-row">
                    <span class="bpc-date">{{ ev.payment_date }}</span>
                    <b class="bpc-amt">+{{ fmtCell(ev.total) }}</b>
                    <span class="bpc-n">分摊 {{ ev.count }} 笔</span>
                    <span class="bpc-note" :title="ev.notes">{{ ev.notes }}</span>
                    <button v-if="auth.canAction('ar_collect')" class="bpc-undo" :disabled="batchActing"
                      @click.stop="undoBatchPay(b, ev)">撤销该次回款</button>
                  </div>
                </div>
                <table v-if="batchDetail[b.batch_no]" class="bp-mtable">
                  <thead><tr><th>项目</th><th>运作日期</th><th class="r">上账</th><th class="r">差额调整</th><th class="r">应开(上账+差额)</th><th class="r">已开票</th><th class="r">税额</th><th>开票日期</th><th class="r">已回款</th><th class="r">未收</th></tr></thead>
                  <tbody>
                    <tr v-for="m in batchDetail[b.batch_no].members" :key="m.id">
                      <td>{{ m.short_name }}</td>
                      <td>{{ m.operation_date || '—' }}</td>
                      <td class="r">{{ fmtCell(m.estimated) }}</td>
                      <td class="r" :class="{ 'bp-diff': parseFloat(m.diff) !== 0 }"
                          :title="(m.adjustments || []).map(a => `${a.reason || '未填原因'}: ${a.amount}`).join('\n') || '无调整'">
                        {{ parseFloat(m.diff) !== 0 ? fmtCell(m.diff) : '—' }}<i v-if="(m.adjustments || []).length > 1" class="bp-adj-n">×{{ m.adjustments.length }}</i>
                      </td>
                      <td class="r">{{ fmtCell(m.billable) }}</td>
                      <td class="r">{{ m.invoiced != null ? fmtCell(m.invoiced) : '未开' }}</td>
                      <td class="r" :title="m.invoice_mode === '差额' ? '差额模式：税额手填' : `税率 ${(parseFloat(m.tax_rate) * 100).toFixed(1)}%`">{{ m.tax_amount != null ? fmtCell(m.tax_amount) : '—' }}</td>
                      <td>{{ m.invoice_date || '—' }}</td>
                      <td class="r">{{ parseFloat(m.collected) ? fmtCell(m.collected) : '—' }}</td>
                      <td class="r" :class="parseFloat(m.outstanding) > 0 ? 'bp-out' : 'bp-ok'">{{ parseFloat(m.outstanding) > 0 ? fmtCell(m.outstanding) : '✓' }}</td>
                    </tr>
                  </tbody>
                </table>
                <div v-else class="bp-empty">加载明细…</div>
              </div>
            </div>
          </div>
        </template>
      </div>

      <div v-if="isDataTab" class="table-wrap dt-scroll" style="margin-top:12px">
        <table class="rec-table">
          <thead>
            <tr>
              <th v-if="auth.canDelete" class="sel-col">
                <input type="checkbox" :checked="pageAllSelected"
                  :indeterminate.prop="hasSelection && !pageAllSelected"
                  title="全选本页" @change="toggleSelectPage" />
              </th>
              <th><ColumnFilter label="项目" field="short_name" type="text" :model-value="colFilters.short_name" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('short_name',v)" @sort="o=>setSort('short_name',o)" /></th>
              <th class="ctr"><ColumnFilter label="运作日期" field="operation_date" type="date" :model-value="colFilters.operation_date" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('operation_date',v)" @sort="o=>setSort('operation_date',o)" /></th>

              <!-- all -->
              <template v-if="activeTab === 'all'">
                <th v-if="show('r_estimated_amount')" class="amt"><ColumnFilter label="预估金额" field="estimated_amount" type="number" :model-value="colFilters.estimated_amount" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('estimated_amount',v)" @sort="o=>setSort('estimated_amount',o)" /></th>
                <th v-if="show('r_actual_invoice_amount')" class="amt"><ColumnFilter label="实际开票" field="actual_invoice_amount" type="number" :model-value="colFilters.actual_invoice_amount" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('actual_invoice_amount',v)" @sort="o=>setSort('actual_invoice_amount',o)" /></th>
                <th v-if="show('r_tax_amount')" class="amt"><ColumnFilter label="税额" field="tax_amount" type="number" :model-value="colFilters.tax_amount" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('tax_amount',v)" @sort="o=>setSort('tax_amount',o)" /></th>
                <th v-if="show('r_account_diff')" class="amt"><ColumnFilter label="账实差额" field="account_diff_adjustment" type="number" :model-value="colFilters.account_diff_adjustment" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('account_diff_adjustment',v)" @sort="o=>setSort('account_diff_adjustment',o)" /></th>
                <th v-if="show('r_outstanding')" class="amt"><ColumnFilter label="未收金额" field="outstanding_amount" type="number" :model-value="colFilters.outstanding_amount" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('outstanding_amount',v)" @sort="o=>setSort('outstanding_amount',o)" /></th>
                <th v-if="show('r_due_date')" class="ctr"><ColumnFilter label="应收到期" field="due_date" type="date" :model-value="colFilters.due_date" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('due_date',v)" @sort="o=>setSort('due_date',o)" /></th>
                <th v-if="show('r_due_date')" class="ctr"><ColumnFilter label="目标回款" field="target_collection_date" type="date" :model-value="colFilters.target_collection_date" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('target_collection_date',v)" @sort="o=>setSort('target_collection_date',o)" /></th>
                <th v-if="show('r_reconciliation')" class="ctr"><ColumnFilter label="对账" field="reconciliation_status" type="enum" :single="true" :sortable="false" :options="DIM_OPTS.reconciliation_status" :model-value="dimModel('reconciliation_status')" @update:model-value="v=>onDimCol('reconciliation_status',v)" /></th>
                <th v-if="show('r_payments')" class="ctr">回款</th>
                <th v-if="show('r_payments')" class="ctr" title="预收核销冲抵的次数（点数字查看明细）">预收冲抵</th>
                <th v-if="show('r_payments')" class="ctr" title="事业部间内部往来核销的次数（点数字查看明细）">内部往来</th>
                <th class="ctr"><ColumnFilter label="状态" field="status" type="enum" :single="true" :sortable="false" :options="DIM_OPTS.status" :model-value="dimModel('status')" @update:model-value="v=>onDimCol('status',v)" /></th>
                <th class="ctr"><ColumnFilter label="责任状态" field="responsibility" type="enum" :single="true" :sortable="false" :options="DIM_OPTS.responsibility" :model-value="dimModel('responsibility')" @update:model-value="v=>onDimCol('responsibility',v)" /></th>
                <th v-if="show('r_notes')" class="notes-col"><ColumnFilter label="备注" field="notes" type="text" :model-value="colFilters.notes" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('notes',v)" @sort="o=>setSort('notes',o)" /></th>
              </template>
              <!-- reconciliation -->
              <template v-else-if="activeTab === 'reconciliation'">
                <th v-if="show('r_estimated_amount')" class="amt"><ColumnFilter label="预估金额" field="estimated_amount" type="number" :model-value="colFilters.estimated_amount" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('estimated_amount',v)" @sort="o=>setSort('estimated_amount',o)" /></th>
                <th v-if="show('r_reconciliation')" class="ctr"><ColumnFilter label="对账状态" field="reconciliation_status" type="enum" :single="true" :sortable="false" :options="DIM_OPTS.reconciliation_status" :model-value="dimModel('reconciliation_status')" @update:model-value="v=>onDimCol('reconciliation_status',v)" /></th>
                <th v-if="show('r_reconciliation')" class="ctr"><ColumnFilter label="对账日期" field="reconciliation_date" type="date" :model-value="colFilters.reconciliation_date" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('reconciliation_date',v)" @sort="o=>setSort('reconciliation_date',o)" /></th>
                <th v-if="show('r_due_date')" class="ctr"><ColumnFilter label="应收到期" field="due_date" type="date" :model-value="colFilters.due_date" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('due_date',v)" @sort="o=>setSort('due_date',o)" /></th>
                <th class="ctr"><ColumnFilter label="状态" field="status" type="enum" :single="true" :sortable="false" :options="DIM_OPTS.status" :model-value="dimModel('status')" @update:model-value="v=>onDimCol('status',v)" /></th>
                <th v-if="show('r_outstanding')" class="amt"><ColumnFilter label="未收金额" field="outstanding_amount" type="number" :model-value="colFilters.outstanding_amount" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('outstanding_amount',v)" @sort="o=>setSort('outstanding_amount',o)" /></th>
              </template>
              <!-- invoice -->
              <template v-else-if="activeTab === 'invoice'">
                <th class="ctr"><ColumnFilter label="批次号" field="invoice_batch_no" type="text" :model-value="colFilters.invoice_batch_no" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('invoice_batch_no',v)" @sort="o=>setSort('invoice_batch_no',o)" /></th>
                <th v-if="show('r_estimated_amount')" class="amt"><ColumnFilter label="预估金额" field="estimated_amount" type="number" :model-value="colFilters.estimated_amount" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('estimated_amount',v)" @sort="o=>setSort('estimated_amount',o)" /></th>
                <th v-if="show('r_actual_invoice_amount')" class="amt"><ColumnFilter label="实际开票额" field="actual_invoice_amount" type="number" :model-value="colFilters.actual_invoice_amount" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('actual_invoice_amount',v)" @sort="o=>setSort('actual_invoice_amount',o)" /></th>
                <th v-if="show('r_tax_amount')" class="amt"><ColumnFilter label="税额" field="tax_amount" type="number" :model-value="colFilters.tax_amount" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('tax_amount',v)" @sort="o=>setSort('tax_amount',o)" /></th>
                <th v-if="show('r_invoice_date')" class="ctr"><ColumnFilter label="开票日期" field="invoice_date" type="date" :model-value="colFilters.invoice_date" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('invoice_date',v)" @sort="o=>setSort('invoice_date',o)" /></th>
                <th v-if="show('r_account_diff')" class="amt"><ColumnFilter label="账实差额" field="account_diff_adjustment" type="number" :model-value="colFilters.account_diff_adjustment" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('account_diff_adjustment',v)" @sort="o=>setSort('account_diff_adjustment',o)" /></th>
                <th v-if="show('r_invoice_status')" class="ctr"><ColumnFilter label="开票状态" field="invoice_status" type="enum" :single="true" :sortable="false" :options="DIM_OPTS.invoice_status" :model-value="dimModel('invoice_status')" @update:model-value="v=>onDimCol('invoice_status',v)" /></th>
              </template>
              <!-- collection -->
              <template v-else>
                <th class="amt">应收基础</th>
                <th v-if="show('r_payments')">回款记录</th>
                <th v-if="show('r_outstanding')" class="amt"><ColumnFilter label="未收金额" field="outstanding_amount" type="number" :model-value="colFilters.outstanding_amount" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('outstanding_amount',v)" @sort="o=>setSort('outstanding_amount',o)" /></th>
                <th v-if="show('r_invoice_status')" class="ctr"><ColumnFilter label="回款状态" field="status" type="enum" :single="true" :sortable="false" :options="DIM_OPTS.status" :model-value="dimModel('status')" @update:model-value="v=>onDimCol('status',v)" /></th>
              </template>

              <th class="ctr">操作</th>
            </tr>
          </thead>
          <tbody>
            <template v-if="loading && !items.length">
              <SkeletonRow v-for="n in 8" :key="n" :cols="12" />
            </template>
            <tr v-else-if="loadErr">
              <td colspan="17" class="empty-cell">⚠️ {{ loadErr }} <button style="border:none;background:none;color:var(--primary);cursor:pointer" @click="load()">重试</button></td>
            </tr>
            <tr v-else-if="!items.length">
              <td colspan="17" class="empty-cell">暂无数据</td>
            </tr>
            <template v-for="rec in items" :key="rec.id">
              <tr :class="['data-row', rec.is_overdue ? 'row-overdue' : '', (selectAllMatching || selectedIds.has(rec.id)) ? 'row-sel' : '']">
                <td v-if="auth.canDelete" class="sel-col">
                  <input type="checkbox" :checked="selectAllMatching || selectedIds.has(rec.id)" @change="toggleRow(rec.id)" />
                </td>
                <td>
                  <div class="proj-name" :title="rec.short_name || rec.customer_name">{{ rec.short_name || rec.customer_name }}</div>
                  <div v-if="rec.short_name && rec.short_name !== rec.customer_name" class="proj-sub" :title="rec.customer_name">{{ rec.customer_name }}</div>
                  <div class="proj-no">{{ rec.project_no }}</div>
                </td>
                <td class="ctr">
                  <span class="ym-chip">{{ rec.operation_date || (rec.operation_year + "/" + String(rec.operation_month).padStart(2, "0")) }}</span>
                </td>

                <!-- all -->
                <template v-if="activeTab === 'all'">
                  <td v-if="show('r_estimated_amount')" class="amt fw">{{ fmtCell(rec.estimated_amount) }}</td>
                  <td v-if="show('r_actual_invoice_amount')" class="amt">{{ rec.actual_invoice_amount ? fmtCell(rec.actual_invoice_amount) : '—' }}</td>
                  <td v-if="show('r_tax_amount')" class="amt text-muted">{{ rec.tax_amount ? fmtCell(rec.tax_amount) : '—' }}</td>
                  <td v-if="show('r_account_diff')" class="amt">{{ parseFloat(rec.account_diff_adjustment) !== 0 ? fmtCell(rec.account_diff_adjustment) : '—' }}</td>
                  <td v-if="show('r_outstanding')" class="amt" :class="parseFloat(rec.outstanding_amount) > 0 ? 'amt-warn' : 'amt-zero'">{{ parseFloat(rec.outstanding_amount) > 0 ? fmtCell(rec.outstanding_amount) : '—' }}</td>
                  <td v-if="show('r_due_date')" class="ctr text-sm-muted">{{ rec.due_date || '—' }}</td>
                  <td v-if="show('r_due_date')" class="ctr text-sm-muted">{{ rec.target_collection_date || '—' }}</td>
                  <td v-if="show('r_reconciliation')" class="ctr">
                    <span :class="['status-pill', rec.reconciliation_status === '已对账' ? 'pill-ok' : 'pill-warn']">{{ rec.reconciliation_status === '已对账' ? '✓ 已对账' : '○ 未对账' }}</span>
                  </td>
                  <td v-if="show('r_payments')" class="ctr">
                    <span class="pay-count" :class="rec.payments?.length ? 'count-has' : 'count-none'">{{ rec.payments?.length || 0 }}</span>
                  </td>
                  <td v-if="show('r_payments')" class="ctr">
                    <button class="pay-toggle" :title="offsetCount(rec) ? '点击展开查看预收抵扣明细' : '无预收冲抵'" @click="togglePayments(rec.id)">
                      <span class="pay-count" :class="offsetCount(rec) ? 'count-offset' : 'count-none'">{{ offsetCount(rec) }}</span>
                    </button>
                  </td>
                  <td v-if="show('r_payments')" class="ctr">
                    <button class="pay-toggle" :title="internalCount(rec) ? '点击展开查看内部往来核销明细' : '无内部往来核销'" @click="togglePayments(rec.id)">
                      <span class="pay-count" :class="internalCount(rec) ? 'count-internal' : 'count-none'">{{ internalCount(rec) }}</span>
                    </button>
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
                  <td v-if="show('r_estimated_amount')" class="amt fw">{{ fmtCell(rec.estimated_amount) }}</td>
                  <td v-if="show('r_reconciliation')" class="ctr">
                    <span :class="['status-pill', rec.reconciliation_status === '已对账' ? 'pill-ok' : 'pill-warn']">{{ rec.reconciliation_status === '已对账' ? '✓ 已对账' : '○ 未对账' }}</span>
                  </td>
                  <td v-if="show('r_reconciliation')" class="ctr text-sm-muted">{{ rec.reconciliation_date || '—' }}</td>
                  <td v-if="show('r_due_date')" class="ctr text-sm-muted">{{ rec.due_date || '—' }}</td>
                  <td class="ctr">
                    <span v-if="rec.is_overdue" class="status-pill pill-danger">逾期{{ rec.overdue_days }}天</span>
                    <span v-else-if="rec.is_current" class="status-pill pill-blue">当期</span>
                    <span v-else-if="rec.invoice_status === '已结清'" class="status-pill pill-ok">已结清</span>
                    <span v-else class="status-pill pill-muted">未到期</span>
                  </td>
                  <td v-if="show('r_outstanding')" class="amt" :class="parseFloat(rec.outstanding_amount) > 0 ? 'amt-warn' : 'amt-zero'">{{ parseFloat(rec.outstanding_amount) > 0 ? fmtCell(rec.outstanding_amount) : '—' }}</td>
                </template>

                <!-- invoice -->
                <template v-else-if="activeTab === 'invoice'">
                  <td class="ctr">
                    <span v-if="rec.invoice_batch_no" class="batch-badge" :title="`合并开票批次：${rec.invoice_batch_no}`">{{ rec.invoice_batch_no }}</span>
                    <span v-else class="text-sm-muted">—</span>
                  </td>
                  <td v-if="show('r_estimated_amount')" class="amt text-muted">{{ fmtCell(rec.estimated_amount) }}</td>
                  <td v-if="show('r_actual_invoice_amount')" class="amt fw">{{ rec.actual_invoice_amount ? fmtCell(rec.actual_invoice_amount) : '—' }}</td>
                  <td v-if="show('r_tax_amount')" class="amt text-muted">{{ rec.tax_amount ? fmtCell(rec.tax_amount) : '—' }}</td>
                  <td v-if="show('r_invoice_date')" class="ctr text-sm-muted">{{ rec.invoice_date || '—' }}</td>
                  <td v-if="show('r_account_diff')" class="amt">{{ parseFloat(rec.account_diff_adjustment) !== 0 ? fmtCell(rec.account_diff_adjustment) : '—' }}</td>
                  <td v-if="show('r_invoice_status')" class="ctr">
                    <span :class="['status-pill', rec.invoice_status === '已结清' ? 'pill-ok' : rec.invoice_status === '部分回款' ? 'pill-blue' : rec.invoice_status === '已开票' ? 'pill-warn' : 'pill-muted']">{{ rec.invoice_status === '已开票' ? '✓ 已开票' : rec.invoice_status === '未开票' ? '○ 未开票' : rec.invoice_status }}</span>
                  </td>
                </template>

                <!-- collection -->
                <template v-else>
                  <td class="amt fw">{{ fmtCell(rec.actual_invoice_amount || rec.estimated_amount) }}</td>
                  <td v-if="show('r_payments')">
                    <button class="pay-toggle" @click="togglePayments(rec.id)">
                      <span class="pay-count" :class="rec.payments?.length ? 'count-has' : 'count-none'">{{ rec.payments?.length || 0 }}</span>
                      <span style="font-size:12px;color:var(--muted)">{{ rec.payments?.length ? '笔回款' : '无回款' }}</span>
                      <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" style="margin-left:3px;color:var(--muted)" :style="expandedPayments[rec.id] ? 'transform:rotate(180deg)' : ''"><path d="M6 9l6 6 6-6"/></svg>
                    </button>
                    <button v-if="auth.canAction('ar_collect')" class="add-pay-btn" @click="openAddPayment(rec)">+ 回款</button>
                  </td>
                  <td v-if="show('r_outstanding')" class="amt" :class="parseFloat(rec.outstanding_amount) > 0 ? 'amt-warn' : 'amt-zero'">{{ parseFloat(rec.outstanding_amount) > 0 ? fmtCell(rec.outstanding_amount) : '—' }}</td>
                  <td v-if="show('r_invoice_status')" class="ctr">
                    <span :class="['status-pill', rec.invoice_status === '已结清' ? 'pill-ok' : rec.invoice_status === '部分回款' ? 'pill-blue' : rec.invoice_status === '已开票' ? 'pill-warn' : 'pill-muted']">{{ rec.invoice_status === '已开票' ? '✓ 已开票' : rec.invoice_status === '未开票' ? '○ 未开票' : rec.invoice_status }}</span>
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

              <!-- Payment detail rows (collection / all tab — 含预收抵扣来源标识) -->
              <template v-if="(activeTab === 'collection' || activeTab === 'all') && show('r_payments') && expandedPayments[rec.id]">
                <tr v-if="!rec.payments?.length" class="pay-row">
                  <td :colspan="99" class="pay-empty">暂无回款记录</td>
                </tr>
                <tr v-else v-for="pay in rec.payments" :key="pay.id" class="pay-row">
                  <td :colspan="99">
                    <div class="pay-detail">
                      <span class="pay-no">第{{ pay.payment_no }}次</span>
                      <span class="pay-amt">{{ fmtCell(pay.amount) }}</span>
                      <span class="pay-date">{{ pay.payment_date }}</span>
                      <span v-if="pay.source === '预收抵扣'" class="pay-src" title="由预收核销生成；删除即反向核销，预收余额恢复">预收抵扣</span>
                      <span v-else-if="pay.source === '内部往来'" class="pay-src pay-src-internal" :title="`事业部间内部往来核销（不计现金）· 往来部门：${pay.counterparty_dept || '—'}`">内部往来 · {{ pay.counterparty_dept || '—' }}</span>
                      <span v-if="pay.notes" class="pay-notes">{{ pay.notes }}</span>
                      <button v-if="pay.source === '预收抵扣' ? auth.canAction('wo_receive') : auth.canDelete" class="pay-del" @click="deletePayment(rec, pay)">
                        {{ pay.source === '预收抵扣' ? '撤销核销' : '删除' }}</button>
                    </div>
                  </td>
                </tr>
              </template>
            </template>
          </tbody>
        </table>
      </div>

      <!-- 吸底合计 + 翻页：Teleport 到 body 以逃脱 .card transform 产生的 fixed 包含块 -->
      <Teleport to="body">
        <div v-if="isDataTab && !showModal && (summaryData || total > size)" class="bottom-bar">
          <div v-if="summaryData" class="bb-summary">
            <span class="bb-item"><i>合计</i><b>{{ summaryData.count }}</b> 条</span>
            <span v-if="show('r_estimated_amount')" class="bb-item"><i>预估</i><b>{{ fmtCell(summaryData.estimated) }}</b></span>
            <span v-if="show('r_actual_invoice_amount')" class="bb-item"><i>开票</i><b>{{ fmtCell(summaryData.invoiced) }}</b></span>
            <span v-if="show('r_tax_amount')" class="bb-item"><i>税额</i><b>{{ fmtCell(summaryData.tax) }}</b></span>
            <span v-if="show('r_payments')" class="bb-item ok"><i>已收</i><b>{{ fmtCell(summaryData.collected) }}</b></span>
            <span v-if="show('r_outstanding')" class="bb-item warn"><i>未收</i><b>{{ fmtCell(summaryData.outstanding) }}</b></span>
          </div>
          <div v-if="total > size" class="bb-pager">
            <button :disabled="page <= 1" class="page-btn" @click="page--; load()">‹ 上一页</button>
            <span class="page-info">{{ page }} / {{ Math.ceil(total / size) }} 页 · 共 {{ total }} 条</span>
            <button :disabled="page * size >= total" class="page-btn" @click="page++; load()">下一页 ›</button>
            <span class="pg-jump">到第<input type="number" v-model.number="jumpPage" :min="1" class="pg-jump-input" :placeholder="`1-${Math.ceil(total / size)}`" @keyup.enter="doJump" />页</span>
          </div>
        </div>
      </Teleport>

      <!-- ══ 催款工作台 ══ -->
      <!-- ══ 预收核销工作台 ══ -->
      <div v-if="activeTab === 'offset'" class="ow-wrap">
        <div class="ow-head">
          <div class="quick-search" style="max-width:260px">
            <svg class="qs-ico" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>
            <input v-model="owQ" class="qs-input" placeholder="搜客户名" @input="onOwSearch" />
          </div>
          <span class="ow-tip">有预收余额且名下有未收应收的客户。勾选应收明细 → 选一笔预收 → 按运作日期先进先出批量冲抵；逐条核销可在「回款跟踪」录入回款时操作</span>
        </div>
        <div v-if="owLoading" class="empty-cell" style="padding:30px;text-align:center">⏳ 加载中…</div>
        <div v-else-if="!owGroups.length" class="empty-cell" style="padding:30px;text-align:center">
          暂无可核销项——没有「预收有余额 且 名下有未收应收」的客户
        </div>
        <div v-else class="ow-groups">
          <div v-for="g in owGroups" :key="g.customer" class="ow-card">
            <div class="ow-card-head">
              <span class="ow-cust">{{ g.customer }}</span>
              <span class="ow-stat"><i>预收余额</i><b class="ok">{{ fmtCell(g.total_balance) }}</b></span>
              <span class="ow-stat"><i>未收应收</i><b class="warn">{{ fmtCell(g.total_outstanding) }}</b></span>
              <span class="ow-stat"><i>可冲抵</i><b>{{ fmtCell(g.offsettable) }}</b></span>
              <button v-if="auth.canAction('wo_receive')" class="btn btn-primary btn-sm" style="margin-left:auto"
                :disabled="!owSelCount(g.customer)" @click="openBatchWriteoff(g)">
                批量核销{{ owSelCount(g.customer) ? `（已选 ${owSelCount(g.customer)} 条）` : '' }}
              </button>
            </div>
            <div class="ow-advances">
              <span v-for="a in g.advances" :key="a.id" class="ow-adv-chip" :title="`往来单位：${a.counterparty || '—'} · ${a.delivery_dept}`">
                预收 {{ a.occur_date || '—' }}<template v-if="a.short_name">·{{ a.short_name }}</template>
                <b>{{ fmtCell(a.balance_amount) }}</b>
              </span>
            </div>
            <table class="ow-table">
              <thead><tr>
                <th class="sel-col"><input type="checkbox" :checked="g.records.length > 0 && g.records.every(r => (owSel[g.customer] || new Set()).has(r.id))" title="全选" @change="owToggleAll(g)" /></th>
                <th>项目</th><th>运作日期</th><th>应收到期</th><th class="amt">上账</th><th class="amt">未收</th>
              </tr></thead>
              <tbody>
                <tr v-for="r in g.records" :key="r.id" :class="{ 'row-sel': (owSel[g.customer] || new Set()).has(r.id) }" @click="owToggle(g.customer, r.id)">
                  <td class="sel-col"><input type="checkbox" :checked="(owSel[g.customer] || new Set()).has(r.id)" @click.stop @change="owToggle(g.customer, r.id)" /></td>
                  <td>{{ r.short_name }}</td>
                  <td>{{ r.operation_date || '—' }}</td>
                  <td>{{ r.due_date || '—' }}</td>
                  <td class="amt">{{ fmtCell(r.estimated) }}</td>
                  <td class="amt amt-warn">{{ fmtCell(r.outstanding) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div v-if="activeTab === 'dunning'">
        <div class="filter-strip" style="margin-top:4px">
          <select v-model="dunFilters.dept" class="sel-bu" @change="loadDunning(true)">
            <option value="">全部事业部</option>
            <option v-for="d in accessibleDepts" :key="d" :value="d">{{ d }}</option>
          </select>
          <input v-model="dunFilters.q" placeholder="搜项目 / 客户 / 对接人" class="search-input" @input="onDunSearch" />
          <span v-if="dunSummary" class="text-sm-muted" style="margin-left:auto">
            当前范围逾期 <strong>{{ dunSummary.count }}</strong> 笔 / <strong style="color:#c62828">{{ fmtAmt(dunSummary.amount) }}</strong>
          </span>
        </div>

        <!-- 账龄分桶卡片（点击筛选） -->
        <div class="dun-buckets">
          <button v-for="b in dunBuckets" :key="b.key"
            class="dun-bucket" :class="{ on: dunFilters.bucket === b.key, empty: !b.count }"
            @click="toggleDunBucket(b.key)">
            <div class="db-label">逾期{{ b.label }}</div>
            <div class="db-count">{{ b.count }} 笔</div>
            <div class="db-amt">{{ fmtAmt(b.amount) }}</div>
          </button>
        </div>

        <!-- 责任人聚合 chips（点击筛选） -->
        <div v-if="dunContacts.length" class="dun-contacts">
          <span class="dc-label">按销售对接人：</span>
          <button v-for="c in dunContacts.slice(0, 12)" :key="c.sales_contact"
            class="dc-chip" :class="{ on: dunFilters.contact === c.sales_contact }"
            :title="`最长逾期 ${c.max_overdue_days} 天`"
            @click="toggleDunContact(c.sales_contact)">
            {{ c.sales_contact }} · {{ c.count }}笔 · {{ fmtAmt(c.amount) }}
          </button>
        </div>

        <!-- 批量生成催款任务工具条 -->
        <div v-if="auth.canArWrite && dunSelected.size" class="bulk-bar">
          <span class="bulk-n">已选 <strong>{{ dunSelected.size }}</strong> 条</span>
          <button class="btn btn-primary btn-sm" :disabled="dunCreating" @click="createDunningTasks">
            {{ dunCreating ? '生成中…' : '⚡ 生成催款任务' }}
          </button>
          <span class="text-sm-muted">生成后出现在 财务驾驶舱 → 决策行动，负责人默认为销售对接人</span>
        </div>

        <div class="table-wrap" style="margin-top:12px">
          <table class="rec-table">
            <thead>
              <tr>
                <th v-if="auth.canArWrite" class="sel-col">
                  <input type="checkbox" :checked="dunPageAllSelected" @change="toggleDunSelectPage" />
                </th>
                <th>项目 / 客户</th>
                <th class="ctr">交付部门</th>
                <th class="ctr">运作日期</th>
                <th class="ctr">应收日期</th>
                <th class="ctr">逾期天数</th>
                <th class="amt">未收金额</th>
                <th class="ctr">销售对接人</th>
                <th class="ctr">最近回款</th>
                <th class="ctr">催款任务</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="dunLoading && !dunItems.length"><td colspan="10" class="empty-cell">⏳ 加载中…</td></tr>
              <tr v-else-if="!dunItems.length"><td colspan="10" class="empty-cell">🎉 当前范围内没有逾期应收</td></tr>
              <tr v-for="r in dunItems" :key="r.id" class="data-row">
                <td v-if="auth.canArWrite" class="sel-col">
                  <input type="checkbox" :disabled="!!r.open_action_id"
                         :checked="dunSelected.has(r.id)" @change="toggleDunRow(r.id)" />
                </td>
                <td>
                  <div class="proj-name">{{ r.short_name || r.customer_name }}</div>
                  <div class="proj-no">{{ r.project_no }} · {{ r.customer_name }}</div>
                </td>
                <td class="ctr text-sm-muted">{{ r.delivery_dept }}</td>
                <td class="ctr"><span class="ym-chip">{{ r.operation_date || (r.operation_year + "/" + String(r.operation_month).padStart(2, "0")) }}</span></td>
                <td class="ctr text-sm-muted">{{ r.due_date }}</td>
                <td class="ctr"><span class="od-badge" :class="overdueClass(r.overdue_days)">{{ r.overdue_days }}天</span></td>
                <td class="amt fw" style="color:#c62828">{{ fmtAmt(r.outstanding_amount) }}</td>
                <td class="ctr text-sm-muted">{{ r.sales_contact || '—' }}</td>
                <td class="ctr text-sm-muted">{{ r.last_payment_date || '—' }}</td>
                <td class="ctr">
                  <span v-if="r.open_action_id" class="dun-has-action" title="已有未关闭的催款行动项">✓ 已建</span>
                  <span v-else class="text-sm-muted">—</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div v-if="dunTotal > size" class="pagination">
          <button :disabled="dunPage <= 1" class="page-btn" @click="dunPage--; loadDunning()">‹ 上一页</button>
          <span class="page-info">{{ dunPage }} / {{ Math.ceil(dunTotal / size) }} 页 · 共 {{ dunTotal }} 条</span>
          <button :disabled="dunPage * size >= dunTotal" class="page-btn" @click="dunPage++; loadDunning()">下一页 ›</button>
        </div>
      </div>

      <!-- ══ 回款流水 ══ -->
      <div v-if="activeTab === 'payments'">
        <div class="filter-strip" style="margin-top:4px">
          <label class="pay-range-lbl">回款日期</label>
          <button v-for="r in PAY_RANGE_PRESETS" :key="r.key || 'all'" type="button"
                  class="pay-range-chip" :class="{ on: payRangePreset === r.key }"
                  @click="setPayRange(r.key)">{{ r.label }}</button>
          <input v-model="payFilters.pay_start" type="date" class="sel-mo" @change="onPayDateChange" />
          <span style="color:var(--muted)">~</span>
          <input v-model="payFilters.pay_end" type="date" class="sel-mo" @change="onPayDateChange" />
          <select v-model="payFilters.dept" class="sel-bu" @change="loadPayments(true)">
            <option value="">全部事业部</option>
            <option v-for="d in accessibleDepts" :key="d" :value="d">{{ d }}</option>
          </select>
          <select v-model="payFilters.source" class="sel-bu" @change="loadPayments(true)" title="按回款来源筛选">
            <option value="">全部来源</option>
            <option value="回款">现金回款</option>
            <option value="预收抵扣">预收抵扣</option>
            <option value="内部往来">内部往来</option>
          </select>
          <input v-model="payFilters.q" placeholder="搜索项目" class="search-input" @input="loadPayments(true)" />
          <button class="btn btn-ghost btn-sm" :disabled="payExporting" @click="exportPayments">↓ 导出</button>
        </div>

        <div v-if="paySummary" class="totals-strip">
          <span class="tot-label">区间合计</span>
          <span class="tot-item"><i>笔数</i>{{ paySummary.count }}</span>
          <span class="tot-item tot-green"><i>回款总额</i>{{ fmtCell(paySummary.total_amount) }}</span>
        </div>

        <div class="table-wrap" style="margin-top:12px">
          <table class="rec-table">
            <thead>
              <tr>
                <th class="ctr">回款日期</th>
                <th class="amt">金额</th>
                <th class="ctr">来源</th>
                <th>项目</th>
                <th class="ctr">交付部门</th>
                <th class="ctr">运作日期</th>
                <th class="ctr">序号</th>
                <th>备注</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="payLoading && !payItems.length"><td colspan="8" class="empty-cell">⏳ 加载中…</td></tr>
              <tr v-else-if="!payItems.length"><td colspan="8" class="empty-cell">暂无回款记录</td></tr>
              <tr v-for="p in payItems" :key="p.id" class="data-row">
                <td class="ctr text-sm-muted">{{ p.payment_date }}</td>
                <td class="amt fw" :style="{ color: p.source === '内部往来' ? '#6a1b9a' : '#2e7d32' }">{{ fmtCell(p.amount) }}</td>
                <td class="ctr">
                  <span v-if="p.source === '内部往来'" class="pay-src pay-src-internal" :title="`往来部门：${p.counterparty_dept || '—'}（不计现金）`">内部往来 · {{ p.counterparty_dept || '—' }}</span>
                  <span v-else-if="p.source === '预收抵扣'" class="pay-src">预收抵扣</span>
                  <span v-else class="text-sm-muted">现金回款</span>
                </td>
                <td>
                  <div class="proj-name">{{ p.short_name || '—' }}</div>
                  <div class="proj-no">{{ p.project_no }}</div>
                </td>
                <td class="ctr text-sm-muted">{{ p.delivery_dept }}</td>
                <td class="ctr"><span class="ym-chip">{{ p.operation_date || (p.operation_year + "/" + String(p.operation_month).padStart(2, "0")) }}</span></td>
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
                <th class="amt" title="应收口径：含预收抵扣；纯现金口径见 现金流分析 / 资金池">已收总额</th>
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
    <!-- 编辑/新增态：点遮罩不关闭，避免填一半误点丢失；仅「保存/取消/✕」可退出 -->
    <Teleport to="body">
      <div v-if="showModal" class="modal-overlay">
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
                       placeholder="输入项目编号 / 简称 / 客户名称 / 负责人 模糊搜索"
                       :disabled="!!editRec"
                       @input="onProjectKeywordInput" />
                <select v-model="recForm.project_id" :disabled="!!editRec">
                  <option value="" disabled>{{ projectSearching ? '搜索中…' : (projects.length ? '请选择项目' : '无匹配项目') }}</option>
                  <option v-for="p in projects" :key="p.id" :value="p.id">
                    {{ p.project_no }} · {{ p.short_name || p.customer_name }}
                  </option>
                </select>
              </label>
              <label class="form-field">
                <span>运作日期 <em>*</em></span>
                <input v-model="recForm.operation_date" type="date"
                       title="应收发生日期；修改后将按项目账期重算应收日期" />
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
                <span>目标回款日期（选填）</span>
                <input v-model="recForm.target_collection_date" type="date" title="业务手工设定的回款目标，与系统按账期推算的应收到期并行" />
              </label>
              <!-- 新建：初始差额+原因；编辑：调整明细管理器（多次、各带原因金额） -->
              <template v-if="!editRec">
                <label class="form-field">
                  <span>差额调整（选填）</span>
                  <input v-model="recForm.account_diff_adjustment" type="number" step="0.01" placeholder="可正可负" />
                </label>
                <label class="form-field">
                  <span>差额原因</span>
                  <input v-model="recForm.adjustment_reason" placeholder="如：运费差/客户扣款/补付" maxlength="200" />
                </label>
              </template>
              <div v-else class="form-field span2 adj-box">
                <span>差额调整明细<i class="adj-total">合计 {{ adjTotal.toFixed(2) }}（未收 = 上账 + 差额合计 − 已回款）</i></span>
                <div v-if="adjList.length" class="adj-list">
                  <div v-for="a in adjList" :key="a.id" class="adj-item">
                    <b :class="parseFloat(a.amount) >= 0 ? 'adj-pos' : 'adj-neg'">{{ parseFloat(a.amount) >= 0 ? '+' : '' }}{{ a.amount }}</b>
                    <span class="adj-reason" :title="a.reason">{{ a.reason || '未填原因' }}</span>
                    <em v-if="a.adjust_date">{{ a.adjust_date }}</em>
                    <em v-if="a.created_by_name">{{ a.created_by_name }}</em>
                    <button type="button" class="adj-del" title="删除该笔调整" @click="removeAdjustment(a)">✕</button>
                  </div>
                </div>
                <div v-else class="adj-empty">暂无调整——金额与原因逐笔记录，可多次追加</div>
                <div class="adj-add">
                  <input v-model="adjForm.amount" type="number" step="0.01" placeholder="金额（可负）" class="adj-amt-inp" />
                  <input v-model="adjForm.reason" placeholder="原因（必填，如：运费差/客户扣款）" maxlength="200" class="adj-reason-inp" />
                  <button type="button" class="btn btn-ghost btn-sm" :disabled="adjBusy" @click="addAdjustment">
                    {{ adjBusy ? '…' : '＋ 追加调整' }}
                  </button>
                </div>
              </div>
              <label class="form-field span2">
                <span>开票批次号<span style="color:var(--muted);font-size:11px;margin-left:4px">合并开票时多条填同一批次号，留空=单独开票</span></span>
                <input v-model="recForm.invoice_batch_no" placeholder="如 PF-2026-001" />
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

      <!-- Batch-Assign Modal — 批量设置开票批次号 -->
      <div v-if="showBatchModal" class="modal-overlay" @click.self="showBatchModal = false">
        <div class="modal-box" style="max-width:400px">
          <div class="modal-header">
            <h3>设置开票批次号</h3>
            <button class="modal-close" @click="showBatchModal = false">✕</button>
          </div>
          <div class="modal-body">
            <p style="font-size:13px;color:var(--muted);margin-bottom:12px">
              将 <strong>{{ selectedCount }}</strong> 条记录归入同一开票批次（同批次合并开一张发票，批次回款自动分摊）。
            </p>
            <div class="bm-modes">
              <label class="bm-opt" :class="{ on: batchMode === 'auto' }">
                <input type="radio" value="auto" v-model="batchMode" />
                <div>
                  <b>自动生成批次号（推荐）</b>
                  <i>系统按「客户简称-日期-序号」命名，如 华为物流-260612-01，见号知义、无需记编码</i>
                </div>
              </label>
              <label class="bm-opt" :class="{ on: batchMode === 'existing' }">
                <input type="radio" value="existing" v-model="batchMode" />
                <div>
                  <b>并入已有批次</b>
                  <i>追加到之前合并的批次（如同客户当月新增了几条记录）</i>
                  <select v-if="batchMode === 'existing'" v-model="batchExisting" style="margin-top:6px;width:100%">
                    <option value="">— 选择批次 —</option>
                    <option v-for="b in batchExistingList" :key="b.batch_no" :value="b.batch_no">
                      {{ b.batch_no }}（{{ (b.customers || []).join('、') || '—' }} · {{ b.count }}条）
                    </option>
                  </select>
                </div>
              </label>
              <label class="bm-opt" :class="{ on: batchMode === 'custom' }">
                <input type="radio" value="custom" v-model="batchMode" />
                <div>
                  <b>自定义 / 清空</b>
                  <i>手工输入批次号；留空提交 = 把所选记录移出批次</i>
                  <input v-if="batchMode === 'custom'" v-model="batchNoInput"
                         placeholder="自定义批次号（留空=清除批次）" style="margin-top:6px;width:100%" />
                </div>
              </label>
            </div>
          </div>
          <div class="modal-footer">
            <button class="btn btn-ghost" @click="showBatchModal = false">取消</button>
            <button class="btn btn-primary" :disabled="batchAssigning" @click="confirmBatchAssign">
              {{ batchAssigning ? '设置中…' : '确认设置' }}
            </button>
          </div>
        </div>
      </div>

      <!-- Batch-Invoice Modal — 金额级分批开票（多次开票事件，先进先出分摊） -->
      <div v-if="showBatchInvoice" class="modal-overlay">
        <div class="modal-box" style="max-width:620px">
          <div class="modal-header">
            <h3>批次开票 — {{ batchTarget?.batch_no }}</h3>
            <button class="modal-close" @click="showBatchInvoice = false">✕</button>
          </div>
          <div class="modal-body">
            <p style="font-size:12.5px;color:var(--muted);margin-bottom:10px">
              <strong>可多次开票</strong>：每次填日期+金额（+税额），系统按运作日期先进先出分摊到各记录的
              可开余额；累计开票不超过「上账+差额」合计即可。全额模式税额按各记录项目税率自动算，
              差额模式可在下方填本次手填税额（按分摊占比落到差额模式记录）。
            </p>

            <!-- 已开票事件 -->
            <div v-if="invDetail?.invoice_events?.length" class="bi-events">
              <div class="bi-events-head">开票记录<i>每行一次开票，可整次撤销</i></div>
              <div v-for="ev in invDetail.invoice_events" :key="ev.id" class="bi-ev-row">
                <span class="bie-date">{{ ev.invoice_date }}</span>
                <b class="bie-amt">{{ fmtCell(ev.amount) }}</b>
                <span v-if="ev.tax_amount != null" class="bie-tax">税 {{ fmtCell(ev.tax_amount) }}</span>
                <span class="bie-note" :title="ev.notes">{{ ev.notes }}</span>
                <button class="bie-undo" :disabled="batchActing" @click="undoBatchInvoice(ev)">撤销</button>
              </div>
            </div>

            <!-- 新增开票 -->
            <div class="bi-add">
              <div class="bi-add-head">新增开票
                <span class="bi-room">批次可开余额 <b>{{ invRoom.toFixed(2) }}</b>（上账+差额合计 − 累计已开）</span>
              </div>
              <div class="form-grid">
                <label class="form-field">
                  <span>开票日期*</span>
                  <input v-model="batchInvForm.invoice_date" type="date" />
                </label>
                <label class="form-field">
                  <span>开票金额*（价税合计）</span>
                  <input v-model="batchInvForm.amount" type="number" step="0.01" :placeholder="`≤ ${invRoom.toFixed(2)}`" />
                </label>
                <label class="form-field">
                  <span>税额（选填，差额模式手填）</span>
                  <input v-model="batchInvForm.tax_amount" type="number" step="0.01" placeholder="全额模式自动算，无需填" />
                </label>
                <label class="form-field">
                  <span>备注（选填）</span>
                  <input v-model="batchInvForm.notes" placeholder="如：发票号 044001900111" maxlength="200" />
                </label>
              </div>
            </div>

            <!-- 成员可开余额 -->
            <table v-if="invDetail" class="bp-mtable" style="margin-top:12px">
              <thead><tr><th>项目</th><th>运作日期</th><th class="r">应开(上账+差额)</th><th class="r">已开票</th><th class="r">剩余可开</th><th class="r">税率</th><th class="r">税额</th></tr></thead>
              <tbody>
                <tr v-for="m in invDetail.members" :key="m.id" :style="parseFloat(m.invoice_room) > 0 ? '' : 'opacity:.55'">
                  <td>{{ m.short_name }}</td><td>{{ m.operation_date || '—' }}</td>
                  <td class="r">{{ fmtCell(m.billable) }}</td>
                  <td class="r">{{ m.invoiced != null ? fmtCell(m.invoiced) : '—' }}</td>
                  <td class="r" :class="parseFloat(m.invoice_room) > 0 ? 'bp-out' : 'bp-ok'">{{ parseFloat(m.invoice_room) > 0 ? fmtCell(m.invoice_room) : '✓ 开满' }}</td>
                  <td class="r">{{ parseFloat(m.tax_rate) ? (parseFloat(m.tax_rate) * 100).toFixed(1) + '%' : '—' }}</td>
                  <td class="r">{{ m.tax_amount != null ? fmtCell(m.tax_amount) : (m.invoice_mode === '差额' ? '手填' : '—') }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="modal-footer">
            <button class="btn btn-ghost" @click="showBatchInvoice = false">关闭</button>
            <button class="btn btn-primary" :disabled="batchActing || !batchInvForm.invoice_date || !(parseFloat(batchInvForm.amount) > 0)" @click="doBatchInvoice">
              {{ batchActing ? '落账中…' : '确认开票落账' }}
            </button>
          </div>
        </div>
      </div>

      <!-- Batch-Payment Modal — 批次回款自动分摊 -->
      <div v-if="showBatchPay" class="modal-overlay">
        <div class="modal-box" style="max-width:560px">
          <div class="modal-header">
            <h3>批次回款 — {{ batchTarget?.batch_no }}</h3>
            <button class="modal-close" @click="showBatchPay = false">✕</button>
          </div>
          <div class="modal-body">
            <template v-if="!batchPayResult">
              <p style="font-size:12.5px;color:var(--muted);margin-bottom:10px">
                一张发票到一笔钱，不用再手工拆账：金额将按<strong>运作日期先进先出</strong>自动分摊到批次内仍有未收的记录。
                可多次录入（部分回款），每次从未结清的记录继续分摊。
                批次未收合计 <strong>{{ fmtCell(batchTarget?.outstanding) }}</strong> 元。
              </p>
              <div class="form-grid">
                <label class="form-field">
                  <span>回款金额*（元）</span>
                  <input v-model="batchPayForm.amount" type="number" step="0.01" :placeholder="`≤ ${batchTarget?.outstanding}`" />
                </label>
                <label class="form-field">
                  <span>回款日期*</span>
                  <input v-model="batchPayForm.payment_date" type="date" />
                </label>
                <label class="form-field span2">
                  <span>备注（选填）</span>
                  <input v-model="batchPayForm.notes" placeholder="如：建行到账，回单号xxx" />
                </label>
              </div>
            </template>
            <template v-else>
              <p style="font-size:13px;color:#2e7d32;font-weight:600;margin-bottom:10px">✓ {{ batchPayResult.message }}</p>
              <table class="bp-mtable">
                <thead><tr><th>项目</th><th>运作日期</th><th class="r">本次分摊</th><th class="r">分摊后未收</th></tr></thead>
                <tbody>
                  <tr v-for="a in batchPayResult.allocations" :key="a.record_id">
                    <td>{{ a.short_name }}</td><td>{{ a.operation_date || '—' }}</td>
                    <td class="r" style="color:#2e7d32;font-weight:600">+{{ fmtCell(a.allocated) }}</td>
                    <td class="r" :class="parseFloat(a.outstanding_after) > 0 ? 'bp-out' : 'bp-ok'">
                      {{ parseFloat(a.outstanding_after) > 0 ? fmtCell(a.outstanding_after) : '✓ 结清' }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </template>
          </div>
          <div class="modal-footer">
            <template v-if="!batchPayResult">
              <button class="btn btn-ghost" @click="showBatchPay = false">取消</button>
              <button class="btn btn-primary" :disabled="batchActing || !(parseFloat(batchPayForm.amount) > 0) || !batchPayForm.payment_date" @click="doBatchPay">
                {{ batchActing ? '分摊中…' : '确认回款并自动分摊' }}
              </button>
            </template>
            <button v-else class="btn btn-primary" @click="showBatchPay = false">完成</button>
          </div>
        </div>
      </div>

      <!-- Batch-Writeoff Modal — 预收批量核销（先进先出分摊） -->
      <div v-if="showWoModal" class="modal-overlay">
        <div class="modal-box" style="max-width:560px">
          <div class="modal-header">
            <h3>预收批量核销 — {{ woTarget?.customer }}</h3>
            <button class="modal-close" @click="showWoModal = false">✕</button>
          </div>
          <div class="modal-body">
            <template v-if="!woResult">
              <p style="font-size:12.5px;color:var(--muted);margin-bottom:10px">
                选一笔预收，金额按<strong>运作日期先进先出</strong>自动分摊到已勾选的 {{ woSelRecords.length }} 条应收
                （每条生成一笔核销 + 一笔「预收抵扣」回款，两侧台账同步、可追溯）。
              </p>
              <div class="wo-adv-pick">
                <label v-for="a in woTarget?.advances || []" :key="a.id" class="wo-adv-opt" :class="{ on: woForm.advance_id === a.id }">
                  <input type="radio" :value="a.id" v-model="woForm.advance_id" />
                  <span>预收 {{ a.occur_date || '—' }}<template v-if="a.short_name"> · {{ a.short_name }}</template><template v-else-if="a.counterparty"> · {{ a.counterparty }}</template></span>
                  <b>余额 {{ fmtCell(a.balance_amount) }}</b>
                </label>
              </div>
              <div class="form-grid" style="margin-top:10px">
                <label class="form-field">
                  <span>核销金额（元）</span>
                  <input v-model="woForm.amount" type="number" step="0.01" :placeholder="`默认 ${woDefaultAmount.toFixed(2)}（=min(预收余额, 所选未收)）`" />
                </label>
                <label class="form-field">
                  <span>核销日期*</span>
                  <input v-model="woForm.writeoff_date" type="date" />
                </label>
              </div>
              <p style="font-size:11.5px;color:var(--muted);margin-top:8px">
                所选未收合计 <b>{{ woSelOutstanding.toFixed(2) }}</b> · 该预收余额 <b>{{ woAdvBalance.toFixed(2) }}</b>
              </p>
            </template>
            <template v-else>
              <p style="font-size:13px;color:#2e7d32;font-weight:600;margin-bottom:10px">✓ {{ woResult.message }}</p>
              <table class="bp-mtable">
                <thead><tr><th>项目</th><th>运作日期</th><th class="r">本次冲抵</th><th class="r">冲抵后未收</th></tr></thead>
                <tbody>
                  <tr v-for="a in woResult.allocations" :key="a.record_id">
                    <td>{{ a.short_name }}</td><td>{{ a.operation_date || '—' }}</td>
                    <td class="r" style="color:#2e7d32;font-weight:600">+{{ fmtCell(a.allocated) }}</td>
                    <td class="r" :class="parseFloat(a.outstanding_after) > 0 ? 'bp-out' : 'bp-ok'">
                      {{ parseFloat(a.outstanding_after) > 0 ? fmtCell(a.outstanding_after) : '✓ 结清' }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </template>
          </div>
          <div class="modal-footer">
            <template v-if="!woResult">
              <button class="btn btn-ghost" @click="showWoModal = false">取消</button>
              <button class="btn btn-primary" :disabled="woBusy || !woForm.advance_id || !woForm.writeoff_date" @click="doBatchWriteoff">
                {{ woBusy ? '核销中…' : '确认批量核销' }}
              </button>
            </template>
            <button v-else class="btn btn-primary" @click="showWoModal = false">完成</button>
          </div>
        </div>
      </div>

      <!-- Payment Modal — 录入态：点遮罩不关闭，仅按钮可退出 -->
      <div v-if="showPayModal" class="modal-overlay">
        <div class="modal-box" style="max-width:460px">
          <div class="modal-header">
            <div>
              <h3>{{ payForm.source === '内部往来' ? '内部往来核销' : '录入回款' }}</h3>
              <div style="font-size:12px;color:var(--muted);margin-top:2px">{{ payRec?.short_name || payRec?.customer_name }}</div>
            </div>
            <button class="modal-close" @click="showPayModal = false">✕</button>
          </div>
          <div class="modal-body">
            <!-- 类型切换：银行回款（现金）/ 内部往来核销（事业部间，不计现金） -->
            <div class="pay-type-tabs">
              <button type="button" class="pay-type-tab" :class="{ on: payForm.source === '回款' }"
                      @click="payForm.source = '回款'; payForm.counterparty_dept = ''">银行回款</button>
              <button type="button" class="pay-type-tab" :class="{ on: payForm.source === '内部往来' }"
                      @click="payForm.source = '内部往来'; advWoSel = null">内部往来核销</button>
            </div>
            <div v-if="payForm.source === '内部往来'" class="internal-note">
              事业部间内部往来核销：冲减本笔应收未收，<strong>不计现金</strong>（不进现金流/资金池）。
            </div>
            <div v-if="payForm.source === '回款' && payAdvance" class="adv-hint">
              <div class="adv-hint-head">
                <span class="adv-hint-tag">可用预收</span>
                <span>该项目尚有 <b>{{ payAdvance.count }}</b> 笔预收，余额合计
                  <b>{{ fmtAmt(payAdvance.total_balance) }}</b></span>
                <button class="adv-hint-link" type="button" @click="gotoAdvance">在预收页管理 →</button>
              </div>
              <ul class="adv-hint-list">
                <li v-for="a in payAdvance.items.slice(0, 5)" :key="a.id" :class="{ on: advWoSel?.id === a.id }">
                  <span class="adv-mt" :class="a.match_type === 'project' ? 'mt-proj' : 'mt-cust'">{{ a.match_type === 'project' ? '本项目' : '客户' }}</span>
                  <span class="adv-cp">{{ a.counterparty || '—' }}</span>
                  <span class="adv-bal">{{ fmtAmt(a.balance_amount) }}</span>
                  <span v-if="a.is_overdue" class="adv-od">逾期{{ a.overdue_days }}天</span>
                  <button v-if="auth.canArWrite" type="button" class="adv-use-btn" @click="selectAdvForWriteoff(a)">用此预收下账</button>
                </li>
              </ul>
              <div v-if="advWoSel" class="adv-wo-form">
                <div class="adv-wo-row">
                  <span>用预收 <b>{{ advWoSel.counterparty || '—' }}</b>（余额 {{ fmtAmt(advWoSel.balance_amount) }}）抵扣本笔应收，未收 {{ fmtAmt(payRec?.outstanding_amount) }}：</span>
                </div>
                <div class="adv-wo-row">
                  <input v-model="advWoForm.amount" type="number" step="0.01" class="adv-wo-amt" />
                  <button class="btn btn-primary btn-xs" :disabled="advWoSaving" @click="applyAdvanceWriteoff">{{ advWoSaving ? '下账中…' : '确认用预收下账' }}</button>
                  <button class="btn btn-ghost btn-xs" @click="advWoSel = null">取消</button>
                </div>
                <div class="adv-wo-tip">将核销该预收并生成「预收抵扣」回款，自动冲减未收余额（不计现金，避免重复）。</div>
              </div>
              <div v-else class="adv-hint-note">提示：可直接「用此预收下账」抵扣本笔应收（生成预收抵扣、不计现金）；或在预收页统一管理核销。下方录入则为正常现金回款。</div>
            </div>
            <div class="form-grid">
              <label v-if="payForm.source === '内部往来'" class="form-field span2">
                <span>往来部门 <em>*</em></span>
                <select v-model="payForm.counterparty_dept">
                  <option value="" disabled>选择往来事业部</option>
                  <option v-for="d in DEPARTMENTS" :key="d" :value="d">{{ d }}</option>
                </select>
              </label>
              <label class="form-field span2">
                <span>{{ payForm.source === '内部往来' ? '核销金额' : '回款金额' }} <em>*</em></span>
                <input v-model="payForm.amount" type="number" step="0.01" autofocus />
              </label>
              <label class="form-field span2">
                <span>{{ payForm.source === '内部往来' ? '核销日期' : '回款日期' }} <em>*</em></span>
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
            <button class="btn btn-primary" :disabled="paySaving" @click="savePayment">{{ paySaving ? '保存中…' : (payForm.source === '内部往来' ? '保存核销' : '保存回款') }}</button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- 数据体检明细 -->
    <Teleport to="body">
      <div v-if="showHealthModal" class="modal-overlay" @click.self="showHealthModal = false">
        <div class="modal-box" style="max-width:880px">
          <div class="modal-header">
            <div>
              <h3>数据体检 · 异常记录</h3>
              <div style="font-size:12px;color:var(--muted);margin-top:2px">口径：预估上账 + 账实差额 − 累计回款 = 未收金额</div>
            </div>
            <button class="modal-close" @click="showHealthModal = false">✕</button>
          </div>
          <div class="modal-body" style="max-height:60vh;overflow:auto">
            <!-- 可一键重算 -->
            <div v-if="healthData?.stale_count" class="health-section">
              <div class="health-sec-head">
                <span>未收金额与现规则不一致（可一键重算）· {{ healthData.stale_count }} 条<span v-if="healthData.stale_count > (healthData.stale?.length||0)">（仅展示前 {{ healthData.stale.length }} 条）</span></span>
                <button v-if="auth.canArWrite" class="btn btn-primary btn-sm" :disabled="healthFixing" @click="fixStaleRecords">
                  {{ healthFixing ? '重算中…' : '一键重算修复' }}
                </button>
              </div>
              <table class="health-table">
                <thead><tr><th>项目编号</th><th>项目简称</th><th>运作日期</th><th class="r">预估上账</th><th class="r">累计回款</th><th class="r">现存未收</th><th class="r">重算未收</th></tr></thead>
                <tbody>
                  <tr v-for="r in healthData.stale" :key="r.id">
                    <td>{{ r.project_no }}</td><td>{{ r.short_name }}</td>
                    <td>{{ r.operation_date || (r.operation_year + "-" + r.operation_month) }}</td>
                    <td class="r">{{ fmtAmt(r.estimated_amount) }}</td>
                    <td class="r">{{ fmtAmt(r.total_paid) }}</td>
                    <td class="r muted">{{ r.stored_outstanding == null ? '—' : fmtAmt(r.stored_outstanding) }}</td>
                    <td class="r ok">{{ fmtAmt(r.recomputed_outstanding) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <!-- 需人工核对 -->
            <div v-if="healthData?.negative_count" class="health-section">
              <div class="health-sec-head">
                <span class="danger-text">累计回款超过上账口径（需人工核对）· {{ healthData.negative_count }} 条<span v-if="healthData.negative_count > (healthData.negative?.length||0)">（仅展示前 {{ healthData.negative.length }} 条）</span></span>
              </div>
              <div class="health-hint">这类记录通常是旧模板把"未收金额"直接导入、或重复导入回款造成。请核对该明细的「预估上账金额」是否偏小、或删除多余的回款记录。点项目编号可在新标签查看明细。</div>
              <table class="health-table">
                <thead><tr><th>项目编号</th><th>项目简称</th><th>运作日期</th><th class="r">预估上账</th><th class="r">账实差额</th><th class="r">累计回款</th><th class="r">超出</th></tr></thead>
                <tbody>
                  <tr v-for="r in healthData.negative" :key="r.id">
                    <td>{{ r.project_no }}</td><td>{{ r.short_name }}</td>
                    <td>{{ r.operation_date || (r.operation_year + "-" + r.operation_month) }}</td>
                    <td class="r">{{ fmtAmt(r.estimated_amount) }}</td>
                    <td class="r">{{ fmtAmt(r.account_diff_adjustment) }}</td>
                    <td class="r">{{ fmtAmt(r.total_paid) }}</td>
                    <td class="r danger-text">{{ fmtAmt(r.deficit) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div v-if="!healthData?.has_issues" class="health-hint">未发现异常记录 ✓</div>
          </div>
          <div class="modal-footer">
            <button class="btn btn-ghost" @click="showHealthModal = false">关闭</button>
          </div>
        </div>
      </div>

      <!-- 导入结果弹窗 -->
      <div v-if="importResult" class="modal-overlay" @click.self="importResult = null">
        <div class="modal-box" style="max-width:800px">
          <div class="modal-header">
            <h3 :class="importResult.ok ? 'imp-ok' : 'imp-fail'">{{ importResult.ok ? '✓ ' : '✕ ' }}{{ importResult.title }}</h3>
            <button class="modal-close" @click="importResult = null">✕</button>
          </div>
          <div class="modal-body imp-body">
            <div v-for="sec in importResult.sections" :key="sec.label" class="imp-section">
              <div class="imp-sec-label" :class="{ 'imp-sec-warn': sec.warn }">{{ sec.label }}</div>
              <ul class="imp-sec-list">
                <li v-for="item in sec.items" :key="item">{{ item }}</li>
                <li v-if="sec.more" class="imp-more">{{ sec.more }}</li>
              </ul>
            </div>
            <div v-if="!importResult.sections?.length" class="imp-empty">无附加信息</div>
          </div>
          <div class="modal-footer">
            <button class="btn btn-primary" @click="importResult = null">知道了</button>
          </div>
        </div>
      </div>

      <!-- 导入预检弹窗 -->
      <ImportPrecheckModal :report="precheckResult" :busy="precheckBusy" :readonly="true"
        @close="precheckResult = null" @apply="onPrecheckApply" />

      <!-- 批量删除二次输入确认 -->
      <div v-if="showDelConfirm" class="modal-overlay" @click.self="showDelConfirm = false">
        <div class="modal-box" style="max-width:420px">
          <div class="modal-header">
            <div><h3>确认删除 {{ delConfirmCount }} 条应收账款</h3></div>
            <button class="modal-close" @click="showDelConfirm = false">✕</button>
          </div>
          <div class="modal-body">
            <p class="del-warn">⚠ 关联回款将一并删除，<strong>不可恢复</strong>。<span v-if="selectAllMatching">（当前为整个筛选集，跨所有分页）</span></p>
            <p class="del-tip">请输入待删条数 <strong>{{ delConfirmCount }}</strong> 以确认：</p>
            <input v-model="delConfirmText" class="del-input" :placeholder="`输入 ${delConfirmCount}`"
              @keyup.enter="confirmBulkDelete" />
          </div>
          <div class="modal-footer">
            <button class="btn btn-ghost" @click="showDelConfirm = false">取消</button>
            <button class="btn-danger-solid" :disabled="!delConfirmOk || bulkDeleting" @click="confirmBulkDelete">
              {{ bulkDeleting ? '删除中…' : '确认删除' }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.health-alert {
  display: flex; align-items: center; gap: 10px; margin-bottom: 12px;
  padding: 10px 14px; border-radius: 10px;
  background: rgba(255,167,38,0.10); border: 1px solid rgba(255,167,38,0.35); color: #b45309;
}
.health-icon { font-size: 16px; }
.health-text { flex: 1; font-size: 13px; line-height: 1.5; }
.health-text strong { color: #92400e; }
.health-btn {
  flex-shrink: 0; padding: 6px 14px; border-radius: 8px; font-size: 12.5px; font-weight: 600;
  border: 1px solid rgba(180,83,9,0.4); background: #fff; color: #b45309; cursor: pointer;
  transition: all 0.14s;
}
.health-btn:hover { background: #b45309; color: #fff; }
.health-section { margin-bottom: 20px; }
.health-sec-head {
  display: flex; align-items: center; justify-content: space-between; gap: 10px;
  font-size: 13px; font-weight: 600; margin-bottom: 8px;
}
.health-hint { font-size: 12px; color: var(--muted); margin-bottom: 8px; line-height: 1.6; }
.danger-text { color: #c62828; }
.health-table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.health-table th, .health-table td { padding: 6px 8px; border-bottom: 1px solid var(--border); text-align: left; }
.health-table th { color: var(--muted); font-weight: 600; }
.health-table td.r, .health-table th.r { text-align: right; font-variant-numeric: tabular-nums; }
.health-table td.muted { color: var(--muted); }
.health-table td.ok { color: #2e7d32; font-weight: 600; }
.btn-sm { padding: 5px 12px; font-size: 12px; }
.act-btn {
  padding: 6px 12px; border-radius: 8px; font-size: 12.5px; font-weight: 500;
  border: 1px solid var(--border); background: rgba(255,252,250,0.8); color: var(--muted);
  cursor: pointer; transition: all 0.14s; white-space: nowrap;
}
.act-btn:hover { border-color: var(--primary); color: var(--primary); }
.act-btn:disabled { opacity: 0.4; cursor: default; }
.act-btn--on { border-color: var(--primary); color: var(--primary); background: rgba(201,99,66,0.08); font-weight: 600; }

/* Topbar: title + inline tabs */
.topbar-left { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }

/* Segment control */
.segment-ctrl { display: inline-flex; gap: 0; padding: 3px; background: rgba(0,0,0,0.04); border-radius: 11px; flex-wrap: wrap; }
.seg-btn { display: flex; align-items: center; gap: 5px; padding: 6px 14px; border-radius: 9px; border: none; font-size: 12.5px; font-weight: 500; color: var(--muted); background: transparent; cursor: pointer; transition: all 0.18s; }
.seg-btn .seg-dot { width: 6px; height: 6px; border-radius: 50%; background: rgba(155,128,112,0.3); transition: all 0.18s; }
.seg-btn.active { background: white; color: var(--primary); font-weight: 700; box-shadow: 0 2px 8px rgba(0,0,0,0.12); }
.seg-btn.active .seg-dot { background: var(--primary); box-shadow: 0 0 6px rgba(201,99,66,0.5); }

/* ── 极简筛选 chip 栏 ─────────────────────────────────────────── */
.filter-bar { margin: 12px 0; }
.filter-chipbar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.quick-search { position: relative; display: inline-flex; align-items: center; }
.qs-ico { position: absolute; left: 9px; color: var(--muted); pointer-events: none; }
.qs-input {
  width: 200px; padding: 6px 26px 6px 30px; border: 1px solid var(--border); border-radius: 9px;
  background: rgba(255,252,250,0.9); font-size: 13px; color: var(--text);
  transition: border-color .14s, box-shadow .14s, width .18s;
}
.qs-input:focus { outline: none; border-color: var(--primary); box-shadow: 0 0 0 3px rgba(201,99,66,0.12); width: 240px; }
.qs-input::placeholder { color: var(--muted); }
.qs-clear {
  position: absolute; right: 7px; width: 16px; height: 16px; border: none; border-radius: 50%;
  background: rgba(0,0,0,0.08); color: var(--muted); font-size: 9px; cursor: pointer;
  display: flex; align-items: center; justify-content: center; line-height: 1;
}
.qs-clear:hover { background: rgba(198,40,40,0.12); color: #c62828; }
.fb-trigger-wrap { position: relative; }
.fb-trigger {
  display: inline-flex; align-items: center; gap: 6px; padding: 6px 12px; border-radius: 9px;
  font-size: 13px; font-weight: 700; border: 1px solid var(--border);
  background: rgba(255,252,250,0.9); color: var(--text); cursor: pointer; transition: all .14s;
}
.fb-trigger:hover, .fb-trigger.on { border-color: var(--primary); color: var(--primary); background: rgba(201,99,66,0.06); }
.fb-badge { display: inline-flex; align-items: center; justify-content: center; min-width: 16px; height: 16px; padding: 0 4px; border-radius: 8px; background: var(--primary); color: #fff; font-size: 10.5px; font-weight: 700; }
.fb-backdrop { position: fixed; inset: 0; z-index: 50; }
.fb-pop {
  position: absolute; top: calc(100% + 6px); left: 0; z-index: 51;
  width: 540px; max-width: 94vw;            /* 容器自身定宽，不依赖内部组件 */
  background: #fff; border: 1px solid var(--border); border-radius: 12px;
  box-shadow: 0 16px 44px rgba(0,0,0,0.18);
  /* 不可 overflow:hidden，否则会裁掉「添加条件」弹出的菜单 */
}
.fb-match { font-size: 12px; font-weight: 800; color: var(--primary); padding: 2px 8px; border-radius: 7px; background: rgba(201,99,66,0.08); }
.fb-hint { font-size: 12.5px; color: var(--muted); }
.filter-chip.date { background: rgba(122,159,212,0.14); color: #3f5a86; }
.filter-chip.amt  { background: rgba(201,99,66,0.12); color: var(--primary); }
.filter-chip.dim  { background: rgba(120,120,120,0.1); color: var(--text); }
.filter-chip { cursor: pointer; }

.filter-main { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.filter-more { display: flex; align-items: center; gap: 8px; flex-wrap: nowrap; overflow-x: auto; margin-top: 8px; padding-top: 10px; padding-bottom: 4px; border-top: 1px dashed var(--border); scrollbar-width: thin; }
.filter-more > * { flex: 0 0 auto; }
.filter-more::-webkit-scrollbar { height: 6px; }
.filter-more::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
.filter-conditions { display: flex; align-items: flex-start; gap: 8px; flex-wrap: wrap; margin-top: 8px; }
.fc-label { font-size: 12px; font-weight: 700; color: var(--muted); padding-top: 6px; white-space: nowrap; }
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
.metrics-bar { display: flex; align-items: center; gap: 10px; flex-wrap: nowrap; overflow-x: auto; margin-bottom: 4px; padding: 9px 16px; background: rgba(0,0,0,0.02); border-radius: 12px; }
.metrics-div { width: 1px; align-self: stretch; min-height: 20px; background: rgba(0,0,0,0.1); margin: 0 2px; }
/* 汇总区：全集合计 / 时段合计 两行纵向堆叠，标签等宽使两行数据项左对齐 */
.metrics-summary { display: flex; flex-direction: column; gap: 7px; }
.metrics-sum-row { display: flex; align-items: center; gap: 10px; flex-wrap: nowrap; }
.metrics-sum-row + .metrics-sum-row { padding-top: 7px; border-top: 1px dashed rgba(0,0,0,0.1); }
.sum-section-lbl { flex: 0 0 auto; width: 60px; font-size: 11px; font-weight: 600; color: var(--muted); letter-spacing: 0.5px; white-space: nowrap; cursor: default; padding: 2px 7px; border-radius: 6px; background: rgba(0,0,0,0.04); text-align: center; }
.sum-section-lbl.alt { background: rgba(46,125,50,0.08); color: #2e7d32; }
.kpi-item { display: flex; align-items: baseline; gap: 6px; }
.kpi-k { font-size: 12px; color: var(--muted); display: flex; flex-direction: column; gap: 1px; }
.kpi-sub { font-size: 10px; color: var(--muted); opacity: 0.75; font-weight: 400; }
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
.pay-range-chip {
  font-size: 12px; padding: 3px 10px; border-radius: 13px; cursor: pointer;
  border: 1px solid var(--border); background: var(--card); color: var(--text);
  white-space: nowrap; transition: all .12s;
}
.pay-range-chip:hover { border-color: var(--primary); color: var(--primary); }
.pay-range-chip.on { background: var(--primary); border-color: var(--primary); color: #fff; }
/* 汇总下钻行 + 合计行 */
.row-drill { cursor: pointer; }
.row-drill:hover { background: rgba(201,99,66,0.07); }
.group-total-row td { border-top: 2px solid rgba(0,0,0,0.1); padding: 11px 12px; background: rgba(0,0,0,0.02); }

/* Table — 紧凑：数据量大，尽量一屏多看 */
.rec-table { width: 100%; }
.rec-table th { font-size: 10.5px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); padding: 6px 10px; background: rgba(0,0,0,0.02); white-space: nowrap; }
/* 列头筛选漏斗弹层经 Teleport 到 body 不受裁剪，但漏斗按钮本身需可见，避免被表头裁掉 */
.rec-table thead th { overflow: visible; }
.rec-table td { padding: 5px 10px; vertical-align: middle; font-size: 12.5px; }
/* 数据表内部滚动：表头吸顶 + 合计行吸底，行在中间滚动，合计始终停在表区底部
   （无需把整页拉到最底就能看到汇总）。max-height 留给上方筛选/指标条，可按需微调。 */
.dt-scroll { max-height: calc(100vh - 250px); overflow: auto; }
.dt-scroll .rec-table thead th { position: sticky; top: 0; z-index: 5; background: #f4f1ef; }
.dt-scroll .rec-table thead .sel-col { z-index: 6; }
/* 选择列 */
.sel-col { width: 30px; text-align: center; padding-left: 8px !important; padding-right: 4px !important; }
.sel-col input { cursor: pointer; }
.data-row:hover { background: rgba(201,99,66,0.03); }
.row-sel, .row-sel:hover { background: rgba(201,99,66,0.09) !important; }
/* 批量删除工具条 */
.bulk-bar { display: flex; align-items: center; gap: 12px; margin: 10px 0 0; padding: 8px 14px;
  border-radius: 10px; background: rgba(198,40,40,0.06); border: 1px solid rgba(198,40,40,0.25); }
.bulk-n { font-size: 13px; color: var(--text); }
.bulk-all { border: none; background: none; color: var(--primary); font-size: 12.5px; cursor: pointer; text-decoration: underline; text-underline-offset: 2px; }
.bulk-all-on { font-size: 12.5px; color: var(--primary); font-weight: 700; }
.bulk-del { margin-left: auto; border: none; border-radius: 8px; padding: 6px 14px; font-size: 13px; font-weight: 700; cursor: pointer; background: var(--danger); color: #fff; }
.bulk-del:disabled { opacity: .6; cursor: default; }
.bulk-cancel { border: none; background: none; color: var(--muted); font-size: 12.5px; cursor: pointer; }
/* 删除二次确认 */
.del-warn { font-size: 13px; color: var(--danger); margin: 0 0 12px; line-height: 1.6; }
.del-tip { font-size: 13px; color: var(--text); margin: 0 0 8px; }
.del-input { width: 100%; padding: 8px 12px; border: 1.5px solid var(--border); border-radius: 8px; font-size: 14px; }
.del-input:focus { border-color: var(--danger); outline: none; }
.btn-danger-solid { border: none; border-radius: 8px; padding: 8px 18px; font-size: 14px; font-weight: 700; cursor: pointer; background: var(--danger); color: #fff; }
.btn-danger-solid:disabled { opacity: .5; cursor: default; }
.data-row:not(:last-child) td { border-bottom: 1px solid rgba(0,0,0,0.04); }
.row-overdue { background: rgba(198,40,40,0.04); }

/* 列合计页脚：置于表格最底部（随表滚动），上分隔线，金额加粗，与列对齐 */
.rec-table tfoot .sum-foot td {
  background: #f8efeb;
  border-top: 2px solid rgba(201,99,66,0.32);
  padding: 9px 12px; font-weight: 800; font-size: 13px;
  font-variant-numeric: tabular-nums;
}
.sum-foot-lbl { white-space: nowrap; color: var(--primary); }
.rec-table tfoot .amt-warn { color: #e65100; }
.rec-table tfoot .amt-muted { color: var(--muted); font-weight: 600; }

.empty-cell { text-align: center; padding: 48px !important; color: var(--muted); font-size: 14px; }
.proj-name { font-weight: 600; font-size: 12.5px; max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
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

/* 开票批次号 badge */
.batch-badge { display: inline-block; font-size: 11px; font-weight: 600; padding: 2px 7px; border-radius: 6px; background: rgba(33,150,243,0.12); color: #1565c0; border: 1px solid rgba(33,150,243,0.2); white-space: nowrap; max-width: 120px; overflow: hidden; text-overflow: ellipsis; cursor: default; }

/* ══ 差额调整明细管理器 ══ */
.adj-box .adj-total { font-style: normal; font-weight: 400; font-size: 11px; color: var(--muted); margin-left: 8px; }
.adj-list { display: flex; flex-direction: column; gap: 4px; margin: 6px 0; }
.adj-item { display: flex; align-items: center; gap: 10px; padding: 6px 10px; border: 1px solid rgba(120,120,120,0.14); border-radius: 8px; background: rgba(255,255,255,0.6); font-size: 12.5px; }
.adj-item b { font-variant-numeric: tabular-nums; min-width: 76px; }
.adj-pos { color: #2e7d32; } .adj-neg { color: #c62828; }
.adj-reason { flex: 1; color: var(--text); overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.adj-item em { font-style: normal; font-size: 11px; color: var(--muted); }
.adj-del { border: none; background: none; color: var(--muted); cursor: pointer; font-size: 12px; }
.adj-del:hover { color: #c62828; }
.adj-empty { font-size: 12px; color: var(--muted); padding: 6px 0; }
.adj-add { display: flex; gap: 6px; margin-top: 4px; }
.adj-add .adj-amt-inp { width: 120px; }
.adj-add .adj-reason-inp { flex: 1; }

/* ══ 预收核销工作台 ══ */
.ow-wrap { margin-top: 12px; }
.ow-head { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; flex-wrap: wrap; }
.ow-tip { font-size: 11.5px; color: var(--muted); flex: 1; min-width: 240px; }
.ow-groups { display: flex; flex-direction: column; gap: 14px; }
.ow-card { border: 1px solid rgba(46,125,50,0.22); border-radius: 12px; background: rgba(46,125,50,0.03); padding: 12px 14px; }
.ow-card-head { display: flex; align-items: center; gap: 18px; flex-wrap: wrap; margin-bottom: 8px; }
.ow-cust { font-size: 14px; font-weight: 800; color: var(--text); }
.ow-stat { display: flex; flex-direction: column; }
.ow-stat i { font-style: normal; font-size: 10.5px; color: var(--muted); }
.ow-stat b { font-size: 13px; font-variant-numeric: tabular-nums; color: var(--text); }
.ow-stat b.ok { color: #2e7d32; }
.ow-stat b.warn { color: #e65100; }
.ow-advances { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 8px; }
.ow-adv-chip { font-size: 11.5px; color: #2e7d32; background: rgba(46,125,50,0.08); border: 1px solid rgba(46,125,50,0.22); border-radius: 9px; padding: 3px 10px; }
.ow-adv-chip b { font-variant-numeric: tabular-nums; margin-left: 6px; }
.ow-table { width: 100%; border-collapse: collapse; font-size: 12.5px; background: #fff; border-radius: 8px; overflow: hidden; }
.ow-table th { background: rgba(46,125,50,0.06); color: var(--muted); font-weight: 600; padding: 7px 10px; text-align: left; white-space: nowrap; }
.ow-table td { padding: 7px 10px; border-top: 1px solid rgba(120,120,120,0.08); cursor: pointer; }
.ow-table tr.row-sel td { background: rgba(46,125,50,0.07); }
.ow-table .amt { text-align: right; font-variant-numeric: tabular-nums; }
.count-offset { background: rgba(21,101,192,0.13); color: #1565c0; }
.wo-adv-pick { display: flex; flex-direction: column; gap: 6px; max-height: 180px; overflow-y: auto; }
.wo-adv-opt { display: flex; align-items: center; gap: 8px; padding: 8px 10px; border: 1px solid var(--border); border-radius: 9px; cursor: pointer; font-size: 12.5px; }
.wo-adv-opt.on { border-color: #2e7d32; background: rgba(46,125,50,0.06); }
.wo-adv-opt b { margin-left: auto; color: #2e7d32; font-variant-numeric: tabular-nums; }

/* 批次开票事件 */
.bi-events { margin-bottom: 10px; padding: 7px 10px; background: rgba(21,101,192,.04);
  border: 1px solid rgba(21,101,192,.18); border-radius: 8px; }
.bi-events-head { font-size: 11.5px; font-weight: 700; color: #1565c0; margin-bottom: 3px; }
.bi-events-head i { font-style: normal; font-weight: 400; font-size: 10.5px; color: var(--muted); margin-left: 8px; }
.bi-ev-row { display: flex; align-items: center; gap: 10px; font-size: 12px; padding: 3px 0; }
.bie-date { color: var(--muted); font-variant-numeric: tabular-nums; min-width: 78px; }
.bie-amt { color: #1565c0; font-variant-numeric: tabular-nums; min-width: 80px; }
.bie-tax { font-size: 11px; color: var(--muted); white-space: nowrap; }
.bie-note { flex: 1; color: var(--muted); font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bie-undo { border: 1px solid rgba(198,40,40,.4); color: #c62828; background: none; border-radius: 6px; padding: 1px 8px; font-size: 11px; cursor: pointer; white-space: nowrap; }
.bie-undo:hover:not(:disabled) { background: rgba(198,40,40,.08); }
.bi-add { border: 1px dashed rgba(201,99,66,.4); border-radius: 10px; padding: 10px 12px; }
.bi-add-head { font-size: 12.5px; font-weight: 700; color: var(--text); margin-bottom: 8px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 6px; }
.bi-room { font-size: 11px; font-weight: 400; color: var(--muted); }
.bi-room b { color: #e65100; font-variant-numeric: tabular-nums; }

/* ══ 合并开票批次工作台 ══ */
.batch-panel { margin-top: 12px; border: 1px solid rgba(33,150,243,0.22); border-radius: 12px; background: rgba(33,150,243,0.03); overflow: hidden; }
.bp-head { display: flex; align-items: center; gap: 10px; padding: 9px 14px; }
.bp-title { font-size: 13px; font-weight: 700; color: #1565c0; }
.bp-title i { font-style: normal; font-size: 11px; background: rgba(33,150,243,0.14); border-radius: 9px; padding: 1px 7px; margin-left: 6px; }
.bp-tip { font-size: 11.5px; color: var(--muted); flex: 1; }
.bp-toggle { border: none; background: none; font-size: 11.5px; color: var(--muted); cursor: pointer; }
.bp-toggle:hover { color: #1565c0; }
.bp-empty { padding: 12px 14px; font-size: 12.5px; color: var(--muted); text-align: center; }
.bp-list { display: flex; flex-direction: column; }
.bp-item { border-top: 1px solid rgba(33,150,243,0.12); }
.bp-row { display: flex; align-items: center; gap: 14px; padding: 9px 14px; cursor: pointer; flex-wrap: wrap; }
.bp-row:hover { background: rgba(33,150,243,0.05); }
.bp-no { font-weight: 700; font-size: 13px; color: var(--text); min-width: 110px; }
.bp-cust { font-size: 12px; color: var(--muted); max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bp-cnt { font-size: 12px; color: var(--muted); }

/* 批次号来源选择 */
.bm-modes { display: flex; flex-direction: column; gap: 8px; }
.bm-opt { display: flex; gap: 10px; align-items: flex-start; padding: 10px 12px;
  border: 1px solid var(--border); border-radius: 10px; cursor: pointer; }
.bm-opt.on { border-color: var(--primary); background: rgba(201,99,66,0.05); }
.bm-opt input[type="radio"] { margin-top: 3px; width: auto; }
.bm-opt > div { flex: 1; }
.bm-opt b { display: block; font-size: 13px; color: var(--text); }
.bm-opt i { display: block; font-style: normal; font-size: 11.5px; color: var(--muted); margin-top: 2px; }
.bp-amt { display: flex; flex-direction: column; min-width: 86px; }
.bp-amt i { font-style: normal; font-size: 10.5px; color: var(--muted); }
.bp-amt b { font-size: 12.5px; font-variant-numeric: tabular-nums; color: var(--text); }
.bp-amt.ok b { color: #2e7d32; }
.bp-amt.warn b { color: #e65100; }
.bp-acts { margin-left: auto; display: flex; align-items: center; gap: 8px; }
.bp-btn { border: 1px solid rgba(33,150,243,0.4); background: #fff; color: #1565c0; font-size: 12px; font-weight: 600; padding: 4px 11px; border-radius: 7px; cursor: pointer; white-space: nowrap; }
.bp-btn:hover { background: rgba(33,150,243,0.08); }
.bp-btn.primary { background: #1565c0; color: #fff; border-color: #1565c0; }
.bp-btn.primary:hover { filter: brightness(1.1); }
.bp-caret { font-size: 11px; color: var(--muted); }
.bp-members { padding: 0 14px 12px; overflow-x: auto; }
.bp-colls { margin-bottom: 8px; padding: 7px 10px; background: rgba(46,125,50,.04); border: 1px solid rgba(46,125,50,.16); border-radius: 8px; }
.bp-colls-head { font-size: 11.5px; font-weight: 700; color: #2e7d32; margin-bottom: 3px; }
.bp-colls-head i { font-style: normal; font-weight: 400; font-size: 10.5px; color: var(--muted); margin-left: 8px; }
.bp-coll-row { display: flex; align-items: center; gap: 10px; font-size: 12px; padding: 3px 0; }
.bpc-date { color: var(--muted); font-variant-numeric: tabular-nums; min-width: 78px; }
.bpc-amt { color: #2e7d32; font-variant-numeric: tabular-nums; min-width: 80px; }
.bpc-n { color: var(--muted); font-size: 11px; white-space: nowrap; }
.bpc-note { flex: 1; color: var(--muted); font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bpc-undo { border: 1px solid rgba(198,40,40,.4); color: #c62828; background: none; border-radius: 6px; padding: 1px 8px; font-size: 11px; cursor: pointer; white-space: nowrap; }
.bpc-undo:hover:not(:disabled) { background: rgba(198,40,40,.08); }
.bp-mtable { width: 100%; border-collapse: collapse; font-size: 12px; background: #fff; border-radius: 8px; overflow: hidden; }
.bp-mtable th { background: rgba(33,150,243,0.07); color: var(--muted); font-weight: 600; padding: 6px 10px; text-align: left; white-space: nowrap; }
.bp-mtable td { padding: 6px 10px; border-top: 1px solid rgba(120,120,120,0.08); white-space: nowrap; }
.bp-mtable .r { text-align: right; font-variant-numeric: tabular-nums; }
.bp-diff { color: #e65100; font-weight: 600; }
.bp-adj-n { font-style: normal; font-size: 10px; color: var(--muted); margin-left: 3px; }
.bp-out { color: #e65100; font-weight: 600; }
.bp-ok { color: #2e7d32; font-weight: 700; }

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
.pay-src { font-size: 11px; font-weight: 600; color: #1b6e35; background: rgba(27,110,53,0.1); padding: 1px 7px; border-radius: 999px; }
.pay-src-internal { color: #6a1b9a; background: rgba(106,27,154,0.1); }
.pay-notes { font-size: 12px; color: var(--muted); font-style: italic; }
.pay-del { margin-left: auto; font-size: 11.5px; color: #c62828; background: none; border: none; cursor: pointer; }
.pay-del:hover { text-decoration: underline; }
/* 内部往来核销：列表次数徽标 + 录入弹窗类型切换 */
.count-internal { background: rgba(106,27,154,0.13); color: #6a1b9a; }
.pay-type-tabs { display: flex; gap: 8px; margin-bottom: 12px; }
.pay-type-tab { flex: 1; padding: 7px 10px; border: 1px solid var(--border); border-radius: 9px; background: rgba(255,252,250,0.8); cursor: pointer; font-size: 13px; color: var(--text); transition: all 0.14s; }
.pay-type-tab:hover { border-color: var(--primary); }
.pay-type-tab.on { background: var(--primary); color: #fff; border-color: var(--primary); font-weight: 600; }
.internal-note { font-size: 12px; color: #6a1b9a; background: rgba(106,27,154,0.07); border: 1px solid rgba(106,27,154,0.2); border-radius: 8px; padding: 8px 12px; margin-bottom: 12px; }

.row-acts { display: flex; gap: 4px; justify-content: center; }
.icon-btn { width: 26px; height: 26px; border-radius: 6px; border: 1px solid var(--border); background: rgba(255,252,250,0.7); display: flex; align-items: center; justify-content: center; color: var(--muted); cursor: pointer; transition: all 0.13s; }
.icon-btn:hover { border-color: var(--primary); color: var(--primary); }
.icon-btn-del:hover { border-color: #c62828; color: #c62828; background: rgba(198,40,40,0.07); }

.pagination { display: flex; align-items: center; justify-content: center; gap: 14px; padding: 16px 0 4px; }
/* .bottom-bar, .bb-*, .page-btn, .page-info → global styles in style.css */

/* 录入回款 · 可用预收提示 */
.adv-hint { margin-bottom: 14px; padding: 10px 12px; border: 1px solid rgba(56,142,60,0.28);
  background: rgba(76,175,80,0.08); border-radius: 12px; }
.adv-hint-head { display: flex; align-items: center; gap: 8px; font-size: 12.5px; color: var(--text); flex-wrap: wrap; }
.adv-hint-tag { padding: 1px 8px; border-radius: 999px; background: #2e7d32; color: #fff; font-size: 11px; font-weight: 600; }
.adv-hint-head b { color: #2e7d32; }
.adv-hint-link { margin-left: auto; border: none; background: none; color: var(--primary); cursor: pointer; font-size: 12px; padding: 0; }
.adv-hint-link:hover { text-decoration: underline; }
.adv-hint-list { list-style: none; margin: 8px 0 0; padding: 0; display: flex; flex-direction: column; gap: 3px; }
.adv-hint-list li { display: flex; align-items: center; gap: 10px; font-size: 12px; color: var(--muted); }
.adv-hint-list .adv-cp { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.adv-hint-list .adv-bal { font-variant-numeric: tabular-nums; color: var(--text); font-weight: 600; }
.adv-hint-list .adv-od { color: #c62828; font-size: 11px; }
.adv-hint-note { margin-top: 8px; font-size: 11px; color: var(--muted); line-height: 1.5; }
.adv-hint-list li.on { background: rgba(76,175,80,0.12); border-radius: 6px; }
.adv-mt { flex: none; font-size: 10px; font-weight: 700; padding: 1px 6px; border-radius: 999px; }
.adv-mt.mt-proj { background: rgba(56,142,60,0.14); color: #2e7d32; }
.adv-mt.mt-cust { background: rgba(21,101,192,0.14); color: #1565c0; }
.adv-use-btn { margin-left: auto; border: 1px solid #2e7d32; background: none; color: #2e7d32; border-radius: 6px; font-size: 11px; padding: 1px 8px; cursor: pointer; white-space: nowrap; }
.adv-use-btn:hover { background: rgba(46,125,50,0.1); }
.adv-wo-form { margin-top: 10px; padding: 9px 10px; border: 1px solid rgba(46,125,50,0.35); background: rgba(76,175,80,0.06); border-radius: 9px; }
.adv-wo-row { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--text); margin-bottom: 6px; flex-wrap: wrap; }
.adv-wo-row:last-of-type { margin-bottom: 0; }
.adv-wo-row b { color: #2e7d32; }
.adv-wo-amt { width: 130px; padding: 5px 8px; border: 1px solid var(--border); border-radius: 7px; font-size: 13px; }
.btn-xs { padding: 4px 10px; font-size: 12px; }
.adv-wo-tip { margin-top: 7px; font-size: 11px; color: var(--muted); line-height: 1.5; }

/* 导入结果弹窗 */
.imp-ok { color: #2e7d32; }
.imp-fail { color: #c62828; }
.imp-body { max-height: calc(82vh - 130px); overflow-y: auto; padding-right: 4px; scrollbar-width: thin; }
.imp-body::-webkit-scrollbar { width: 6px; }
.imp-body::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
.imp-section { margin-bottom: 16px; }
.imp-sec-label { font-size: 13px; font-weight: 700; color: var(--text); margin-bottom: 6px; padding: 4px 10px; border-radius: 6px; background: rgba(0,0,0,0.04); }
.imp-sec-label.imp-sec-warn { background: rgba(230,81,0,0.08); color: #e65100; }
.imp-sec-list { list-style: none; margin: 0; padding: 0 0 0 10px; display: flex; flex-direction: column; gap: 4px; }
.imp-sec-list li { font-size: 12.5px; color: var(--text); line-height: 1.6; white-space: pre-wrap; word-break: break-all; border-bottom: 1px dashed rgba(0,0,0,0.06); padding-bottom: 4px; }
.imp-sec-list li:last-child { border-bottom: none; }
.imp-more { color: var(--muted); font-style: italic; }
.imp-empty { font-size: 13px; color: var(--muted); text-align: center; padding: 12px 0; }

/* 催款工作台 */
.dun-buckets { display: flex; gap: 10px; margin-top: 12px; flex-wrap: wrap; }
.dun-bucket { flex: 1; min-width: 130px; text-align: left; padding: 10px 14px; border: 1.5px solid var(--border); border-radius: 10px; background: #fff; cursor: pointer; transition: all .15s; }
.dun-bucket:hover { border-color: #e65100; }
.dun-bucket.on { border-color: #e65100; background: rgba(230,81,0,0.06); box-shadow: 0 0 0 2px rgba(230,81,0,0.12); }
.dun-bucket.empty { opacity: .55; }
.db-label { font-size: 11px; color: var(--muted); margin-bottom: 4px; }
.db-count { font-size: 15px; font-weight: 700; color: var(--text); }
.db-amt { font-size: 13px; font-weight: 600; color: #c62828; margin-top: 2px; }
.dun-contacts { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-top: 10px; }
.dc-label { font-size: 12px; color: var(--muted); flex-shrink: 0; }
.dc-chip { padding: 4px 10px; border: 1px solid var(--border); border-radius: 14px; background: #fff; font-size: 12px; color: var(--text); cursor: pointer; transition: all .15s; }
.dc-chip:hover { border-color: #e65100; }
.dc-chip.on { border-color: #e65100; background: rgba(230,81,0,0.08); color: #e65100; font-weight: 600; }
.od-badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 12px; font-weight: 700; }
.od-badge.od-warn { background: rgba(230,81,0,0.1); color: #e65100; }
.od-badge.od-danger { background: rgba(198,40,40,0.1); color: #c62828; }
.dun-has-action { font-size: 12px; color: #2e7d32; font-weight: 600; }

/* 分页跳转 */
.pg-jump { display:inline-flex;align-items:center;gap:4px;font-size:13px;color:var(--muted);margin-left:8px; }
.pg-jump-input { width:46px;text-align:center;padding:2px 4px;border:1px solid var(--border);border-radius:6px;font-size:13px; }

/* 移动端 KPI 响应式 */
@media (max-width: 640px) {
  .metrics-bar { flex-wrap: wrap !important; }
  .kpi-item, .kpi-progress { min-width: calc(50% - 8px) !important; flex: 1 1 calc(50% - 8px) !important; }
}
</style>
