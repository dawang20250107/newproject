<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount, provide } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../../stores/auth.js'
import { DEPARTMENTS, yearCST, monthCST, todayCST } from '../../constants.js'
import ar from '../../api/ar.js'
import { fmtCompact, fmtMoney } from '../../utils/format.js'
import { downloadBlob } from '../../utils/download.js'
import { useServerSort } from '../../composables/useServerSort.js'
import SortTh from '../../components/ar/SortTh.vue'
import FilterPanel from '../../components/ar/FilterPanel.vue'
import { describeCondition } from '../../composables/arConditions.js'

const route = useRoute()
const router = useRouter()

const auth = useAuthStore()
const items = ref([])
const total = ref(0)
const kpiData = ref(null)
const healthData = ref(null)
const showHealthModal = ref(false)
const healthFixing = ref(false)
const loading = ref(false)
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
  } catch (e) { alert(e?.msg || '删除失败') }
  finally { bulkDeleting.value = false }
}

// 服务端排序（点表头）——状态机经 provide 下放给各 <SortTh>，变化即回首页重拉
const sorter = useServerSort(() => load(true))
provide('arSort', sorter)

const showModal = ref(false)
const editRec = ref(null)
const saving = ref(false)
const recForm = reactive({
  project_id: '', operation_year: yearCST(), operation_month: monthCST(),
  estimated_amount: '', actual_invoice_amount: '', tax_amount: '',
  invoice_date: '', reconciliation_date: '', account_diff_adjustment: '',
  invoice_batch_no: '', notes: '',
})

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
const payForm = reactive({ amount: '', payment_date: '', notes: '' })
const paySaving = ref(false)
// 录入回款时联动：该项目可用预收（只读提示，便于判断是否以预收冲抵应收）
const payAdvance = ref(null)
const expandedPayments = ref({})
const importing = ref(false)
const exporting = ref(false)
const fileInput = ref(null)
const importResult = ref(null)   // { ok: bool, title, lines: [] }

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
  { key: 'dunning', label: '催款' },
  { key: 'payments', label: '回款流水' },
  { key: 'summary', label: '汇总' },
]
const DATA_TABS = ['all', 'reconciliation', 'invoice', 'collection']
const isDataTab = computed(() => DATA_TABS.includes(activeTab.value))
const summaryData = ref(null)

// ── 筛选 chip 栏 ─────────────────────────────────────────────────────────────
const hasAnyFilter = computed(() => conditions.value.length > 0)
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
const payFilters = reactive({ pay_start: '', pay_end: '', dept: '', q: '' })
const payItems = ref([])
const paySummary = ref(null)
const payTotal = ref(0)
const payPage = ref(1)
const payLoading = ref(false)
const payExporting = ref(false)

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
    alert(msg)
    await loadDunning(true)
  } catch (e) { alert(e?.msg || '生成失败') }
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

async function load(reset = false) {
  if (reset) page.value = 1
  loading.value = true
  try {
    const [recs, kpi] = await Promise.all([
      ar.listRecords({ ...reqParams(), sort: sorter.sort.value || undefined,
        include_payments: 1, page: page.value, size }),
      ar.recordsKpi(reqParams()),
    ])
    items.value = recs.data.items
    total.value = recs.data.total
    summaryData.value = recs.data.summary
    kpiData.value = kpi.data
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
    alert(msg)
    await loadHealth(); await load()
  } catch (e) { alert(e?.msg || '重算失败') }
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
  } catch (e) { alert(e?.msg || '导出失败')
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
  else if (!DATA_TABS.includes(prev)) load()  // returning from a non-data tab
}

// Shared-filter change → refresh whichever tab consumes those filters.
function onFilterChange() {
  clearSelection()
  if (activeTab.value === 'summary') loadGroupSummary()
  else load(true)
}

// 汇总行下钻：把该维度作为条件追加（替换同字段旧条件），切到全部明细
function upsertDim(field, value) {
  const list = conditions.value.filter(c => !(c.t === 'dim' && c.field === field))
  list.push({ t: 'dim', field, value })
  conditions.value = list
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
    operation_year: yearCST(), operation_month: monthCST(),
    estimated_amount: '', actual_invoice_amount: '', tax_amount: '',
    invoice_date: '', reconciliation_date: '', account_diff_adjustment: '',
    invoice_batch_no: '', notes: '',
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
    invoice_batch_no: rec.invoice_batch_no || '',
    notes: rec.notes,
  })
  showModal.value = true
}

function openBatchAssign() {
  batchNoInput.value = ''
  showBatchModal.value = true
}

async function confirmBatchAssign() {
  batchAssigning.value = true
  try {
    if (selectAllMatching.value) {
      await ar.batchAssignBatchNo({ all: true, invoice_batch_no: batchNoInput.value }, reqParams())
    } else {
      await ar.batchAssignBatchNo({ ids: [...selectedIds.value], invoice_batch_no: batchNoInput.value })
    }
    const action = batchNoInput.value ? `批次号「${batchNoInput.value}」` : '（清空批次）'
    alert(`已为 ${selectedCount.value} 条记录设置${action}`)
    showBatchModal.value = false
    clearSelection()
    await load()
  } catch (e) { alert(e?.msg || '设置批次号失败')
  } finally { batchAssigning.value = false }
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
      reconciliation_date: recForm.reconciliation_date || null, account_diff_adjustment: recForm.account_diff_adjustment || 0,
      invoice_batch_no: recForm.invoice_batch_no || '',
      notes: recForm.notes,
    }
    if (editRec.value) await ar.updateRecord(editRec.value.id, payload)
    else await ar.createRecord(payload)
    showModal.value = false; await load()
  } catch (e) { alert(e?.msg || '保存失败')
  } finally { saving.value = false }
}

async function deleteRec(rec) {
  const amt = parseFloat(rec.estimated_amount || 0).toFixed(2)
  if (!confirm(`确定删除「${rec.short_name || rec.customer_name}」${rec.operation_year}年${rec.operation_month}月的应收记录（${amt} 元）？同月可能存在多条记录，请确认。`)) return
  try { await ar.deleteRecord(rec.id); await load() }
  catch (e) { alert(e?.msg || '删除失败') }
}

function togglePayments(id) { expandedPayments.value[id] = !expandedPayments.value[id] }

function openAddPayment(rec) {
  payRec.value = rec
  Object.assign(payForm, { amount: '', payment_date: todayCST(), notes: '' })
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
  if (!(amt > 0)) { alert('下账金额必须大于0'); return }
  advWoSaving.value = true
  try {
    await ar.addWriteoff(advWoSel.value.id, {
      amount: amt,
      writeoff_date: payForm.payment_date || todayCST(),
      ar_record_id: payRec.value.id,
    })
    showPayModal.value = false
    await load()
  } catch (e) { alert(e?.msg || '预收下账失败')
  } finally { advWoSaving.value = false }
}

// 跳转到预收预付页，预筛该项目的预收，便于在那里做核销冲抵。
function gotoAdvance() {
  const pid = payRec.value?.project_id
  showPayModal.value = false
  router.push({ path: '/ar/advances', query: { project_id: pid, direction: '预收' } })
}

async function savePayment() {
  if (!payForm.amount || !payForm.payment_date) { alert('金额和日期必填'); return }
  paySaving.value = true
  try {
    await ar.addPayment(payRec.value.id, payForm)
    showPayModal.value = false; await load()
  } catch (e) { alert(e?.msg || '保存失败')
  } finally { paySaving.value = false }
}

async function deletePayment(rec, pay) {
  if (!confirm(`确定删除第${pay.payment_no}次回款 ${pay.amount} 元？`)) return
  try { await ar.deletePayment(rec.id, pay.id); await load() }
  catch (e) { alert(e?.msg || '删除失败') }
}

async function downloadTemplate() {
  try {
    const res = await ar.recordTemplate()
    downloadBlob(res, '应收账款明细导入模板.xlsx')
  } catch (e) { alert(e?.msg || '模板下载失败') }
}

async function handleImport(e) {
  const f = e.target.files?.[0]; if (!f) return
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
  } finally { importing.value = false; if (fileInput.value) fileInput.value.value = '' }
}

async function exportData() {
  exporting.value = true
  try {
    const res = await ar.exportRecords(reqParams())
    downloadBlob(res, '应收账款明细.xlsx')
  } catch (e) { alert(e?.msg || '导出失败')
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
        <!-- 筛选 chip 栏紧跟 Tab 之后，省去独立一行 -->
        <div v-if="activeTab !== 'payments' && activeTab !== 'dunning'" class="filter-chipbar">
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
            <div class="kpi-item ok"><span class="kpi-k">已收</span><span class="kpi-v">{{ fmtAmt(kpiData.collection.collected_amount) }}</span></div>
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

      <div v-if="isDataTab" class="table-wrap dt-scroll" style="margin-top:12px">
        <table class="rec-table">
          <thead>
            <tr>
              <th v-if="auth.canDelete" class="sel-col">
                <input type="checkbox" :checked="pageAllSelected"
                  :indeterminate.prop="hasSelection && !pageAllSelected"
                  title="全选本页" @change="toggleSelectPage" />
              </th>
              <SortTh col="short_name" label="项目" />
              <SortTh col="operation" label="年月" class="ctr" />

              <!-- all -->
              <template v-if="activeTab === 'all'">
                <SortTh v-if="show('r_estimated_amount')" col="estimated" label="预估金额" class="amt" />
                <SortTh v-if="show('r_actual_invoice_amount')" col="invoiced" label="实际开票" class="amt" />
                <th v-if="show('r_tax_amount')" class="amt">税额</th>
                <th v-if="show('r_account_diff')" class="amt">账实差额</th>
                <SortTh v-if="show('r_outstanding')" col="outstanding" label="未收金额" class="amt" />
                <SortTh v-if="show('r_due_date')" col="due_date" label="应收到期" class="ctr" />
                <th v-if="show('r_reconciliation')" class="ctr">对账</th>
                <th v-if="show('r_payments')" class="ctr">回款</th>
                <th class="ctr">状态</th>
                <th class="ctr">责任状态</th>
                <th v-if="show('r_notes')" class="notes-col">备注</th>
              </template>
              <!-- reconciliation -->
              <template v-else-if="activeTab === 'reconciliation'">
                <SortTh v-if="show('r_estimated_amount')" col="estimated" label="预估金额" class="amt" />
                <th v-if="show('r_reconciliation')" class="ctr">对账状态</th>
                <SortTh v-if="show('r_reconciliation')" col="reconciliation_date" label="对账日期" class="ctr" />
                <SortTh v-if="show('r_due_date')" col="due_date" label="应收到期" class="ctr" />
                <th class="ctr">状态</th>
                <SortTh v-if="show('r_outstanding')" col="outstanding" label="未收金额" class="amt" />
              </template>
              <!-- invoice -->
              <template v-else-if="activeTab === 'invoice'">
                <th class="ctr">批次号</th>
                <SortTh v-if="show('r_estimated_amount')" col="estimated" label="预估金额" class="amt" />
                <SortTh v-if="show('r_actual_invoice_amount')" col="invoiced" label="实际开票额" class="amt" />
                <th v-if="show('r_tax_amount')" class="amt">税额</th>
                <SortTh v-if="show('r_invoice_date')" col="invoice_date" label="开票日期" class="ctr" />
                <th v-if="show('r_account_diff')" class="amt">账实差额</th>
                <th v-if="show('r_invoice_status')" class="ctr">开票状态</th>
              </template>
              <!-- collection -->
              <template v-else>
                <th class="amt">应收基础</th>
                <th v-if="show('r_payments')">回款记录</th>
                <SortTh v-if="show('r_outstanding')" col="outstanding" label="未收金额" class="amt" />
                <th v-if="show('r_invoice_status')" class="ctr">回款状态</th>
              </template>

              <th class="ctr">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="loading && !items.length">
              <td colspan="16" class="empty-cell">⏳ 加载中…</td>
            </tr>
            <tr v-else-if="!items.length">
              <td colspan="16" class="empty-cell">暂无数据</td>
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
                  <span class="ym-chip">{{ rec.operation_year }}/{{ String(rec.operation_month).padStart(2,'0') }}</span>
                </td>

                <!-- all -->
                <template v-if="activeTab === 'all'">
                  <td v-if="show('r_estimated_amount')" class="amt fw">{{ fmtCell(rec.estimated_amount) }}</td>
                  <td v-if="show('r_actual_invoice_amount')" class="amt">{{ rec.actual_invoice_amount ? fmtCell(rec.actual_invoice_amount) : '—' }}</td>
                  <td v-if="show('r_tax_amount')" class="amt text-muted">{{ rec.tax_amount ? fmtCell(rec.tax_amount) : '—' }}</td>
                  <td v-if="show('r_account_diff')" class="amt">{{ parseFloat(rec.account_diff_adjustment) !== 0 ? fmtCell(rec.account_diff_adjustment) : '—' }}</td>
                  <td v-if="show('r_outstanding')" class="amt" :class="parseFloat(rec.outstanding_amount) > 0 ? 'amt-warn' : 'amt-zero'">{{ parseFloat(rec.outstanding_amount) > 0 ? fmtCell(rec.outstanding_amount) : '—' }}</td>
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
                  <td v-if="show('r_estimated_amount')" class="amt fw">{{ fmtCell(rec.estimated_amount) }}</td>
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
                    <span :class="['status-pill', rec.invoice_status === '已结清' ? 'pill-ok' : rec.invoice_status === '部分回款' ? 'pill-blue' : rec.invoice_status === '已开票' ? 'pill-warn' : 'pill-muted']">{{ rec.invoice_status }}</span>
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
                    <button v-if="auth.canArWrite" class="add-pay-btn" @click="openAddPayment(rec)">+ 回款</button>
                  </td>
                  <td v-if="show('r_outstanding')" class="amt" :class="parseFloat(rec.outstanding_amount) > 0 ? 'amt-warn' : 'amt-zero'">{{ parseFloat(rec.outstanding_amount) > 0 ? fmtCell(rec.outstanding_amount) : '—' }}</td>
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
                      <span class="pay-amt">{{ fmtCell(pay.amount) }}</span>
                      <span class="pay-date">{{ pay.payment_date }}</span>
                      <span v-if="pay.source === '预收抵扣'" class="pay-src" title="由预收核销生成，须在预收预付页删除对应核销">预收抵扣</span>
                      <span v-if="pay.notes" class="pay-notes">{{ pay.notes }}</span>
                      <button v-if="auth.canDelete && pay.source !== '预收抵扣'" class="pay-del" @click="deletePayment(rec, pay)">删除</button>
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
          </div>
        </div>
      </Teleport>

      <!-- ══ 催款工作台 ══ -->
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
                <th class="ctr">运作年月</th>
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
                <td class="ctr"><span class="ym-chip">{{ r.operation_year }}/{{ String(r.operation_month).padStart(2,'0') }}</span></td>
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
          <input v-model="payFilters.pay_start" type="date" class="sel-mo" @change="loadPayments(true)" />
          <span style="color:var(--muted)">~</span>
          <input v-model="payFilters.pay_end" type="date" class="sel-mo" @change="loadPayments(true)" />
          <select v-model="payFilters.dept" class="sel-bu" @change="loadPayments(true)">
            <option value="">全部事业部</option>
            <option v-for="d in accessibleDepts" :key="d" :value="d">{{ d }}</option>
          </select>
          <input v-model="payFilters.q" placeholder="搜索项目" class="search-input" @input="loadPayments(true)" />
          <button class="btn btn-ghost btn-sm" :disabled="payExporting" @click="exportPayments">↓ 导出</button>
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
            <p style="font-size:13px;color:var(--muted);margin-bottom:14px">
              为 <strong>{{ selectedCount }}</strong> 条记录设置同一开票批次号，相同批次号的记录将合并开具一张发票。
              留空则清除批次号（取消合并）。
            </p>
            <label class="form-field span2">
              <span>批次号</span>
              <input v-model="batchNoInput" placeholder="如 PF-2026-001（留空=清除批次）" autofocus />
            </label>
          </div>
          <div class="modal-footer">
            <button class="btn btn-ghost" @click="showBatchModal = false">取消</button>
            <button class="btn btn-primary" :disabled="batchAssigning" @click="confirmBatchAssign">
              {{ batchAssigning ? '设置中…' : '确认设置' }}
            </button>
          </div>
        </div>
      </div>

      <!-- Payment Modal — 录入态：点遮罩不关闭，仅按钮可退出 -->
      <div v-if="showPayModal" class="modal-overlay">
        <div class="modal-box" style="max-width:460px">
          <div class="modal-header">
            <div>
              <h3>录入回款</h3>
              <div style="font-size:12px;color:var(--muted);margin-top:2px">{{ payRec?.short_name || payRec?.customer_name }}</div>
            </div>
            <button class="modal-close" @click="showPayModal = false">✕</button>
          </div>
          <div class="modal-body">
            <div v-if="payAdvance" class="adv-hint">
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
                <thead><tr><th>项目编号</th><th>项目简称</th><th>年月</th><th class="r">预估上账</th><th class="r">累计回款</th><th class="r">现存未收</th><th class="r">重算未收</th></tr></thead>
                <tbody>
                  <tr v-for="r in healthData.stale" :key="r.id">
                    <td>{{ r.project_no }}</td><td>{{ r.short_name }}</td>
                    <td>{{ r.operation_year }}-{{ r.operation_month }}</td>
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
                <thead><tr><th>项目编号</th><th>项目简称</th><th>年月</th><th class="r">预估上账</th><th class="r">账实差额</th><th class="r">累计回款</th><th class="r">超出</th></tr></thead>
                <tbody>
                  <tr v-for="r in healthData.negative" :key="r.id">
                    <td>{{ r.project_no }}</td><td>{{ r.short_name }}</td>
                    <td>{{ r.operation_year }}-{{ r.operation_month }}</td>
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

      <!-- 批量删除二次输入确认 -->
      <div v-if="showDelConfirm" class="modal-overlay" @click.self="showDelConfirm = false">
        <div class="modal-box" style="max-width:420px">
          <div class="modal-header">
            <div><h3>确认删除 {{ delConfirmCount }} 条应收明细</h3></div>
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
.metrics-bar { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; margin-bottom: 4px; padding: 9px 16px; background: rgba(0,0,0,0.02); border-radius: 12px; }
.metrics-div { width: 1px; align-self: stretch; min-height: 20px; background: rgba(0,0,0,0.1); margin: 0 2px; }
/* 汇总区：全集合计 / 时段合计 两行纵向堆叠，标签等宽使两行数据项左对齐 */
.metrics-summary { display: flex; flex-direction: column; gap: 7px; }
.metrics-sum-row { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
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
/* 汇总下钻行 + 合计行 */
.row-drill { cursor: pointer; }
.row-drill:hover { background: rgba(201,99,66,0.07); }
.group-total-row td { border-top: 2px solid rgba(0,0,0,0.1); padding: 11px 12px; background: rgba(0,0,0,0.02); }

/* Table — 紧凑：数据量大，尽量一屏多看 */
.rec-table { width: 100%; }
.rec-table th { font-size: 10.5px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); padding: 6px 10px; background: rgba(0,0,0,0.02); white-space: nowrap; }
.rec-table td { padding: 5px 10px; vertical-align: middle; font-size: 12.5px; }
/* 数据表内部滚动：表头吸顶 + 合计行吸底，行在中间滚动，合计始终停在表区底部
   （无需把整页拉到最底就能看到汇总）。max-height 留给上方筛选/指标条，可按需微调。 */
.dt-scroll { max-height: calc(100vh - 250px); overflow: auto; }
.dt-scroll .rec-table thead th { position: sticky; top: 0; z-index: 5; background: #f4f1ef; }
.dt-scroll .rec-table thead .sel-col { z-index: 6; }
/* 选择列 */
.sel-col { width: 30px; text-align: center; padding-left: 8px !important; padding-right: 4px !important; }
.sel-col input { cursor: pointer; }
.data-row { transition: background 0.12s; }
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
.pay-notes { font-size: 12px; color: var(--muted); font-style: italic; }
.pay-del { margin-left: auto; font-size: 11.5px; color: #c62828; background: none; border: none; cursor: pointer; }
.pay-del:hover { text-decoration: underline; }

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
</style>
