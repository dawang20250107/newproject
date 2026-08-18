<script setup>
import { confirmDlg } from '../../composables/confirm.js'
import { ref, reactive, computed, onMounted, watch, nextTick, onActivated } from 'vue'
import { useRoute } from 'vue-router'
import { useToast } from '../../composables/useToast.js'
import { useAuthStore } from '../../stores/auth.js'
import { DEPARTMENTS, yearCST, monthCST, todayCST } from '../../constants.js'
import ar from '../../api/ar.js'
import { fmtCompact } from '../../utils/format.js'
import { downloadBlob } from '../../utils/download.js'
import ImportPrecheckModal from '../../components/ImportPrecheckModal.vue'
import SelCell from '../../components/SelCell.vue'
import ColumnFilter from '../../components/ColumnFilter.vue'
import SkeletonRow from '../../components/SkeletonRow.vue'
import SchemePicker from '../../components/SchemePicker.vue'
import { useTableSchemes } from '../../composables/useTableSchemes.js'
import { useShiftSelect } from '../../composables/useShiftSelect.js'
import { useEscClearSelection } from '../../composables/useEscClearSelection.js'
import { useRangeSelection } from '../../composables/useRangeSelection.js'
import Amt from '../../components/Amt.vue'
import { useColWidths } from '../../composables/useColWidths.js'
import ContextMenu from '../../components/ContextMenu.vue'
import { useContextMenu } from '../../composables/useContextMenu.js'
import { copyText, copyRowTSV } from '../../utils/clipboard.js'
import { loadPref, savePref } from '../../utils/prefs.js'
import { useModalEsc } from '../../composables/useModalEsc.js'
import { useModalEnter } from '../../composables/useModalEnter.js'
import Pager from '../../components/Pager.vue'

const toast = useToast()
const auth = useAuthStore()
const route = useRoute()

const direction = ref('预收')          // '预收' | '预付' | 'diff' | 'suppliers'
const projectFilter = ref(null)        // { id, label } or null
const items = ref([])
const total = ref(0)
const kpi = ref(null)
const listSummary = ref(null)   // 筛选汇总（当前方向，随筛选/区间联动，来自列表接口）

// ── 多选与批量操作（与日常收款同款交互）─────────────────────────────────────
const selectedIds = ref(new Set())
const selCount = computed(() => selectedIds.value.size)
const hasSel = computed(() => selCount.value > 0)
const pageAll = computed(() => items.value.length > 0 && items.value.every(r => selectedIds.value.has(r.id)))
function toggleRow(id) { const s = new Set(selectedIds.value); s.has(id) ? s.delete(id) : s.add(id); selectedIds.value = s }
function toggleAll() { const s = new Set(selectedIds.value); if (pageAll.value) items.value.forEach(r => s.delete(r.id)); else items.value.forEach(r => s.add(r.id)); selectedIds.value = s }
function clearSel() { selectedIds.value = new Set() }
const { onRowSelClick } = useShiftSelect({ items, selectedIds, toggleSingle: toggleRow })
useEscClearSelection(() => hasSel.value, clearSel)
// Excel 式单元格区域选择（拖选/Shift 扩选/方向键移动/Ctrl+C 复制为 TSV）
const rangeSel = useRangeSelection({ ignoreCols: () => (canDelete.value ? [0] : []), onCopy: n => toast.success(`已复制 ${n} 个单元格，可粘贴进 Excel`) })
const selSum = computed(() => items.value.filter(r => selectedIds.value.has(r.id))
  .reduce((s, r) => s + (parseFloat(r.advance_amount) || 0), 0))
async function bulkDelete() {
  if (!hasSel.value) return
  if (!(await confirmDlg(`批量删除选中的 ${selCount.value} 笔${dirLabel.value}（金额合计 ${fmtAmt(selSum.value)}）？\n` +
                         `已有核销或退款关联的记录会自动跳过；此操作不可撤销。`, { danger: true }))) return
  try {
    const d = (await ar.bulkDeleteAdvances([...selectedIds.value])).data || {}
    const skipped = d.skipped || []
    if (skipped.length) toast.success(`已删除 ${d.deleted} 条，跳过 ${skipped.length} 条（${skipped[0].reason}）`)
    else toast.success(`已删除 ${d.deleted} 条`)
    clearSel(); load(true)
  } catch (e) { toast.error(e?.error || '批量删除失败') }
}
const loading = ref(false)
const loadErr = ref('')
const page = ref(1)
const size = ref(50)

// 顶部全局关键字 + 与列头无重复的页级控件（实际收付时间区间/核销状态）。
// 部门改由列头「交付部门」筛选，dept 不再出现于工具栏。
// 时间维度按「分期收付日期」（真实现金事件日，命中任意一期即入选）筛选；默认不限（台账余额是全周期视角），
// KPI/列表汇总/导出随区间联动（后端同一 _apply_advance_filters）。
const filters = reactive({ start_date: '', end_date: '', writeoff_status: '', q: '' })

// ── 实际收付时间预设（与日常收款同款交互）────────────────────────────────────
const DATE_PRESETS = [
  { k: 'all', l: '全部' },
  { k: 'today', l: '本日' }, { k: 'thisweek', l: '本周' },
  { k: 'thismonth', l: '本月' }, { k: 'lastmonth', l: '上月' },
  { k: 'thisquarter', l: '本季度' }, { k: 'lastquarter', l: '上季度' },
  { k: 'halfyear', l: '近半年' }, { k: 'thisyear', l: '本年' }, { k: 'lastyear', l: '去年' },
  { k: 'year1', l: '近一年' }, { k: 'd30', l: '近30天' }, { k: 'd90', l: '近90天' },
]
function _ymd(d) { return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}` }
function computePreset(k) {
  const t = new Date(), y = t.getFullYear(), m = t.getMonth(), d = t.getDate()
  const back = n => { const x = new Date(t); x.setDate(d - n); return x }
  const mk = (a, b) => ({ start: _ymd(a), end: _ymd(b) })
  switch (k) {
    case 'all': return { start: '', end: '' }
    case 'today': return mk(t, t)
    // 本周=周一~周日整周（含未来几天）：区间是完整自然周，而非周一到今天
    case 'thisweek': {
      const day = t.getDay()
      const mon = new Date(t); mon.setDate(d - (day === 0 ? 6 : day - 1))
      const sun = new Date(mon); sun.setDate(mon.getDate() + 6)
      return mk(mon, sun)
    }
    case 'thismonth': return mk(new Date(y, m, 1), t)
    case 'lastmonth': return mk(new Date(y, m - 1, 1), new Date(y, m, 0))
    case 'thisquarter': return mk(new Date(y, Math.floor(m / 3) * 3, 1), t)
    case 'lastquarter': { const qm = Math.floor(m / 3) * 3 - 3; return mk(new Date(y, qm, 1), new Date(y, qm + 3, 0)) }
    case 'halfyear': return mk(back(182), t)
    case 'thisyear': return mk(new Date(y, 0, 1), t)
    case 'lastyear': return mk(new Date(y - 1, 0, 1), new Date(y - 1, 11, 31))
    case 'year1': return mk(back(365), t)
    case 'd30': return mk(back(29), t)
    case 'd90': return mk(back(89), t)
  }
  return { start: '', end: '' }
}
const activePreset = ref('all')
let _applyingPreset = false
function applyPreset(k) {
  _applyingPreset = true
  const r = computePreset(k)
  filters.start_date = r.start; filters.end_date = r.end
  _applyingPreset = false
  activePreset.value = k
  load(true)
}
watch([() => filters.start_date, () => filters.end_date],
      () => { if (!_applyingPreset) activePreset.value = '' }, { flush: 'sync' })
// KPI 区间提示：让「页面汇总=当前筛选汇总」这一点对用户可见
const rangeActive = computed(() => !!(filters.start_date || filters.end_date))
const rangeLabel = computed(() => {
  if (!filters.start_date && !filters.end_date) return '全部期间'
  return `${filters.start_date || '…'} ~ ${filters.end_date || '…'}`
})

// ── Excel 风格列头筛选 + 排序 ───────────────────────────────────────────────
const colFilters = reactive({})          // field -> {op, value}
const sortField = ref('')
const sortOrder = ref('')                // 'asc' | 'desc' | ''
// 列头「交付部门」枚举选项（与工具栏部门口径一致）
const deptOptions = computed(() =>
  accessibleDepts.value.map(d => ({ value: d, label: d })))
function setColFilter(field, val) {
  if (val == null) delete colFilters[field]
  else colFilters[field] = val
  load(true)
}
function setSort(field, order) {
  sortField.value = order ? field : ''
  sortOrder.value = order || ''
  load(true)
}
// 通用筛选方案（表格方案基座）：保存列头筛选 + 排序为命名方案
const schemes = useTableSchemes('ar_advances', {
  colFilters, sortField, sortOrder,
  onApply: () => { load(true) },
})
function buildParams() {
  const p = { direction: direction.value, ...filters, page: page.value, size: size.value }
  if (projectFilter.value) p.project_id = projectFilter.value.id
  if (Object.keys(colFilters).length) p.filters = JSON.stringify(colFilters)
  if (sortField.value && sortOrder.value) { p.sort = sortField.value; p.order = sortOrder.value }
  return p
}

// ── 按单位聚合视图（客户/供应商 → 名下项目 两级下钻）─────────────────────────
const viewMode = ref('detail')          // detail=明细台账 | bycp=按单位聚合
const cpRows = ref([])
const cpCashBasis = ref(false)          // true=区间实际收付口径（选了收付时间）
const cpLoading = ref(false)
const expandedCps = ref(new Set())
function toggleCpExpand(cp) {
  const s = new Set(expandedCps.value); s.has(cp) ? s.delete(cp) : s.add(cp); expandedCps.value = s
}
async function loadByCp() {
  if (!isAdvanceMode.value || viewMode.value !== 'bycp') return
  cpLoading.value = true
  try {
    const p = { direction: direction.value, ...filters }
    if (projectFilter.value) p.project_id = projectFilter.value.id
    const res = await ar.advancesByCounterparty(p)
    cpRows.value = res.data.rows
    cpCashBasis.value = res.data.cash_basis
  } catch (e) { toast.error(e?.msg || e?.error || '聚合加载失败') }
  finally { cpLoading.value = false }
}
function switchView(v) {
  if (viewMode.value === v) return
  viewMode.value = v
  if (v === 'bycp') loadByCp()
}
// 下钻：聚合行 → 明细视图（单位精确匹配走列头筛选管线，与方案/漏斗状态一致）
function drillCp(row) {
  if (row.counterparty !== '（未填单位）') colFilters.counterparty = { op: 'eq', value: row.counterparty }
  viewMode.value = 'detail'
  load(true)
}
function drillProject(row, p) {
  if (row.counterparty !== '（未填单位）') colFilters.counterparty = { op: 'eq', value: row.counterparty }
  if (p.project_id) projectFilter.value = { id: p.project_id, label: p.short_name }
  else colFilters.project_short_name = { op: 'empty' }   // 散单：项目为空
  viewMode.value = 'detail'
  load(true)
}

// 部门下拉数据源：优先用与系统常量匹配的事业部；若用户真实部门名不在常量内
// （历史命名/二级部门等），回退到其真实可见部门，避免下拉为空导致无法选择部门。
const accessibleDepts = computed(() => {
  const eff = auth.effectiveDepts || []
  const matched = eff.filter(d => DEPARTMENTS.includes(d))
  if (matched.length) return matched
  return eff.length ? eff : (auth.allowedDepts || [])
})
const years = Array.from({ length: 5 }, (_, i) => yearCST() - 2 + i)
const months = Array.from({ length: 12 }, (_, i) => i + 1)
const fmtAmt = (v) => fmtCompact(v, { dash: '0.00' })

const show = k => auth.canArView(k)
const canCreate = computed(() => auth.canArWrite)
const canDelete = computed(() => auth.canDelete)
// 操作级权限：核销按当前方向取对应动作键；收付登记独立动作
const canWoAction = computed(() => auth.canAction(direction.value === '预收' ? 'wo_receive' : 'wo_prepaid'))
const canInstAction = computed(() => auth.canAction('adv_installment'))

const isReceive = computed(() => direction.value === '预收')
const isAdvanceMode = computed(() => direction.value === '预收' || direction.value === '预付')
const dirLabel = computed(() => direction.value === '预收' ? '预收' : '预付')
const partyLabel = computed(() => direction.value === '预收' ? '客户' : '供应商')

const importing = ref(false)
const exporting = ref(false)
const fileInput = ref(null)
const precheckResult = ref(null)
const precheckBusy = ref(false)
const pendingFile = ref(null)

async function load(reset = false) {
  if (!isAdvanceMode.value) return
  if (reset) page.value = 1
  loading.value = true
  loadErr.value = ''
  try {
    const params = buildParams()
    // KPI 与筛选合计须同口径：复用列表参数但去掉分页，带上项目过滤与列头筛选，
    // 否则顶部 KPI 反映的是更宽的范围，与底部「筛选合计」对不上
    const kpiParams = { ...params }; delete kpiParams.page; delete kpiParams.size
    const [res, k] = await Promise.all([
      ar.listAdvances(params),
      ar.advancesKpi(kpiParams),
    ])
    items.value = res.data.items
    total.value = res.data.total
    kpi.value = k.data[direction.value]
    listSummary.value = (res.data.summary || {})[direction.value] || null
    // 选中集只保留仍在当前列表中的行（翻页/切方向/筛选后清掉不可见的陈旧选中）
    const live = new Set(items.value.map(r => r.id))
    selectedIds.value = new Set([...selectedIds.value].filter(id => live.has(id)))
    // 聚合视图开着时同步刷新（筛选/区间/方向变化经由 load 汇聚于此，单点挂钩全覆盖）
    if (viewMode.value === 'bycp') loadByCp()
  } catch (e) { loadErr.value = e?.error || e?.message || '加载失败，请刷新重试'
  } finally { loading.value = false }
}

function switchDir(d) {
  if (d === direction.value) return
  direction.value = d
  if (d === 'suppliers') {
    loadSuppliers()
  } else if (d === 'diff') {
    diffView.value === 'project' ? loadDiff() : loadTimeline()
  } else {
    load(true)
  }
}

// ── 收付差异（预收 vs 预付，按项目简称对齐）─────────────────────────────────
const diffData = ref(null)
const diffLoading = ref(false)
const diffQ = ref('')
let diffTimer = null
const diffExpanded = ref(new Set())     // 展开的项目行
const diffAllOpen = ref(false)          // 一键展开/折叠总控

async function loadDiff() {
  diffLoading.value = true
  try {
    const res = await ar.advanceDiffSummary({ q: diffQ.value.trim() || undefined })
    diffData.value = res.data
    diffExpanded.value = new Set()
    diffAllOpen.value = false
  } catch (_) { diffData.value = null }
  finally { diffLoading.value = false }
}
function onDiffSearch() {
  clearTimeout(diffTimer)
  diffTimer = setTimeout(() => { diffView.value === 'project' ? loadDiff() : loadTimeline() }, 300)
}
function toggleDiffRow(name) {
  const s = new Set(diffExpanded.value)
  s.has(name) ? s.delete(name) : s.add(name)
  diffExpanded.value = s
}
function toggleDiffAll() {
  diffAllOpen.value = !diffAllOpen.value
  diffExpanded.value = diffAllOpen.value
    ? new Set((diffData.value?.rows || []).map(r => r.project))
    : new Set()
}

const diffClass = v => parseFloat(v) >= 0 ? 'amt-pos' : 'amt-neg'
const fmtDiff = v => (parseFloat(v) > 0 ? '+' : '') + fmtAmt(v)

function drillToProject(r) {
  filters.q = r.project
  direction.value = '预收'
  load(true)
}

// ── 收付差异 · 时间维度（按月 / 按周）─────────────────────────────────────────
// 三视角：按项目（全量累计 + 逐笔明细）/ 按月 / 按周。
// 按月/按周 = 选定年份后取该年时间线，再用「月/周」筛选框定位某一期，
// 表格与「按项目」完全一致（项目 × 预收/预付/当期差异 + 行展开逐笔明细）。
const diffView = ref('project')              // 'project' | 'month' | 'week'
const periodYear = ref(yearCST())
const periodKey = ref('')                    // 选中的期间 key，如 '2026-03' / '2026-W12'
const timelineData = ref(null)
const timelineLoading = ref(false)
const timelineExporting = ref(false)
const yearOptions = computed(() => {
  const y = yearCST(); return [y, y - 1, y - 2, y - 3, y - 4, y - 5]
})
// 期间下拉项（该年有发生记录的月/周；缺日期归入「未记录」）
const periodOptions = computed(() => {
  const list = (timelineData.value?.periods || []).map(p => ({ key: p.period, label: p.label }))
  if (timelineData.value?.null_period) list.push({ key: '__null__', label: '日期未记录' })
  return list
})
const currentPeriod = computed(() => {
  if (!timelineData.value) return null
  if (periodKey.value === '__null__') {
    const n = timelineData.value.null_period
    return n ? { ...n, label: '日期未记录' } : null
  }
  return (timelineData.value.periods || []).find(p => p.period === periodKey.value) || null
})

async function loadTimeline() {
  timelineLoading.value = true
  try {
    const res = await ar.advanceDiffTimeline({
      grain: diffView.value,
      start: `${periodYear.value}-01-01`,
      end: `${periodYear.value}-12-31`,
      q: diffQ.value.trim() || undefined,
    })
    timelineData.value = res.data
    // 默认定位最近一期（含数据）；若当前选中期仍存在则保留
    const keys = (res.data.periods || []).map(p => p.period)
    if (res.data.null_period) keys.push('__null__')
    if (!keys.includes(periodKey.value)) {
      periodKey.value = keys.length ? keys[keys.length - 1] : ''
    }
  } catch (_) { timelineData.value = null }
  finally { timelineLoading.value = false }
}
function setDiffView(v) {
  if (v === diffView.value) return
  diffView.value = v
  v === 'project' ? loadDiff() : loadTimeline()
}
// 方向/视图记忆：记住上次停留的 Tab 与差异视角，下次进页沿用（route.query 指定时仍以其为准）
watch([direction, diffView],
      () => savePref('ar_adv_state', { direction: direction.value, diffView: diffView.value }))
async function exportTimeline() {
  timelineExporting.value = true
  try {
    const res = await ar.advanceDiffTimelineExport({
      grain: diffView.value,
      start: `${periodYear.value}-01-01`,
      end: `${periodYear.value}-12-31`,
      q: diffQ.value.trim() || undefined,
    })
    downloadBlob(res, `收付差异-按${diffView.value === 'week' ? '周' : '月'}-${periodYear.value}.xlsx`)
  } catch (e) { toast.error(e?.msg || e?.error || '导出失败') }
  finally { timelineExporting.value = false }
}
// 「按项目」用 diffData，「按月/按周」用选中期间的项目拆分——同结构同模板
const diffRows = computed(() =>
  diffView.value === 'project' ? (diffData.value?.rows || []) : (currentPeriod.value?.projects || []))
const diffSummary = computed(() => {
  if (diffView.value === 'project') return diffData.value?.summary || null
  const p = currentPeriod.value
  if (!p) return null
  return { count: p.projects.length, in_total: p.in_total, out_total: p.out_total, diff: p.diff }
})
const diffBusy = computed(() => diffView.value === 'project' ? diffLoading.value : timelineLoading.value)
function onFilterChange() { load(true) }
let qTimer = null
function onQInput() { clearTimeout(qTimer); qTimer = setTimeout(() => load(true), 300) }
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / size.value)))
function go(p) { if (p < 1 || p > totalPages.value) return; page.value = p; load() }
const jumpPage = ref(1)
function doJump() {
  const tp = Math.ceil(total.value / size.value)
  const p = Math.max(1, Math.min(tp, jumpPage.value || 1))
  page.value = p; load()
}

// ── create / edit ──────────────────────────────────────────────────────────
const showModal = ref(false)
const editRec = ref(null)
const saving = ref(false)
const form = reactive({
  project_id: '', delivery_dept: '', counterparty: '',
  occur_year: yearCST(), occur_month: monthCST(), occur_date: todayCST(),
  advance_amount: '', expected_writeoff_date: '', notes: '',
})

const projects = ref([])
const projectKeyword = ref('')
const projKwInp = ref(null)     // 新增弹窗打开后自动聚焦的首个可编辑控件
const showProjList = ref(false)
let projectTimer = null
async function searchProjects(kw) {
  const res = await ar.listProjects({ size: 100, q: kw || undefined })
  projects.value = res.data.items
}
function onProjectKeywordInput() {
  showProjList.value = true
  if (!projectKeyword.value.trim()) form.project_id = ''
  clearTimeout(projectTimer)
  projectTimer = setTimeout(() => searchProjects(projectKeyword.value.trim()), 220)
}
let autoCounterparty = ''
function pickProject(p) {
  if (p) {
    form.project_id = p.id
    form.delivery_dept = p.delivery_dept
    projectKeyword.value = `${p.short_name}（${p.delivery_dept}）`
    if (direction.value === '预收' && p.customer_name &&
        (!form.counterparty || form.counterparty === autoCounterparty)) {
      form.counterparty = p.customer_name
      autoCounterparty = p.customer_name
    }
  } else {
    form.project_id = ''
    projectKeyword.value = ''
  }
  showProjList.value = false
}
function onProjBlur() { setTimeout(() => { showProjList.value = false }, 160) }

function openCreate() {
  editRec.value = null
  contSaved.value = 0
  // 录入记忆：沿用上次新增的交付部门；已不在可选部门内则回退第一个（选项目后仍以项目部门为准）
  const lastDept = loadPref('ar_adv_last_dept', '')
  Object.assign(form, {
    project_id: '',
    delivery_dept: accessibleDepts.value.includes(lastDept) ? lastDept : (accessibleDepts.value[0] || ''),
    counterparty: '',
    occur_year: yearCST(), occur_month: monthCST(), occur_date: todayCST(),
    advance_amount: '', expected_writeoff_date: '', notes: '',
  })
  projectKeyword.value = ''
  autoCounterparty = ''
  searchProjects('')
  showModal.value = true
  nextTick(() => projKwInp.value?.focus())
}
// 右键「以此新建」：以选中行为模板打开新建弹窗——沿用方向（当前 Tab）/交付部门/
// 往来单位/关联项目，金额、日期、备注等逐笔字段留空重填
function createFrom(rec) {
  openCreate()
  Object.assign(form, {
    project_id: rec.project_id || '',
    delivery_dept: rec.delivery_dept || form.delivery_dept,
    counterparty: rec.counterparty || '',
  })
  projectKeyword.value = rec.short_name || ''
  if (rec.short_name) searchProjects(rec.short_name)
}
function openEdit(rec) {
  editRec.value = rec
  Object.assign(form, {
    project_id: rec.project_id || '', delivery_dept: rec.delivery_dept || '',
    counterparty: rec.counterparty || '',
    occur_year: rec.occur_year, occur_month: rec.occur_month, occur_date: rec.occur_date || '',
    advance_amount: rec.advance_amount, expected_writeoff_date: rec.expected_writeoff_date || '',
    notes: rec.notes || '',
  })
  projectKeyword.value = rec.short_name || ''
  autoCounterparty = ''
  searchProjects(rec.short_name || '')
  showModal.value = true
}
async function save() {
  if (saving.value) return
  saving.value = true
  try {
    const payload = { direction: direction.value, ...form }
    if (!payload.project_id) delete payload.project_id
    if (editRec.value) await ar.updateAdvance(editRec.value.id, payload)
    else {
      await ar.createAdvance(payload)
      // 录入记忆：下次新增默认沿用本次交付部门
      savePref('ar_adv_last_dept', form.delivery_dept)
    }
    showModal.value = false
    await load()
  } catch (e) { toast.error(e?.msg || e?.error || '操作失败') }
  finally { saving.value = false }
}
// 「保存并继续」：连续录入不关弹窗——保留期间/上下文字段（方向/交付部门/发生年月/款项日期/预计核销日期），
// 清空逐笔字段（往来单位/关联项目/金额/备注）并聚焦项目搜索；计数随 openCreate 归零
const contSaved = ref(0)
async function saveAndNext() {
  if (saving.value) return
  saving.value = true
  try {
    const payload = { direction: direction.value, ...form }
    if (!payload.project_id) delete payload.project_id
    await ar.createAdvance(payload)
    savePref('ar_adv_last_dept', form.delivery_dept)
    contSaved.value++
    toast.success(`已连续保存 ${contSaved.value} 笔`)
    Object.assign(form, { project_id: '', counterparty: '', advance_amount: '', notes: '' })
    projectKeyword.value = ''
    autoCounterparty = ''
    load()
    nextTick(() => projKwInp.value?.focus())
  } catch (e) { toast.error(e?.msg || e?.error || '操作失败') }
  finally { saving.value = false }
}
async function removeRec(rec) {
  if (!(await confirmDlg(`确认删除该${dirLabel.value}记录（${rec.counterparty}）？\n若该记录已有核销或退款关联，系统将拦截——需先在「核销」明细删除核销、或在日常收款解除退款关联。`))) return
  try { await ar.deleteAdvance(rec.id); await load() }
  catch (e) { toast.error(e?.msg || e?.error || '操作失败') }
}

// ── writeoffs ───────────────────────────────────────────────────────────────
const showWoModal = ref(false)
const woRec = ref(null)
const woList = ref([])
const woForm = reactive({ amount: '', writeoff_date: todayCST(), notes: '', ar_record_id: '' })
const woSaving = ref(false)
const woOffsetRecords = ref([])
const canOffset = computed(() =>
  woRec.value?.direction === '预收' &&
  (!!woRec.value?.project_id || !!woRec.value?.counterparty) &&
  woOffsetRecords.value.length > 0)

async function openWriteoffs(rec) {
  woRec.value = rec
  Object.assign(woForm, { amount: '', writeoff_date: todayCST(), notes: '', ar_record_id: '' })
  woOffsetRecords.value = []
  showWoModal.value = true
  await Promise.all([refreshWriteoffs(), loadOffsetRecords(rec)])
}
async function loadOffsetRecords(rec) {
  if (rec.direction !== '预收') return
  const params = rec.project_id ? { project_id: rec.project_id }
    : (rec.counterparty ? { customer: rec.counterparty } : null)
  if (!params) return
  try {
    const res = await ar.advanceOffsettable(params)
    woOffsetRecords.value = res.data.items || []
  } catch (_) { woOffsetRecords.value = [] }
}
async function refreshWriteoffs() {
  const res = await ar.listWriteoffs(woRec.value.id)
  woList.value = res.data
}
const woAmountOver = computed(() => {
  const a = parseFloat(woForm.amount)
  return !isNaN(a) && a > Number(woRec.value?.balance_amount || 0) + 0.005
})
async function addWriteoff() {
  if (!(parseFloat(woForm.amount) > 0)) { toast.error('核销金额必须大于0'); return }
  if (woAmountOver.value) { toast.error('核销金额不能超过未核销余额'); return }
  woSaving.value = true
  try {
    const payload = { ...woForm }
    if (!payload.ar_record_id) delete payload.ar_record_id
    await ar.addWriteoff(woRec.value.id, payload)
    Object.assign(woForm, { amount: '', writeoff_date: todayCST(), notes: '', ar_record_id: '' })
    await loadOffsetRecords(woRec.value)
    await refreshWriteoffs()
    await load()
    const fresh = items.value.find(r => r.id === woRec.value.id)
    if (fresh) woRec.value = fresh
  } catch (e) { toast.error(e?.msg || e?.error || '操作失败') }
  finally { woSaving.value = false }
}
async function delWriteoff(w) {
  if (!(await confirmDlg('确认删除该核销记录？'))) return
  try {
    await ar.deleteWriteoff(woRec.value.id, w.id)
    await refreshWriteoffs(); await load()
    const fresh = items.value.find(r => r.id === woRec.value.id)
    if (fresh) woRec.value = fresh
  } catch (e) { toast.error(e?.msg || e?.error || '操作失败') }
}

// ── 收付明细（多次到账/付出；总额=明细之和，派生） ───────────────────────────
const showInstModal = ref(false)
const instRec = ref(null)
const instList = ref([])
const instForm = reactive({ amount: '', occur_date: todayCST(), notes: '' })
const instBusy = ref(false)
async function openInstallments(rec) {
  instRec.value = rec
  Object.assign(instForm, { amount: '', occur_date: todayCST(), notes: '' })
  instList.value = []
  showInstModal.value = true
  loadTransfers()
  try {
    const res = await ar.listAdvInstallments(rec.id)
    instList.value = res.data.items
  } catch (_) { instList.value = [] }
}
// 新增收付卡片：长列表时底部表单要拉很久 → 右上角按钮弹出固定居中卡片。
// Esc/取消 关卡片；Enter=保存；「保存并继续」连录多笔不关卡片；遮罩仅在未填写时可点关。
const showInstAdd = ref(false)
const instAmtInput = ref(null)
const instListBody = ref(null)
const lastInstId = ref(null)
function openInstAdd() {
  Object.assign(instForm, { amount: '', occur_date: todayCST(), notes: '' })
  showInstAdd.value = true
  nextTick(() => instAmtInput.value?.focus())
}
function instAddMaskClick() {
  if (!String(instForm.amount).trim() && !instForm.notes.trim()) showInstAdd.value = false
}
async function saveInstAdd(stay = false) {
  if (instBusy.value) return
  if (!parseFloat(instForm.amount)) { toast.error('收付金额不能为0（可负=退回）'); return }
  if (!instForm.occur_date) { toast.error('请选择收付日期'); return }
  instBusy.value = true
  try {
    const res = await ar.addAdvInstallment(instRec.value.id, { ...instForm })
    instList.value = res.data.items
    Object.assign(instForm, { amount: '', occur_date: todayCST(), notes: '' })
    await load()
    const fresh = items.value.find(r => r.id === instRec.value.id)
    if (fresh) instRec.value = fresh
    // 新行高亮并滚入视野（列表内滚动，不动弹窗）
    const added = instList.value[instList.value.length - 1]
    lastInstId.value = added?.id ?? null
    nextTick(() => {
      const el = instListBody.value
      if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
    })
    toast.success(`已登记第 ${added?.install_no ?? instList.value.length} 笔`)
    if (stay) nextTick(() => instAmtInput.value?.focus())
    else showInstAdd.value = false
  } catch (e) { toast.error(e?.msg || e?.error || '操作失败') }
  finally { instBusy.value = false }
}
// ── 转移（单位间/项目间权益转移，非现金事件；跨事业部仅超管）────────────────
const canTransferAction = computed(() => auth.canAction('adv_transfer'))
const showTransfer = ref(false)
const transferBusy = ref(false)
const transferList = reactive({ tin: [], tout: [] })
const transferForm = reactive({
  amount: '', date: todayCST(), reason: '', mode: 'existing',
  to_advance_id: '', target_label: '', target_kw: '',
  new_counterparty: '', new_project_id: '', new_project_kw: '',
})
const targetOpts = ref([])
const targetProjOpts = ref([])
const transferAmtInput = ref(null)

async function loadTransfers() {
  if (!instRec.value) return
  try {
    const res = await ar.listAdvTransfers(instRec.value.id)
    transferList.tin = res.data.transfers_in || []
    transferList.tout = res.data.transfers_out || []
  } catch { transferList.tin = []; transferList.tout = [] }
}
const migInsts = ref([])           // 按笔迁移：选中的收付明细数组（空=按金额权益划转）
const migCarry = ref('auto')       // 核销随迁：auto=自动同步（推荐）/ none=仅迁收付
const migPureWoSum = ref(0)        // 纯登记核销池合计（预览随迁上限）
const instSel = ref(new Set())     // 收付明细多选（批量迁移）
function toggleInstSel(id) {
  const st = new Set(instSel.value)
  st.has(id) ? st.delete(id) : st.add(id)
  instSel.value = st
}
function toggleInstSelAll() {
  instSel.value = instSel.value.size === instList.value.length
    ? new Set() : new Set(instList.value.map(i => i.id))
}
function _resetTransferForm() {
  Object.assign(transferForm, {
    amount: '', date: todayCST(), reason: '', mode: 'existing',
    to_advance_id: '', target_label: '', target_kw: '',
    new_counterparty: '', new_project_id: '', new_project_kw: '',
  })
  targetOpts.value = []; targetProjOpts.value = []
}
function openTransfer() {
  migInsts.value = []
  _resetTransferForm()
  showTransfer.value = true
  searchTargets('')
  nextTick(() => transferAmtInput.value?.focus())
}
// 按笔迁移：收付当初记错了对象 → 整笔物理迁走（现金流水随行更正）；支持多笔批量
async function openInstMigrate(list) {
  migInsts.value = Array.isArray(list) ? list : [list]
  migCarry.value = 'auto'
  _resetTransferForm()
  showTransfer.value = true
  searchTargets('')
  migPureWoSum.value = 0
  try {
    const res = await ar.listWriteoffs(instRec.value.id)
    const rows = Array.isArray(res.data) ? res.data : (res.data.items || [])
    migPureWoSum.value = rows
      .filter(w => !w.ar_record_id && !w.payment_id)
      .reduce((s, w) => s + (parseFloat(w.amount) || 0), 0)
  } catch { migPureWoSum.value = 0 }
}
function migrateSelected() {
  const list = instList.value.filter(i => instSel.value.has(i.id))
  if (!list.length) { toast.error('请先勾选要迁移的收付明细'); return }
  openInstMigrate(list)
}
const migAmt = computed(() => migInsts.value.reduce((s, i) => s + (parseFloat(i.amount) || 0), 0))
// 自动同步随迁核销 = min(迁移额, 已核销合计, 纯登记核销池)
const migCarryAmt = computed(() => {
  if (migCarry.value !== 'auto' || !instRec.value) return 0
  return +Math.min(migAmt.value, Number(instRec.value.written_off_amount) || 0,
                   migPureWoSum.value).toFixed(2)
})
// 迁移后源余额预览 = 现余额 − 迁移额 + 随迁核销
const migSrcAfter = computed(() => {
  if (!migInsts.value.length || !instRec.value) return 0
  return +(Number(instRec.value.balance_amount) - migAmt.value + migCarryAmt.value).toFixed(2)
})
let targetTimer = null
async function searchTargets(kw) {
  try {
    const res = await ar.listAdvances({ direction: direction.value, q: kw || undefined, size: 8 })
    targetOpts.value = (res.data.items || []).filter(r => r.id !== instRec.value?.id)
  } catch { targetOpts.value = [] }
}
function onTargetKw() {
  transferForm.to_advance_id = ''; transferForm.target_label = ''
  clearTimeout(targetTimer)
  targetTimer = setTimeout(() => searchTargets(transferForm.target_kw.trim()), 220)
}
function pickTarget(r) {
  transferForm.to_advance_id = r.id
  transferForm.target_label = `${r.counterparty || '—'}${r.short_name ? '·' + r.short_name : ''}（余额 ${fmtAmt(r.balance_amount)}）`
  transferForm.target_kw = ''
  targetOpts.value = []
}
let tpTimer = null
async function searchTargetProjects(kw) {
  try {
    const res = await ar.listProjects({ size: 8, q: kw || undefined })
    targetProjOpts.value = res.data.items || []
  } catch { targetProjOpts.value = [] }
}
function onTargetProjKw() {
  transferForm.new_project_id = ''
  clearTimeout(tpTimer)
  tpTimer = setTimeout(() => searchTargetProjects(transferForm.new_project_kw.trim()), 220)
}
function pickTargetProject(pr) {
  transferForm.new_project_id = pr.id
  transferForm.new_project_kw = `${pr.short_name}（${pr.delivery_dept}）`
  targetProjOpts.value = []
}
async function submitTransfer() {
  if (transferBusy.value) return
  if (!migInsts.value.length && !(parseFloat(transferForm.amount) > 0)) { toast.error('请填写转移金额（大于0）'); return }
  if (!transferForm.date) { toast.error('请选择转移日期'); return }
  if (!transferForm.reason.trim()) { toast.error('请填写转移原因（如：合同主体变更/项目落位），以便追溯'); return }
  if (migInsts.value.length && migSrcAfter.value < 0) {
    toast.error('迁移后源余额为负：可自动随迁的纯登记核销不足，请先撤销对应关联核销'); return
  }
  const body = { transfer_date: transferForm.date, reason: transferForm.reason }
  if (migInsts.value.length) {
    body.installment_ids = migInsts.value.map(i => i.id)
    body.carry_mode = migCarry.value
  } else {
    body.amount = transferForm.amount
  }
  if (transferForm.mode === 'existing') {
    if (!transferForm.to_advance_id) { toast.error('请选择目标记录'); return }
    body.to_advance_id = transferForm.to_advance_id
  } else {
    if (!transferForm.new_counterparty.trim()) { toast.error('请填写目标往来单位'); return }
    body.new_target = { counterparty: transferForm.new_counterparty.trim() }
    if (transferForm.new_project_id) body.new_target.project_id = transferForm.new_project_id
  }
  transferBusy.value = true
  try {
    if (migInsts.value.length) {
      await ar.migrateAdvInstallments(instRec.value.id, body)
      instSel.value = new Set()
      const res = await ar.listAdvInstallments(instRec.value.id)
      instList.value = res.data.items
    } else {
      await ar.addAdvTransfer(instRec.value.id, body)
    }
    toast.success(migInsts.value.length ? '已整笔迁移' : '已转移')
    showTransfer.value = false
    await loadTransfers()
    await load()
    const fresh = items.value.find(r => r.id === instRec.value.id)
    if (fresh) instRec.value = fresh
  } catch (e) { toast.error(e?.msg || e?.error || '操作失败') }
  finally { transferBusy.value = false }
}
async function undoTransfer(t) {
  if (!(await confirmDlg(`撤销转移「${t.from.counterparty} → ${t.to.counterparty}：${fmtAmt(t.amount)}」？双方余额将复原。`))) return
  try {
    await ar.deleteAdvTransfer(instRec.value.id, t.id)
    toast.success('已撤销')
    await loadTransfers()
    // 整笔迁移撤销会把收付/核销行搬回来 → 同步刷新明细列表
    try {
      const res = await ar.listAdvInstallments(instRec.value.id)
      instList.value = res.data.items
    } catch {}
    await load()
    const fresh = items.value.find(r => r.id === instRec.value.id)
    if (fresh) instRec.value = fresh
  } catch (e) { toast.error(e?.msg || e?.error || '操作失败') }
}
// 核销迁移（核销挂错记录的更正；仅纯登记核销）
const migrateWo = ref(null)
const migrateKw = ref('')
const migrateOpts = ref([])
let migrateTimer = null
function openMigrate(w) {
  migrateWo.value = w
  migrateKw.value = ''
  migrateOpts.value = []
  searchMigrateTargets('')
}
async function searchMigrateTargets(kw) {
  try {
    const res = await ar.listAdvances({ direction: direction.value, q: kw || undefined, size: 8 })
    migrateOpts.value = (res.data.items || []).filter(r => r.id !== woRec.value?.id)
  } catch { migrateOpts.value = [] }
}
function onMigrateKw() { clearTimeout(migrateTimer); migrateTimer = setTimeout(() => searchMigrateTargets(migrateKw.value.trim()), 220) }
async function doMigrate(target) {
  if (!(await confirmDlg(`将第${migrateWo.value.writeoff_no}笔核销（${fmtAmt(migrateWo.value.amount)}）迁移到「${target.counterparty || '—'}${target.short_name ? '·' + target.short_name : ''}」？`))) return
  try {
    await ar.migrateAdvWriteoff(woRec.value.id, migrateWo.value.id, { to_advance_id: target.id })
    toast.success('已迁移')
    migrateWo.value = null
    const res = await ar.listWriteoffs(woRec.value.id)
    woList.value = Array.isArray(res.data) ? res.data : (res.data.items || [])
    await load()
    const fresh = items.value.find(r => r.id === woRec.value.id)
    if (fresh) woRec.value = fresh
  } catch (e) { toast.error(e?.msg || e?.error || '操作失败') }
}

async function delInstallment(i) {
  if (!(await confirmDlg(`删除第${i.install_no}笔收付 ${i.amount} 元？总额与未核销余额将随之回退。`))) return
  instBusy.value = true
  try {
    const res = await ar.deleteAdvInstallment(instRec.value.id, i.id)
    instList.value = res.data.items
    await load()
    const fresh = items.value.find(r => r.id === instRec.value.id)
    if (fresh) instRec.value = fresh
  } catch (e) { toast.error(e?.msg || e?.error || '操作失败') }
  finally { instBusy.value = false }
}

// ── template / import / export ────────────────────────────────────────────────
async function downloadTemplate() {
  try {
    const res = await ar.advanceTemplate()
    downloadBlob(res, '预收预付导入模板.xlsx')
  } catch (e) { toast.error(e?.msg || e?.error || '操作失败') }
}
async function handleImport(e) {
  const f = e.target.files?.[0]; if (!f) return
  pendingFile.value = f
  precheckResult.value = null
  importing.value = true
  try {
    const fd = new FormData(); fd.append('file', f)
    const pr = await ar.precheckAdvances(fd); const pd = pr.data
    if (pd.skipPrecheck) { await doImport(f); return }
    if ((pd.attention || 0) > 0) { precheckResult.value = pd; return }
    await doImport(f)
  } catch (e) { toast.error(e?.msg || e?.error || '操作失败') }
  finally { importing.value = false; if (fileInput.value) fileInput.value.value = '' }
}

async function doImport(f) {
  importing.value = true
  try {
    const fd = new FormData(); fd.append('file', f)
    const res = await ar.importAdvances(fd); const d = res.data
    if (d.rejected) {
      toast.error(d.message || '导入未执行，请按提示修正后重新导入')
    } else {
      toast.success(`导入完成：创建 ${d.created} 条`)
    }
    await load()
  } catch (e) { toast.error(e?.msg || e?.error || '操作失败') }
  finally { importing.value = false }
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
    const res = await ar.exportAdvances(buildParams())
    downloadBlob(res, `${dirLabel.value}明细.xlsx`)
  } catch (e) { toast.error(e?.msg || e?.error || '操作失败') }
  finally { exporting.value = false }
}

function woStatusClass(s) {
  return s === '已核销' ? 'pill-ok' : s === '部分核销' ? 'pill-blue' : 'pill-muted'
}

function clearProjectFilter() { projectFilter.value = null; load(true) }

// ── Supplier management ───────────────────────────────────────────────────────
const supplierItems = ref([])
const supplierTotal = ref(0)
const supplierLoading = ref(false)
const supplierFilters = reactive({ type: '', dept: '', q: '' })

const showSupplierModal = ref(false)
const editSupplier = ref(null)
const supplierSaving = ref(false)
const supplierForm = reactive({
  name: '', supplier_type: 'public', project_id: '', delivery_dept: '',
  contact: '', notes: '',
})
const supplierProjKeyword = ref('')
const supplierProjects = ref([])
const showSupplierProjList = ref(false)
let supplierProjTimer = null

async function loadSuppliers() {
  supplierLoading.value = true
  try {
    const res = await ar.listSuppliers({ ...supplierFilters })
    supplierItems.value = res.data.items
    supplierTotal.value = res.data.total
  } finally { supplierLoading.value = false }
}

let supplierQTimer = null
function onSupplierQInput() {
  clearTimeout(supplierQTimer)
  supplierQTimer = setTimeout(loadSuppliers, 300)
}

async function searchSupplierProjects(kw) {
  try {
    const res = await ar.listProjects({ size: 100, q: kw || undefined })
    supplierProjects.value = res.data.items
  } catch (e) {
    supplierProjects.value = []
  }
}

// 切到「私有」时确保项目列表已加载（覆盖打开弹窗时异步竞态/失败的情况）
watch(() => supplierForm.supplier_type, (t) => {
  if (t === 'private' && !supplierProjects.value.length) {
    searchSupplierProjects(supplierProjKeyword.value.trim())
  }
})
function onSupplierProjKeywordInput() {
  showSupplierProjList.value = true
  if (!supplierProjKeyword.value.trim()) supplierForm.project_id = ''
  clearTimeout(supplierProjTimer)
  supplierProjTimer = setTimeout(() => searchSupplierProjects(supplierProjKeyword.value.trim()), 220)
}
function pickSupplierProject(p) {
  if (p) {
    supplierForm.project_id = p.id
    supplierForm.delivery_dept = p.delivery_dept
    supplierProjKeyword.value = `${p.short_name}（${p.delivery_dept}）`
  } else {
    supplierForm.project_id = ''
    supplierProjKeyword.value = ''
  }
  showSupplierProjList.value = false
}
function onSupplierProjBlur() { setTimeout(() => { showSupplierProjList.value = false }, 160) }

function openCreateSupplier() {
  editSupplier.value = null
  Object.assign(supplierForm, {
    name: '', supplier_type: 'public', project_id: '',
    delivery_dept: accessibleDepts.value[0] || '',
    contact: '', notes: '',
  })
  supplierProjKeyword.value = ''
  searchSupplierProjects('')
  showSupplierModal.value = true
}
function openEditSupplier(s) {
  editSupplier.value = s
  Object.assign(supplierForm, {
    name: s.name, supplier_type: s.supplier_type,
    project_id: s.project_id || '', delivery_dept: s.delivery_dept || '',
    contact: s.contact || '', notes: s.notes || '',
  })
  supplierProjKeyword.value = s.project_short_name
    ? `${s.project_short_name}（${s.delivery_dept}）` : ''
  if (s.project_short_name) searchSupplierProjects(s.project_short_name)
  showSupplierModal.value = true
}
async function saveSupplier() {
  supplierSaving.value = true
  try {
    const payload = { ...supplierForm }
    if (!payload.project_id) delete payload.project_id
    if (editSupplier.value) await ar.updateSupplier(editSupplier.value.id, payload)
    else await ar.createSupplier(payload)
    showSupplierModal.value = false
    await loadSuppliers()
  } catch (e) { toast.error(e?.msg || e?.error || '操作失败') }
  finally { supplierSaving.value = false }
}
async function removeSupplier(s) {
  if (!(await confirmDlg(`确认删除供应商「${s.name}」？`))) return
  try { await ar.deleteSupplier(s.id); await loadSuppliers() }
  catch (e) { toast.error(e?.msg || e?.error || '操作失败') }
}

// ── 右键上下文菜单 ────────────────────────────────────────────────────────────
async function copyField(val, label) {
  const ok = await copyText(val)
  ok ? toast.success(`已复制：${label}`) : toast.error('复制失败')
}
async function copyWholeRow(row, cols) {
  const ok = await copyRowTSV(row, cols, { header: true })
  ok ? toast.success('已复制整行（含表头，可粘贴到 Excel）') : toast.error('复制失败')
}

// 双击数据行：预收/预付记录 = 打开收付明细（查看为主，编辑走右键）；供应商表 = 编辑
function onRowDblClick(item, e, handler = openEdit, allowed = canCreate.value) {
  if (e.target.closest('input, button, select, textarea, a')) return
  if (!allowed) return
  handler(item)
}

// 预收/预付记录表
const ctxRec = useContextMenu()
const REC_COPY_COLS = [
  { key: 'counterparty', label: '往来单位' },
  { key: 'short_name', label: '项目' },
  { key: 'delivery_dept', label: '交付部门' },
  { key: 'occur_date', label: '款项日期' },
  { key: 'advance_amount', label: '总额', format: v => fmtAmt(v) },
  { key: 'written_off_amount', label: '已核销', format: v => fmtAmt(v) },
  { key: 'balance_amount', label: '余额', format: v => fmtAmt(v) },
  { key: 'writeoff_status', label: '核销状态' },
]
const ctxRecItems = computed(() => {
  const r = ctxRec.menu.payload
  if (!r) return []
  return [
    { key: 'inst', label: '收付明细', icon: 'payment', hidden: !(canCreate.value || canInstAction.value), action: x => openInstallments(x) },
    { key: 'wo', label: '核销', icon: 'refresh', hidden: !(canCreate.value || canWoAction.value), action: x => openWriteoffs(x) },
    { key: 'edit', label: '编辑', icon: 'edit', shortcut: 'E', hidden: !canCreate.value, action: x => openEdit(x) },
    { key: 'create-from', label: '以此新建', icon: 'plus', hidden: !canCreate.value, action: x => createFrom(x) },
    { divider: true },
    {
      key: 'copy', label: '复制', icon: 'copy',
      children: [
        { key: 'copy-row', label: '复制整行', icon: 'copy', shortcut: '⌘C', action: x => copyWholeRow(x, REC_COPY_COLS) },
        { divider: true },
        { key: 'copy-cp', label: '往来单位', icon: 'customer', hidden: !r.counterparty, action: x => copyField(x.counterparty, x.counterparty) },
        { key: 'copy-proj', label: '项目', icon: 'cell', hidden: !r.short_name, action: x => copyField(x.short_name, x.short_name) },
        { key: 'copy-bal', label: '余额', icon: 'cell', action: x => copyField(fmtAmt(x.balance_amount), fmtAmt(x.balance_amount)) },
      ],
    },
    { divider: true },
    { key: 'del', label: '删除', icon: 'trash', danger: true, hidden: !canDelete.value, action: x => removeRec(x) },
  ]
})

// 供应商表
const ctxSup = useContextMenu()
const SUP_COPY_COLS = [
  { key: 'name', label: '供应商' },
  { key: 'supplier_type', label: '类型', format: v => (v === 'private' ? '私有' : '公共') },
  { key: 'project_short_name', label: '项目' },
  { key: 'delivery_dept', label: '交付部门' },
  { key: 'contact', label: '联系人' },
  { key: 'prepaid_balance', label: '预付余额', format: v => fmtAmt(v) },
]
const ctxSupItems = computed(() => {
  const s = ctxSup.menu.payload
  if (!s) return []
  return [
    { key: 'edit', label: '编辑', icon: 'edit', shortcut: 'E', hidden: !canCreate.value, action: x => openEditSupplier(x) },
    { divider: true },
    {
      key: 'copy', label: '复制', icon: 'copy',
      children: [
        { key: 'copy-row', label: '复制整行', icon: 'copy', shortcut: '⌘C', action: x => copyWholeRow(x, SUP_COPY_COLS) },
        { divider: true },
        { key: 'copy-name', label: '供应商名称', icon: 'customer', action: x => copyField(x.name, x.name) },
        { key: 'copy-contact', label: '联系人', icon: 'cell', hidden: !s.contact, action: x => copyField(x.contact, x.contact) },
      ],
    },
    { divider: true },
    { key: 'del', label: '删除', icon: 'trash', danger: true, hidden: !canDelete.value, action: x => removeSupplier(x) },
  ]
})

// 弹窗 Esc 关闭：嵌套的项目选择层放最后（先关内层再关外层）
useModalEsc(
  [() => showModal.value, () => (showModal.value = false)],
  [() => showWoModal.value, () => (showWoModal.value = false)],
  [() => showInstModal.value, () => (showInstModal.value = false)],
  [() => showSupplierModal.value, () => (showSupplierModal.value = false)],
  [() => showProjList.value, () => (showProjList.value = false)],
  [() => showSupplierProjList.value, () => (showSupplierProjList.value = false)],
  [() => showInstAdd.value, () => (showInstAdd.value = false)],
  [() => showTransfer.value, () => (showTransfer.value = false)],
  [() => !!migrateWo.value, () => (migrateWo.value = null)],
)
// Ctrl/Cmd+Enter 提交新增/编辑弹窗（save 内部自带 saving 防重）
useModalEnter(() => showModal.value, () => save())

// keep-alive：命中 App.vue include 白名单；返回秒开，数据后台刷新（首次激活跳过，onMounted 已加载）
defineOptions({ name: 'AdvancesPage' })
let _kaFirst = true
onActivated(() => { if (_kaFirst) { _kaFirst = false; return } load(true) })

onMounted(async () => {
  const q = route.query || {}
  if (q.direction === '预收' || q.direction === '预付') direction.value = q.direction
  if (q.project_id) {
    projectFilter.value = { id: Number(q.project_id), label: q.project_no || `项目#${q.project_id}` }
  }
  // 方向/视图记忆：route.query 优先（direction / project_id 下钻均视为显式指定方向）；脏值回退默认
  const saved = loadPref('ar_adv_state') || {}
  if (['project', 'month', 'week'].includes(saved.diffView)) diffView.value = saved.diffView
  if (!q.direction && !q.project_id &&
      ['预收', '预付', 'diff', 'suppliers'].includes(saved.direction)) direction.value = saved.direction
  // 有默认方案则套用并由其触发加载；否则常规加载。
  // 恢复到差异/供应商 Tab 时方案加载不会触发对应视图，需按 switchDir 同款分支补加载
  const applied = await schemes.loadAndApplyDefault()
  if (direction.value === 'suppliers') loadSuppliers()
  else if (direction.value === 'diff') diffView.value === 'project' ? loadDiff() : loadTimeline()
  else if (!applied) load(true)
})
</script>

<template>
  <div>
    <div class="topbar" style="align-items:flex-start">
      <div>
        <h1>预收预付</h1>
        <div style="font-size:13px;color:var(--muted);margin-top:2px">
          围绕项目台账登记预收/预付款，跟踪核销进度与挂账账龄，并打通现金流
        </div>
      </div>
    </div>

    <!-- direction / mode tabs -->
    <div class="dir-tabs">
      <button :class="['dir-tab', { active: direction === '预收' }]" @click="switchDir('预收')">预收（客户预付款）</button>
      <button :class="['dir-tab', { active: direction === '预付' }]" @click="switchDir('预付')">预付（付供应商）</button>
      <button :class="['dir-tab', { active: direction === 'diff' }]" @click="switchDir('diff')">收付差异</button>
      <div class="dir-tab-sep"></div>
      <button :class="['dir-tab', { active: direction === 'suppliers' }]" @click="switchDir('suppliers')">供应商池</button>
    </div>

    <!-- KPI (advances only)：随时间区间/筛选联动的「筛选汇总」 -->
    <div v-if="isAdvanceMode && kpi" class="kpi-row">
      <div class="kpi"><div class="kpi-k">{{ dirLabel }}笔数<span class="kpi-range">{{ rangeLabel }}</span></div><div class="kpi-v">{{ kpi.count }} 笔</div></div>
      <div v-if="show('adv_amount')" class="kpi"><div class="kpi-k">{{ dirLabel }}{{ (filters.start_date || filters.end_date) ? '实际收付' : '金额' }}<span class="kpi-range">{{ rangeLabel }}</span></div><div class="kpi-v" :title="(filters.start_date || filters.end_date) ? '区间内按分期收付日期统计的实际收付合计（非记录整笔金额）' : ''"><Amt :v="kpi.advance_amount" :fmt="fmtAmt" /></div></div>
      <div v-if="show('adv_writeoff')" class="kpi"><div class="kpi-k">{{ rangeActive ? '区间核销' : '已核销' }}<span class="kpi-range">{{ rangeLabel }}</span></div><div class="kpi-v" :title="rangeActive ? '区间内按核销日期统计的核销合计' : ''"><Amt :v="kpi.written_off" :fmt="fmtAmt" /><span v-if="!rangeActive" class="kpi-sub">{{ kpi.writeoff_rate }}%</span></div></div>
      <div v-if="show('adv_writeoff') && !isReceive && Number(kpi.refunded) > 0" class="kpi"><div class="kpi-k">已退款</div><div class="kpi-v"><Amt :v="kpi.refunded" :fmt="fmtAmt" /></div></div>
      <div v-if="show('adv_writeoff')" class="kpi accent"><div class="kpi-k">未核销余额</div><div class="kpi-v"><Amt :v="kpi.balance" :fmt="fmtAmt" /></div></div>
      <div v-if="show('adv_writeoff')" class="kpi warn"><div class="kpi-k">逾期挂账</div><div class="kpi-v"><Amt :v="kpi.overdue_balance" :fmt="fmtAmt" /><span class="kpi-sub">{{ kpi.overdue_count }} 笔</span></div></div>
    </div>

    <!-- ── Advance list (预收/预付) ── -->
    <template v-if="isAdvanceMode">
      <div class="card fh-fill">
        <div class="filter-row">
          <input v-model="filters.q" class="inp sm global-search" placeholder="全局搜索：往来单位 / 项目 / 编号 / 备注…" @input="onQInput" />
          <select v-model="filters.writeoff_status" class="sel sm" @change="onFilterChange">
            <option value="">核销状态</option>
            <option value="未核销">未核销</option>
            <option value="部分核销">部分核销</option>
            <option value="已核销">已核销</option>
          </select>
          <button v-if="projectFilter" class="proj-chip" @click="clearProjectFilter">
            项目：{{ projectFilter.label }} ✕
          </button>
          <SchemePicker :ctl="schemes" :can-public="auth.canArWrite" :is-super-admin="auth.isSuperAdmin" />
          <!-- 视图切换：明细台账 / 按单位聚合（客户或供应商 → 名下项目 两级下钻） -->
          <div class="view-seg" role="tablist">
            <button :class="['vs-btn', { on: viewMode === 'detail' }]" @click="switchView('detail')">明细</button>
            <button :class="['vs-btn', { on: viewMode === 'bycp' }]" @click="switchView('bycp')">按{{ partyLabel }}</button>
          </div>
          <div class="spacer"></div>
          <button class="btn btn-ghost btn-sm" @click="downloadTemplate">下载模板</button>
          <label v-if="canCreate" class="btn btn-ghost btn-sm" :class="{ disabled: importing }">
            {{ importing ? '导入中…' : '导入' }}
            <input ref="fileInput" type="file" accept=".xlsx,.xls" style="display:none" @change="handleImport" />
          </label>
          <button class="btn btn-ghost btn-sm" :disabled="exporting" @click="exportData">{{ exporting ? '导出中…' : '导出' }}</button>
          <button v-if="canCreate" class="btn btn-primary btn-sm" @click="openCreate">+ 新增{{ dirLabel }}</button>
        </div>

        <!-- 实际收付时间（款项日期）区间：KPI / 列表 / 汇总 / 导出全部随之联动 -->
        <div class="adv-timebar">
          <span class="tb-lbl">收付时间</span>
          <div class="tb-presets">
            <button v-for="p in DATE_PRESETS" :key="p.k" class="pchip" :class="{ on: activePreset === p.k }"
                    @click="applyPreset(p.k)">{{ p.l }}</button>
          </div>
          <div class="tb-range">
            <input v-model="filters.start_date" type="date" class="inp sm tb-date" @change="onFilterChange" />
            <span class="tb-sep">~</span>
            <input v-model="filters.end_date" type="date" class="inp sm tb-date" @change="onFilterChange" />
            <button v-if="filters.start_date || filters.end_date" class="btn btn-ghost btn-sm"
                    @click="applyPreset('all')">清除</button>
          </div>
        </div>

        <!-- ══ 按单位聚合视图：客户/供应商 → 名下项目 两级下钻 ══ -->
        <div v-if="viewMode === 'bycp'" class="table-scroll page-scroll">
          <table class="data-table cp-agg-table">
            <thead>
              <tr>
                <th>{{ partyLabel }}（往来单位）</th>
                <th class="ctr">笔数</th>
                <th class="ctr">项目数</th>
                <th class="amt" :title="cpCashBasis ? '区间内按分期收付日期统计的实际收付合计' : '记录全额合计'">{{ dirLabel }}{{ cpCashBasis ? '实际收付' : '金额' }}</th>
                <th v-if="show('adv_writeoff')" class="amt">{{ cpCashBasis ? '区间核销' : '已核销' }}</th>
                <th v-if="show('adv_writeoff') && !isReceive" class="amt">已退款</th>
                <th v-if="show('adv_writeoff')" class="amt">未核销余额</th>
                <th v-if="show('adv_writeoff')" class="amt">逾期挂账</th>
                <th class="ctr">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="cpLoading && !cpRows.length"><td colspan="9" class="empty">⏳ 加载中…</td></tr>
              <tr v-else-if="!cpRows.length"><td colspan="9" class="empty">当前筛选无{{ dirLabel }}记录</td></tr>
              <template v-for="row in cpRows" :key="row.counterparty">
                <tr class="cp-row" @click="toggleCpExpand(row.counterparty)">
                  <td class="cp-name">
                    <span class="cp-caret">{{ expandedCps.has(row.counterparty) ? '▾' : '▸' }}</span>{{ row.counterparty }}
                  </td>
                  <td class="ctr">{{ row.count }}</td>
                  <td class="ctr">{{ row.project_count }}<span v-if="row.projects.some(p => !p.project_id)" class="loose-tag" title="含未挂项目的散单">+散单</span></td>
                  <td class="amt num-strong">{{ fmtAmt(row.advance_amount) }}</td>
                  <td v-if="show('adv_writeoff')" class="amt">{{ fmtAmt(row.written_off) }}</td>
                  <td v-if="show('adv_writeoff') && !isReceive" class="amt">{{ Number(row.refunded) ? fmtAmt(row.refunded) : '—' }}</td>
                  <td v-if="show('adv_writeoff')" class="amt num-strong">{{ fmtAmt(row.balance) }}</td>
                  <td v-if="show('adv_writeoff')" class="amt" :class="{ 'txt-warn': Number(row.overdue_balance) > 0 }">{{ Number(row.overdue_balance) ? fmtAmt(row.overdue_balance) : '—' }}</td>
                  <td class="ctr"><button class="btn btn-ghost btn-sm" @click.stop="drillCp(row)">查看明细</button></td>
                </tr>
                <tr v-for="p in (expandedCps.has(row.counterparty) ? row.projects : [])"
                    :key="row.counterparty + '·' + (p.project_id ?? 'loose')" class="cp-proj-row">
                  <td class="cp-proj-name">└ {{ p.short_name }}</td>
                  <td class="ctr">{{ p.count }}</td>
                  <td class="ctr">—</td>
                  <td class="amt">{{ fmtAmt(p.advance_amount) }}</td>
                  <td v-if="show('adv_writeoff')" class="amt">{{ fmtAmt(p.written_off) }}</td>
                  <td v-if="show('adv_writeoff') && !isReceive" class="amt">{{ Number(p.refunded) ? fmtAmt(p.refunded) : '—' }}</td>
                  <td v-if="show('adv_writeoff')" class="amt">{{ fmtAmt(p.balance) }}</td>
                  <td v-if="show('adv_writeoff')" class="amt" :class="{ 'txt-warn': Number(p.overdue_balance) > 0 }">{{ Number(p.overdue_balance) ? fmtAmt(p.overdue_balance) : '—' }}</td>
                  <td class="ctr"><button class="btn btn-ghost btn-sm" @click.stop="drillProject(row, p)">查看明细</button></td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>

        <div v-if="viewMode === 'detail'" class="table-scroll page-scroll range-root" :ref="rangeSel.setRoot">
          <table class="data-table">
            <thead>
              <tr>
                <th v-if="canDelete" class="sel-col"><input type="checkbox" :checked="pageAll" @change="toggleAll" title="全选本页" /></th>
                <th v-if="show('adv_counterparty')"><ColumnFilter label="往来单位" field="counterparty" type="text" :model-value="colFilters.counterparty" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('counterparty',v)" @sort="o=>setSort('counterparty',o)" /></th>
                <th><ColumnFilter label="项目简称" field="project_short_name" type="text" :model-value="colFilters.project_short_name" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('project_short_name',v)" @sort="o=>setSort('project_short_name',o)" /></th>
                <th><ColumnFilter label="部门" field="delivery_dept" type="enum" :options="deptOptions" :model-value="colFilters.delivery_dept" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('delivery_dept',v)" @sort="o=>setSort('delivery_dept',o)" /></th>
                <th title="合作入驻/业务归属年月，不参与金额统计——金额按分期实际收付日期统计">入驻年月</th>
                <th><ColumnFilter label="款项日期" field="occur_date" type="date" :model-value="colFilters.occur_date" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('occur_date',v)" @sort="o=>setSort('occur_date',o)" /></th>
                <th v-if="show('adv_amount')" class="amt"><ColumnFilter :label="rangeActive ? `${dirLabel}实际收付` : `${dirLabel}金额`" field="advance_amount" type="number" :model-value="colFilters.advance_amount" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('advance_amount',v)" @sort="o=>setSort('advance_amount',o)" /></th>
                <th v-if="show('adv_writeoff')" class="amt"><ColumnFilter :label="rangeActive ? '区间核销' : '已核销'" field="written_off_amount" type="number" :model-value="colFilters.written_off_amount" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('written_off_amount',v)" @sort="o=>setSort('written_off_amount',o)" /></th>
                <th v-if="show('adv_writeoff')" class="amt"><ColumnFilter label="未核销余额" field="balance_amount" type="number" :model-value="colFilters.balance_amount" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('balance_amount',v)" @sort="o=>setSort('balance_amount',o)" /></th>
                <th v-if="show('adv_writeoff')" class="ctr">核销状态</th>
                <th v-if="show('adv_expected_date')" class="ctr"><ColumnFilter label="挂账账龄" field="expected_writeoff_date" type="date" :model-value="colFilters.expected_writeoff_date" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('expected_writeoff_date',v)" @sort="o=>setSort('expected_writeoff_date',o)" /></th>
                <th class="adv-notes-col">备注</th>
              </tr>
            </thead>
            <tbody>
              <template v-if="loading && !items.length">
                <SkeletonRow v-for="n in 8" :key="n" :cols="12" />
              </template>
              <tr v-else-if="loadErr">
                <td colspan="12" class="empty">⚠️ {{ loadErr }} <button style="border:none;background:none;color:var(--primary);cursor:pointer;font-size:13px;text-decoration:underline" @click="load()">重试</button></td>
              </tr>
              <tr v-else-if="!items.length"><td colspan="12" class="empty">暂无{{ dirLabel }}记录</td></tr>
              <tr v-for="(r, idx) in items" :key="r.id" :class="{ 'row-sel': selectedIds.has(r.id) }"
                  @contextmenu.prevent="ctxRec.open($event, r)" @dblclick="onRowDblClick(r, $event, openInstallments, canCreate || canInstAction)">
                <SelCell v-if="canDelete" :idx="idx" :id="r.id" :checked="selectedIds.has(r.id)" :on-sel="onRowSelClick" />
                <td v-if="show('adv_counterparty')">{{ r.counterparty || '—' }}</td>
                <td><span v-if="r.short_name" class="proj-name">{{ r.short_name }}</span><span v-else>—</span></td>
                <td>{{ r.delivery_dept }}</td>
                <td>{{ r.occur_year }}-{{ String(r.occur_month).padStart(2, '0') }}</td>
                <td>{{ r.occur_date || '—' }}</td>
                <td v-if="show('adv_amount')" class="amt num-strong">{{ fmtAmt(r.advance_amount) }}</td>
                <td v-if="show('adv_writeoff')" class="amt">{{ fmtAmt(r.written_off_amount) }}</td>
                <td v-if="show('adv_writeoff')" class="amt num-strong">{{ fmtAmt(r.balance_amount) }}</td>
                <td v-if="show('adv_writeoff')" class="ctr">
                  <span class="status-pill" :class="woStatusClass(r.writeoff_status)">{{ r.writeoff_status }}</span>
                </td>
                <td v-if="show('adv_expected_date')" class="ctr">
                  <span v-if="r.is_overdue" class="status-pill pill-danger">逾期{{ r.overdue_days }}天</span>
                  <span v-else-if="r.balance_amount > 0" class="status-pill pill-muted">挂账{{ r.pending_days }}天</span>
                  <span v-else>—</span>
                </td>
                <td class="adv-notes-cell" :title="r.notes">{{ r.notes || '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- 选中态操作条：有选中时替换筛选合计栏 -->
        <div v-if="hasSel" class="adv-sumbar sumbar-sel">
          <span class="sb-k">已选 {{ selCount }} 笔</span>
          <span class="sb-i">金额合计 <b><Amt :v="selSum" :fmt="fmtAmt" /></b></span>
          <button class="btn btn-danger btn-sm" @click="bulkDelete">批量删除</button>
          <button class="btn btn-ghost btn-sm" @click="clearSel">取消选择</button>
          <span class="sb-range">Shift 可区间选 · Esc 取消</span>
        </div>
        <!-- 筛选汇总：与当前时间区间/搜索/列头筛选完全同口径（来自列表接口） -->
        <div v-else-if="listSummary" class="adv-sumbar">
          <span class="sb-k">筛选合计</span>
          <span class="sb-i">{{ listSummary.count }} 笔</span>
          <span v-if="show('adv_amount')" class="sb-i">{{ dirLabel }}{{ rangeActive ? '实际收付' : '金额' }} <b><Amt :v="listSummary.advance_amount" :fmt="fmtAmt" /></b></span>
          <span v-if="show('adv_writeoff')" class="sb-i">{{ rangeActive ? '区间核销' : '已核销' }} <b><Amt :v="listSummary.written_off" :fmt="fmtAmt" /></b></span>
          <span v-if="show('adv_writeoff') && !isReceive && Number(listSummary.refunded) > 0" class="sb-i">已退款 <b><Amt :v="listSummary.refunded" :fmt="fmtAmt" /></b></span>
          <span v-if="show('adv_writeoff')" class="sb-i">未核销余额 <b class="sb-accent"><Amt :v="listSummary.balance" :fmt="fmtAmt" /></b></span>
          <span v-if="show('adv_writeoff') && Number(listSummary.overdue_balance) > 0" class="sb-i">逾期挂账 <b class="sb-warn"><Amt :v="listSummary.overdue_balance" :fmt="fmtAmt" /></b></span>
          <span class="sb-range">{{ rangeLabel }}</span>
        </div>

        <Pager v-if="viewMode === 'detail'" v-model:page="page" v-model:size="size" :total="total" storage-key="ar_advances" @change="load()" />
      </div>
    </template>

    <!-- ── 收付差异：预收 vs 预付（按项目，含月差异/周差异列）── -->
    <template v-else-if="direction === 'diff'">
      <!-- 视角切换：按项目（累计+逐笔）/ 按月 / 按周（项目×期间透视表） -->
      <div class="diff-viewbar">
        <div class="diff-view-tabs">
          <button :class="{ act: diffView === 'project' }" @click="setDiffView('project')">按项目</button>
          <button :class="{ act: diffView === 'month' }" @click="setDiffView('month')">按月</button>
          <button :class="{ act: diffView === 'week' }" @click="setDiffView('week')">按周</button>
        </div>
      </div>

      <!-- ════ 统一表格：按项目（全量）/ 按月 / 按周（选定期间）——同结构同模板 ════ -->
      <div class="card fh-fill">
        <div class="filter-row">
          <input v-model="diffQ" class="inp sm" style="width:200px" placeholder="搜项目简称" @input="onDiffSearch" />
          <!-- 按月/按周：年份 + 期间（月/周）筛选框 -->
          <template v-if="diffView !== 'project'">
            <select v-model.number="periodYear" class="sel sm" @change="loadTimeline">
              <option v-for="y in yearOptions" :key="y" :value="y">{{ y }} 年</option>
            </select>
            <select v-model="periodKey" class="sel sm" style="min-width:118px">
              <option v-if="!periodOptions.length" value="">该年无发生</option>
              <option v-for="o in periodOptions" :key="o.key" :value="o.key">{{ o.label }}</option>
            </select>
          </template>
          <span v-if="diffSummary" class="tl-stat">
            {{ diffSummary.count }} 项 · 预收 <b style="color:var(--c-success)">{{ fmtAmt(diffSummary.in_total) }}</b> ·
            预付 <b style="color:#ef6c00">{{ fmtAmt(diffSummary.out_total) }}</b> ·
            差异 <b :style="{ color: parseFloat(diffSummary.diff) >= 0 ? 'var(--c-success)' : 'var(--c-danger)' }">{{ fmtAmt(diffSummary.diff) }}</b>
          </span>
          <div style="flex:1"></div>
          <button v-if="diffView === 'project'" class="btn btn-ghost btn-sm" @click="toggleDiffAll">
            {{ diffAllOpen ? '▲ 一键折叠' : '▼ 一键展开' }}
          </button>
          <button v-else class="btn btn-ghost btn-sm" :disabled="timelineExporting" @click="exportTimeline">
            {{ timelineExporting ? '导出中…' : '↓ 导出' }}
          </button>
        </div>
        <div v-if="diffBusy" class="empty" style="padding:30px;text-align:center">⏳ 加载中…</div>
        <div v-else-if="!diffRows.length" class="empty" style="padding:30px;text-align:center">
          {{ diffView === 'project'
            ? '暂无预收/预付数据（未挂项目的散单归入「（未挂项目）」组）'
            : '该期间暂无预收/预付发生记录' }}
        </div>
        <div v-else class="table-wrap page-scroll">
          <table class="diff-table">
            <thead>
              <tr>
                <th class="dt-proj">项目简称 / 部门</th>
                <th class="dt-amt">预收金额</th>
                <th class="dt-amt">预付金额</th>
                <th class="dt-amt">{{ diffView === 'project' ? '差异（预收−预付）' : (diffView === 'week' ? '周差异' : '月差异') }}</th>
                <th v-if="diffView === 'project'" class="dt-notes">备注</th>
                <th class="dt-caret"></th>
              </tr>
            </thead>
            <tbody>
              <template v-for="r in diffRows" :key="r.project">
                <tr class="diff-row" @click="toggleDiffRow(r.project)" @dblclick.stop="drillToProject(r)">
                  <td class="dt-proj">
                    <span class="dt-name" :title="r.project">{{ r.project }}</span>
                    <span class="dt-dept">{{ (r.dept || '—').replace('事业部', '') }}</span>
                  </td>
                  <td class="dt-amt" style="color:var(--c-success)">{{ parseFloat(r.in_total) ? fmtAmt(r.in_total) : '—' }}</td>
                  <td class="dt-amt" style="color:#ef6c00">{{ parseFloat(r.out_total) ? fmtAmt(r.out_total) : '—' }}</td>
                  <td class="dt-amt fw" :style="{ color: parseFloat(r.diff) >= 0 ? 'var(--c-success)' : 'var(--c-danger)' }">{{ fmtAmt(r.diff) }}</td>
                  <td v-if="diffView === 'project'" class="dt-notes" :title="r.notes">{{ r.notes || '—' }}</td>
                  <td class="dt-caret">{{ diffExpanded.has(r.project) ? '▲' : '▼' }}</td>
                </tr>
                <tr v-if="diffExpanded.has(r.project)" class="diff-detail-row">
                  <td :colspan="diffView === 'project' ? 6 : 5">
                    <div class="diff-detail">
                      <div class="dd-col">
                        <div class="dd-head in">预收明细 · {{ r.in_items.length }} 笔</div>
                        <div v-if="!r.in_items.length" class="dd-empty">无预收记录</div>
                        <div v-for="i in r.in_items" :key="'i' + i.id" class="dd-item">
                          <span class="dd-date">{{ i.occur_date }}</span>
                          <b class="dd-amt in">{{ fmtAmt(i.amount) }}</b>
                          <span class="dd-party" :title="i.counterparty">{{ i.counterparty }}</span>
                          <em v-if="parseFloat(i.balance) > 0" class="dd-bal">余 {{ fmtAmt(i.balance) }}</em>
                        </div>
                      </div>
                      <div class="dd-col">
                        <div class="dd-head out">预付明细 · {{ r.out_items.length }} 笔</div>
                        <div v-if="!r.out_items.length" class="dd-empty">无预付记录</div>
                        <div v-for="i in r.out_items" :key="'o' + i.id" class="dd-item">
                          <span class="dd-date">{{ i.occur_date }}</span>
                          <b class="dd-amt out">{{ fmtAmt(i.amount) }}</b>
                          <span class="dd-party" :title="i.counterparty">{{ i.counterparty }}</span>
                          <em v-if="parseFloat(i.balance) > 0" class="dd-bal">余 {{ fmtAmt(i.balance) }}</em>
                        </div>
                      </div>
                    </div>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>
      </div>
    </template>

    <!-- ── Supplier pool ── -->
    <template v-else>
      <div class="card fh-fill">
        <div class="filter-row">
          <select v-model="supplierFilters.type" class="sel sm" @change="loadSuppliers">
            <option value="">全部类型</option>
            <option value="private">私有（绑项目）</option>
            <option value="public">公共（绑事业部）</option>
          </select>
          <select v-if="accessibleDepts.length > 1" v-model="supplierFilters.dept" class="sel sm" @change="loadSuppliers">
            <option value="">全部部门</option>
            <option v-for="d in accessibleDepts" :key="d" :value="d">{{ d }}</option>
          </select>
          <input v-model="supplierFilters.q" class="inp sm" placeholder="搜索供应商名称 / 联系人" @input="onSupplierQInput" />
          <div class="spacer"></div>
          <button v-if="canCreate" class="btn btn-primary btn-sm" @click="openCreateSupplier">+ 新增供应商</button>
        </div>

        <div class="table-scroll page-scroll">
          <table class="data-table">
            <thead>
              <tr>
                <th>供应商名称</th>
                <th class="ctr">类型</th>
                <th>关联项目</th>
                <th>部门</th>
                <th>联系人</th>
                <th class="amt">预付余额</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="!supplierLoading && !supplierItems.length">
                <td colspan="6" class="empty">暂无供应商，点击「新增供应商」添加</td>
              </tr>
              <tr v-for="s in supplierItems" :key="s.id" @contextmenu.prevent="ctxSup.open($event, s)" @dblclick="onRowDblClick(s, $event, openEditSupplier)">
                <td><b>{{ s.name }}</b><div v-if="s.notes" class="dept-tag">{{ s.notes }}</div></td>
                <td class="ctr">
                  <span class="status-pill" :class="s.supplier_type === 'private' ? 'pill-blue' : 'pill-muted'">
                    {{ s.supplier_type === 'private' ? '私有' : '公共' }}
                  </span>
                </td>
                <td><span v-if="s.project_short_name" class="proj-name">{{ s.project_short_name }}</span><span v-else>—</span></td>
                <td>{{ s.delivery_dept }}</td>
                <td>{{ s.contact || '—' }}</td>
                <td class="amt">
                  <span :class="{ 'num-strong': parseFloat(s.prepaid_balance) > 0, 'bal-positive': parseFloat(s.prepaid_balance) > 0 }">
                    {{ parseFloat(s.prepaid_balance) > 0 ? fmtAmt(s.prepaid_balance) : '—' }}
                  </span>
                  <span v-if="s.prepaid_count > 0" class="kpi-sub"> {{ s.prepaid_count }}笔</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-if="supplierLoading" style="text-align:center;padding:20px;color:var(--muted)">加载中…</div>
      </div>
    </template>

    <!-- ── create / edit advance modal ── -->
    <div v-if="showModal" class="modal-mask" @click.self="showModal = false">
      <div class="modal">
        <h3>{{ editRec ? '编辑' : '新增' }}{{ dirLabel }}</h3>
        <div class="form-grid">
          <label class="fld full">
            <span>关联项目（可选，搜索选择；留空则仅填往来单位）</span>
            <div class="combo">
              <input ref="projKwInp" v-model="projectKeyword" class="inp" placeholder="搜索项目简称 / 编号…"
                     @focus="showProjList = true" @input="onProjectKeywordInput" @blur="onProjBlur" />
              <button v-if="form.project_id || projectKeyword" type="button" class="combo-clear"
                      @mousedown.prevent="pickProject(null)">×</button>
              <ul v-if="showProjList" class="combo-list">
                <li class="combo-opt muted" @mousedown.prevent="pickProject(null)">不关联项目（仅填往来单位）</li>
                <li v-for="p in projects" :key="p.id" class="combo-opt"
                    :class="{ on: form.project_id === p.id }" @mousedown.prevent="pickProject(p)">
                  <span>{{ p.short_name }}</span><span class="combo-dept">{{ p.delivery_dept }}</span>
                </li>
                <li v-if="!projects.length" class="combo-opt muted">无匹配项目</li>
              </ul>
            </div>
          </label>
          <label class="fld" v-if="!form.project_id">
            <span>交付部门 <em>*</em></span>
            <select v-model="form.delivery_dept" class="sel">
              <option v-for="d in accessibleDepts" :key="d" :value="d">{{ d }}</option>
            </select>
          </label>
          <label class="fld"><span>{{ partyLabel }}（往来单位） <em>*</em></span>
            <input v-model="form.counterparty" class="inp" :placeholder="`${partyLabel}名称`" /></label>
          <label class="fld"><span>入驻年 <em>*</em></span>
            <select v-model.number="form.occur_year" class="sel"><option v-for="y in years" :key="y" :value="y">{{ y }}</option></select></label>
          <label class="fld"><span>入驻月 <em>*</em></span>
            <select v-model.number="form.occur_month" class="sel"><option v-for="m in months" :key="m" :value="m">{{ m }}</option></select></label>
          <label class="fld"><span>款项日期</span><input v-model="form.occur_date" type="date" class="inp" /></label>
          <label class="fld"><span>{{ dirLabel }}金额（元）</span><input v-model="form.advance_amount" type="number" step="0.01" class="inp" /></label>
          <label class="fld"><span>预计核销日期</span><input v-model="form.expected_writeoff_date" type="date" class="inp" /></label>
          <label class="fld full"><span>备注</span><input v-model="form.notes" class="inp" /></label>
        </div>
        <div class="modal-foot">
          <button class="btn btn-ghost" @click="showModal = false">取消</button>
          <button v-if="!editRec" class="btn btn-ghost" :disabled="saving" @click="saveAndNext">保存并继续</button>
          <button class="btn btn-primary" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存' }}</button>
        </div>
      </div>
    </div>

    <!-- ── writeoff modal ── -->
    <div v-if="showWoModal" class="modal-mask" @click.self="showWoModal = false">
      <div class="modal inst-modal">
        <h3>核销 · {{ woRec.counterparty }}</h3>
        <div class="wo-summary">
          <span>{{ dirLabel }}金额 <b>{{ fmtAmt(woRec.advance_amount) }}</b></span>
          <span>已核销 <b>{{ fmtAmt(woRec.written_off_amount) }}</b></span>
          <span class="hl">未核销余额 <b>{{ fmtAmt(woRec.balance_amount) }}</b></span>
        </div>
        <div class="inst-scroll">
        <table class="data-table compact">
          <thead>
            <tr>
              <th>#</th><th class="amt">核销金额</th><th>核销日期</th>
              <th>冲抵明细</th><th>备注</th><th v-if="canDelete || canWoAction"></th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!woList.length"><td :colspan="(canDelete || canWoAction) ? 6 : 5" class="empty">暂无核销记录</td></tr>
            <tr v-for="w in woList" :key="w.id">
              <td>{{ w.writeoff_no }}</td>
              <td class="amt">{{ fmtAmt(w.amount) }}</td>
              <td>{{ w.writeoff_date }}</td>
              <td>
                <span v-if="w.ar_record_id" class="offset-badge" :title="`已生成预收抵扣回款 · ${w.ar_project_no || ''}`">↳ 转回款</span>
                <span v-else-if="w.payment_id" class="offset-badge pay-badge" :title="`关联排款: ${w.payment_payee || ''}`">↳ 排款#{{ w.payment_id }}</span>
                <span v-else>—</span>
              </td>
              <td>{{ w.notes || '—' }}</td>
              <td v-if="canDelete || canWoAction">
                <button v-if="!w.ar_record_id && !w.payment_id && (canCreate || canTransferAction)"
                        class="lnk" title="核销挂错记录时迁移到另一条同方向记录" @click="openMigrate(w)">迁移</button>
                <button class="lnk danger" @click="delWriteoff(w)">删除</button>
              </td>
            </tr>
          </tbody>
        </table>
        </div>
        <div v-if="canCreate || canWoAction" class="wo-add">
          <div v-if="canOffset" class="wo-offset-row">
            <span class="wo-offset-lbl">冲抵应收：</span>
            <select v-model="woForm.ar_record_id" class="inp wo-offset-sel">
              <option value="">不冲抵（仅登记核销）</option>
              <option v-for="o in woOffsetRecords" :key="o.id" :value="o.id">{{ o.label }}</option>
            </select>
            <span v-if="woForm.ar_record_id" class="wo-offset-tip">↳ 核销后自动生成「预收抵扣」回款，冲减应收未收余额（不计现金）</span>
          </div>
          <div class="wo-inputs">
            <input v-model="woForm.amount" type="number" step="0.01" class="inp"
                   :placeholder="Number(woRec.balance_amount) > 0 ? '核销金额(元)，按 = 填全额' : '核销金额(元)'"
                   :class="{ 'inp-bad': woAmountOver }"
                   @keydown="e => { if (e.key === '=') { e.preventDefault(); if (Number(woRec.balance_amount) > 0) woForm.amount = Number(woRec.balance_amount).toFixed(2) } }" />
            <button v-if="Number(woRec.balance_amount) > 0" type="button" class="wo-fill-chip"
                    title="填入未核销余额" @click="woForm.amount = Number(woRec.balance_amount).toFixed(2)">全额 ¥{{ fmtAmt(woRec.balance_amount) }}</button>
            <input v-model="woForm.writeoff_date" type="date" class="inp" />
            <input v-model="woForm.notes" class="inp" placeholder="备注" />
            <button class="btn btn-primary btn-sm" :disabled="woSaving || woAmountOver" @click="addWriteoff">{{ woSaving ? '…' : '新增核销' }}</button>
          </div>
          <div v-if="woAmountOver" class="wo-over-tip">核销金额不能超过未核销余额 ¥{{ fmtAmt(woRec.balance_amount) }}</div>
        </div>
        <div class="modal-foot">
          <button class="btn btn-ghost" @click="showWoModal = false">关闭</button>
        </div>

        <!-- 核销迁移：选择目标记录 -->
        <div v-if="migrateWo" class="inst-add-mask" @click.self="migrateWo = null">
          <div class="inst-add-card tr-card">
            <h4>迁移核销<span class="ia-sub">第{{ migrateWo.writeoff_no }}笔 · {{ fmtAmt(migrateWo.amount) }}</span></h4>
            <div class="ia-fld">
              <span>迁移到（同方向、余额须足以承接）</span>
              <input v-model="migrateKw" class="inp" placeholder="搜索往来单位 / 项目…" @input="onMigrateKw" />
              <div v-if="migrateOpts.length" class="tr-opts">
                <div v-for="r in migrateOpts" :key="r.id" class="tr-opt" @click="doMigrate(r)">
                  <b>{{ r.counterparty || '—' }}</b><span v-if="r.short_name">·{{ r.short_name }}</span>
                  <i>{{ r.delivery_dept }}</i><em>余额 {{ fmtAmt(r.balance_amount) }}</em>
                </div>
              </div>
            </div>
            <p class="ia-hint">仅纯登记核销可迁移；已关联预收抵扣回款/排款的须先撤销关联</p>
            <div class="ia-foot">
              <button class="btn btn-ghost btn-sm" @click="migrateWo = null">取消</button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ── installment modal（收付明细：一条记录多次到账/付出）── -->
    <div v-if="showInstModal" class="modal-mask" @click.self="showInstModal = false">
      <div class="modal inst-modal">
        <div class="inst-head">
          <h3>收付明细 · {{ instRec.counterparty }}</h3>
          <div class="inst-head-btns">
            <button v-if="instSel.size" class="btn btn-primary btn-sm" @click="migrateSelected">⇄ 迁移选中（{{ instSel.size }} 笔）</button>
            <button v-if="canCreate || canTransferAction" class="btn btn-ghost btn-sm"
                    title="往来单位间/项目间权益转移（非现金，不产生收付流水）" @click="openTransfer">⇄ 转移</button>
            <button v-if="canCreate || canInstAction" class="btn btn-primary btn-sm" @click="openInstAdd">＋ 新增{{ dirLabel }}</button>
          </div>
        </div>
        <div class="wo-summary">
          <span>{{ dirLabel }}总额 <b>{{ fmtAmt(instRec.advance_amount) }}</b><i style="font-style:normal;font-size:11px;color:var(--muted)">（=明细之和）</i></span>
          <span>已核销 <b>{{ fmtAmt(instRec.written_off_amount) }}</b></span>
          <span class="hl">未核销余额 <b>{{ fmtAmt(instRec.balance_amount) }}</b></span>
          <span v-if="parseFloat(instRec.transferred_in_amount)" class="tr-chip tr-chip-in">转入 {{ fmtAmt(instRec.transferred_in_amount) }}</span>
          <span v-if="parseFloat(instRec.transferred_out_amount)" class="tr-chip tr-chip-out">转出 {{ fmtAmt(instRec.transferred_out_amount) }}</span>
        </div>
        <div ref="instListBody" class="inst-scroll">
          <table class="data-table compact">
            <thead><tr>
              <th v-if="canCreate || canTransferAction" class="sel-th"><input type="checkbox" title="全选（批量迁移）"
                  :checked="instList.length > 0 && instSel.size === instList.length" @change="toggleInstSelAll" /></th>
              <th>#</th><th class="amt">收付金额</th><th>收付日期</th><th>备注</th><th v-if="canCreate || canInstAction"></th></tr></thead>
            <tbody>
              <tr v-if="!instList.length"><td :colspan="(canCreate || canInstAction) ? 6 : 5" class="empty">暂无收付明细——点右上角「＋ 新增{{ dirLabel }}」登记第一笔</td></tr>
              <tr v-for="i in instList" :key="i.id" :class="{ 'row-flash': i.id === lastInstId, 'row-sel': instSel.has(i.id) }">
                <td v-if="canCreate || canTransferAction" class="sel-th"><input type="checkbox" :checked="instSel.has(i.id)" @change="toggleInstSel(i.id)" /></td>
                <td>{{ i.install_no }}</td>
                <td class="amt" :style="{ color: parseFloat(i.amount) < 0 ? 'var(--c-danger)' : 'inherit' }">{{ fmtAmt(i.amount) }}</td>
                <td>{{ i.occur_date }}</td>
                <td>{{ i.notes || '—' }}</td>
                <td v-if="canCreate || canInstAction">
                  <button v-if="canCreate || canTransferAction" class="lnk" title="这笔收付记错对象？整笔迁移到另一条记录（现金流水随行）" @click="openInstMigrate(i)">迁移</button>
                  <button class="lnk danger" :disabled="instBusy" @click="delInstallment(i)">删除</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-if="transferList.tout.length || transferList.tin.length" class="tr-sec">
          <div class="tr-sec-head">转移记录<i>权益重分类，非现金，不计入收付流水</i></div>
          <div v-for="t in transferList.tout" :key="'o' + t.id" class="tr-item">
            <span class="tr-kind" :class="{ cash: t.kind === 'cash_lines' }">{{ t.kind === 'cash_lines' ? '整笔' : '权益' }}</span>
            <b class="tr-amt-out">−{{ fmtAmt(t.amount) }}</b>
            <span>→ {{ t.to.counterparty || '—' }}<template v-if="t.to.short_name">·{{ t.to.short_name }}</template><template v-if="t.to.delivery_dept !== instRec.delivery_dept">（{{ t.to.delivery_dept }}）</template></span>
            <em>{{ t.transfer_date }}</em>
            <span class="tr-reason" :title="t.reason">{{ t.reason }}</span>
            <button v-if="canCreate || canTransferAction" class="lnk danger" @click="undoTransfer(t)">撤销</button>
          </div>
          <div v-for="t in transferList.tin" :key="'i' + t.id" class="tr-item">
            <span class="tr-kind" :class="{ cash: t.kind === 'cash_lines' }">{{ t.kind === 'cash_lines' ? '整笔' : '权益' }}</span>
            <b class="tr-amt-in">+{{ fmtAmt(t.amount) }}</b>
            <span>← {{ t.from.counterparty || '—' }}<template v-if="t.from.short_name">·{{ t.from.short_name }}</template><template v-if="t.from.delivery_dept !== instRec.delivery_dept">（{{ t.from.delivery_dept }}）</template></span>
            <em>{{ t.transfer_date }}</em>
            <span class="tr-reason" :title="t.reason">{{ t.reason }}</span>
            <button v-if="canCreate || canTransferAction" class="lnk danger" @click="undoTransfer(t)">撤销</button>
          </div>
        </div>
        <p class="inst-note">
          与应收的多次回款同构：同一笔{{ dirLabel }}业务可分多次到账/付出，总额与未核销余额自动派生；删除某笔会回退总额（低于已核销时拒绝，须先删核销）。
        </p>
        <div class="modal-foot">
          <button class="btn btn-ghost" @click="showInstModal = false">关闭</button>
        </div>

        <!-- 转移卡片：固定居中浮层，Esc 关闭 -->
        <div v-if="showTransfer" class="inst-add-mask" @click.self="() => { if (!transferForm.amount && !transferForm.reason) showTransfer = false }">
          <div class="inst-add-card tr-card">
            <h4 v-if="migInsts.length === 1">⇄ 整笔迁移<span class="ia-sub">第{{ migInsts[0].install_no }}笔 {{ fmtAmt(migInsts[0].amount) }} · {{ migInsts[0].occur_date }}</span></h4>
            <h4 v-else-if="migInsts.length">⇄ 批量迁移<span class="ia-sub">{{ migInsts.length }} 笔 · 合计 {{ fmtAmt(migAmt) }}</span></h4>
            <h4 v-else>⇄ 转移{{ dirLabel }}<span class="ia-sub">{{ instRec.counterparty }} · 余额 {{ fmtAmt(instRec.balance_amount) }}</span></h4>
            <div v-if="migInsts.length" class="mig-info">收付日期与金额整笔随迁，现金口径同步更正（区别于按金额的权益划转）</div>
            <label v-if="!migInsts.length" class="ia-fld">
              <span>转移金额 <em>*</em>
                <button type="button" class="wo-fill-chip" style="margin-left:6px"
                        @click="transferForm.amount = Number(instRec.balance_amount).toFixed(2)">全额 ¥{{ fmtAmt(instRec.balance_amount) }}</button>
              </span>
              <input ref="transferAmtInput" v-model="transferForm.amount" type="number" step="0.01" class="inp" placeholder="≤ 未核销余额" />
            </label>
            <div v-if="migInsts.length" class="ia-fld">
              <span>核销随迁</span>
              <div class="tr-mode">
                <label :class="{ active: migCarry === 'auto' }"><input v-model="migCarry" type="radio" value="auto" />自动同步（推荐）</label>
                <label :class="{ active: migCarry === 'none' }"><input v-model="migCarry" type="radio" value="none" />仅迁收付</label>
              </div>
              <div class="mig-preview" :class="{ bad: migSrcAfter < 0 }">
                <template v-if="migCarry === 'auto'">自动随迁核销 {{ fmtAmt(migCarryAmt) }} · </template>迁移后源余额：{{ fmtAmt(migSrcAfter) }}<template v-if="migSrcAfter < 0">（为负：可自动随迁的纯登记核销不足，请先撤销对应关联核销）</template>
              </div>
            </div>
            <label class="ia-fld">
              <span>转移日期 <em>*</em></span>
              <input v-model="transferForm.date" type="date" class="inp" />
            </label>
            <label class="ia-fld">
              <span>转移原因 <em>*</em></span>
              <input v-model="transferForm.reason" class="inp" maxlength="200" placeholder="如：合同主体变更 / 预收落位到项目" />
            </label>
            <div class="ia-fld">
              <span>转移到 <em>*</em></span>
              <div class="tr-mode">
                <label :class="{ active: transferForm.mode === 'existing' }"><input v-model="transferForm.mode" type="radio" value="existing" />已有记录</label>
                <label :class="{ active: transferForm.mode === 'new' }"><input v-model="transferForm.mode" type="radio" value="new" />新建记录</label>
              </div>
              <template v-if="transferForm.mode === 'existing'">
                <div v-if="transferForm.target_label" class="tr-picked">{{ transferForm.target_label }}
                  <button type="button" class="lnk" @click="transferForm.to_advance_id = ''; transferForm.target_label = ''; searchTargets('')">重选</button></div>
                <template v-else>
                  <input v-model="transferForm.target_kw" class="inp" placeholder="搜索往来单位 / 项目…" @input="onTargetKw" />
                  <div v-if="targetOpts.length" class="tr-opts">
                    <div v-for="r in targetOpts" :key="r.id" class="tr-opt" @click="pickTarget(r)">
                      <b>{{ r.counterparty || '—' }}</b><span v-if="r.short_name">·{{ r.short_name }}</span>
                      <i>{{ r.delivery_dept }}</i><em>余额 {{ fmtAmt(r.balance_amount) }}</em>
                    </div>
                  </div>
                </template>
              </template>
              <template v-else>
                <input v-model="transferForm.new_counterparty" class="inp" style="margin-bottom:6px" placeholder="目标往来单位（必填）" />
                <input v-model="transferForm.new_project_kw" class="inp" placeholder="关联项目（选填，搜索项目简称）" @input="onTargetProjKw" />
                <div v-if="targetProjOpts.length && !transferForm.new_project_id" class="tr-opts">
                  <div v-for="pr in targetProjOpts" :key="pr.id" class="tr-opt" @click="pickTargetProject(pr)">
                    <b>{{ pr.short_name }}</b><i>{{ pr.delivery_dept }}</i><span>{{ pr.customer_name }}</span>
                  </div>
                </div>
              </template>
            </div>
            <p class="ia-hint">{{ migInsts.length ? '整笔迁移：收付流水物理移动到目标，已核销部分同步平移（自动拆行），账龄按收付日承袭；可整单撤销' : '转移是权益重分类：不产生现金流水，账龄承袭原记录' }}；跨事业部仅超级管理员</p>
            <div class="ia-foot">
              <button class="btn btn-ghost btn-sm" @click="showTransfer = false">取消</button>
              <button class="btn btn-primary btn-sm" :disabled="transferBusy" @click="submitTransfer">{{ transferBusy ? '…' : (migInsts.length ? '确认迁移' : '确认转移') }}</button>
            </div>
          </div>
        </div>

        <!-- 新增收付卡片：固定居中浮层，Esc 关卡片、Enter 保存 -->
        <div v-if="showInstAdd" class="inst-add-mask" @click.self="instAddMaskClick">
          <div class="inst-add-card" @keydown.enter.prevent="saveInstAdd(false)">
            <h4>新增{{ dirLabel }}<span class="ia-sub">{{ instRec.counterparty }} · 第 {{ instList.length + 1 }} 笔</span></h4>
            <label class="ia-fld">
              <span>收付金额 <em>*</em></span>
              <input ref="instAmtInput" v-model="instForm.amount" type="number" step="0.01" class="inp" placeholder="元，负数=退回" />
            </label>
            <label class="ia-fld">
              <span>收付日期 <em>*</em></span>
              <input v-model="instForm.occur_date" type="date" class="inp" />
            </label>
            <label class="ia-fld">
              <span>备注</span>
              <input v-model="instForm.notes" class="inp" placeholder="如：第二笔预付款" />
            </label>
            <p class="ia-hint">Enter 保存 · Esc 取消 · 总额与未核销余额自动派生</p>
            <div class="ia-foot">
              <button class="btn btn-ghost btn-sm" @click="showInstAdd = false">取消</button>
              <button class="btn btn-ghost btn-sm" :disabled="instBusy" @click="saveInstAdd(true)">保存并继续</button>
              <button class="btn btn-primary btn-sm" :disabled="instBusy" @click="saveInstAdd(false)">{{ instBusy ? '…' : '保存' }}</button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ── create / edit supplier modal ── -->
    <div v-if="showSupplierModal" class="modal-mask" @click.self="showSupplierModal = false">
      <div class="modal sup-modal">
        <h3>{{ editSupplier ? '编辑' : '新增' }}供应商</h3>

        <!-- 名称 -->
        <div class="sf-row">
          <label class="sf-fld">
            <span class="sf-lbl">供应商名称 <em>*</em></span>
            <input v-model="supplierForm.name" class="inp" placeholder="应与预付往来单位名称完全一致" />
            <span class="sf-hint">系统按此名称精确匹配预付余额，请确保与账单一致</span>
          </label>
        </div>

        <!-- 类型 -->
        <div class="sf-row">
          <span class="sf-lbl">类型 <em>*</em></span>
          <div class="sup-type-row">
            <label class="sup-type-btn" :class="{ active: supplierForm.supplier_type === 'public' }">
              <input type="radio" v-model="supplierForm.supplier_type" value="public" />
              公共供应商
              <span class="sup-type-desc">归属某事业部</span>
            </label>
            <label class="sup-type-btn" :class="{ active: supplierForm.supplier_type === 'private' }">
              <input type="radio" v-model="supplierForm.supplier_type" value="private" />
              私有供应商
              <span class="sup-type-desc">绑定特定项目</span>
            </label>
          </div>
        </div>

        <!-- 归属（私有选项目，公共选事业部）+ 联系人 两列 -->
        <div class="sf-row sf-two">
          <label v-if="supplierForm.supplier_type === 'private'" class="sf-fld">
            <span class="sf-lbl">关联项目 <em>*</em></span>
            <div class="combo">
              <input v-model="supplierProjKeyword" class="inp" placeholder="搜索项目简称 / 编号…"
                     @focus="showSupplierProjList = true"
                     @input="onSupplierProjKeywordInput" @blur="onSupplierProjBlur" />
              <button v-if="supplierForm.project_id || supplierProjKeyword" type="button" class="combo-clear"
                      @mousedown.prevent="pickSupplierProject(null)">×</button>
              <ul v-if="showSupplierProjList" class="combo-list">
                <li v-for="p in supplierProjects" :key="p.id" class="combo-opt"
                    :class="{ on: supplierForm.project_id === p.id }"
                    @mousedown.prevent="pickSupplierProject(p)">
                  <span>{{ p.short_name }}</span><span class="combo-dept">{{ p.delivery_dept }}</span>
                </li>
                <li v-if="!supplierProjects.length" class="combo-opt muted">无匹配项目</li>
              </ul>
            </div>
          </label>
          <label v-else class="sf-fld">
            <span class="sf-lbl">归属事业部 <em>*</em></span>
            <select v-model="supplierForm.delivery_dept" class="sel">
              <option v-for="d in accessibleDepts" :key="d" :value="d">{{ d }}</option>
            </select>
          </label>
          <label class="sf-fld">
            <span class="sf-lbl">联系人</span>
            <input v-model="supplierForm.contact" class="inp" placeholder="选填" />
          </label>
        </div>

        <!-- 备注 -->
        <div class="sf-row">
          <label class="sf-fld">
            <span class="sf-lbl">备注</span>
            <input v-model="supplierForm.notes" class="inp" placeholder="选填" />
          </label>
        </div>

        <div class="modal-foot">
          <button class="btn btn-ghost" @click="showSupplierModal = false">取消</button>
          <button class="btn btn-primary" :disabled="supplierSaving" @click="saveSupplier">
            {{ supplierSaving ? '保存中…' : '保存' }}
          </button>
        </div>
      </div>
    </div>
  </div>

  <!-- 导入预检弹窗 -->
  <ImportPrecheckModal :report="precheckResult" :busy="precheckBusy" :readonly="true"
    @close="precheckResult = null" @apply="onPrecheckApply" />

  <!-- 右键上下文菜单（预收/预付记录 + 供应商） -->
  <ContextMenu :ctx="ctxRec" :items="ctxRecItems" />
  <ContextMenu :ctx="ctxSup" :items="ctxSupItems" />
</template>

<style scoped>
.topbar { display: flex; justify-content: space-between; margin-bottom: 10px; }
.dir-tabs { display: flex; gap: 8px; margin-bottom: 10px; align-items: center; }
.dir-tab-sep { width: 1px; height: 24px; background: var(--border); margin: 0 4px; }
.dir-tab {
  padding: 7px 16px; border-radius: 8px; border: 1px solid var(--border);
  background: var(--card); color: var(--muted); font-weight: 600; cursor: pointer; font-size: 13.5px;
}
.dir-tab.active { background: var(--primary); color: #fff; border-color: var(--primary); }

.kpi-row { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 10px; }
.kpi { flex: 1; min-width: 108px; background: var(--card); border: 1px solid var(--border); border-radius: 9px; padding: 8px 11px; }
.kpi-k { font-size: 11px; color: var(--muted); }
.kpi-v { font-size: 20px; font-weight: 800; color: var(--text); margin-top: 2px; line-height: 1.2; }
.kpi-sub { font-size: 11px; font-weight: 600; color: var(--muted); margin-left: 5px; }
.kpi-range { font-size: 10.5px; font-weight: 400; color: var(--muted); margin-left: 6px; opacity: .8; }

/* 实际收付时间区间条（款项日期）*/
.adv-timebar { display: flex; align-items: center; gap: 10px; padding: 6px 0 10px; flex-wrap: nowrap; min-width: 0; }
.tb-lbl { font-size: 12px; font-weight: 700; color: var(--muted); white-space: nowrap; flex-shrink: 0; }
.tb-presets { display: flex; gap: 5px; overflow-x: auto; scrollbar-width: none; min-width: 0; }
.tb-presets::-webkit-scrollbar { display: none; }
.pchip { padding: 3px 11px; border-radius: 999px; border: 1px solid var(--border); background: var(--card);
  color: var(--text); font-size: 12px; cursor: pointer; white-space: nowrap; transition: all .15s; flex-shrink: 0; }
.pchip:hover { border-color: var(--primary); color: var(--primary); }
.pchip.on { background: var(--primary); border-color: var(--primary); color: #fff; font-weight: 600; }
.tb-range { display: flex; align-items: center; gap: 6px; flex-shrink: 0; margin-left: auto; }
.tb-date { width: 132px; }
.tb-sep { color: var(--muted); font-size: 12px; }

/* 筛选合计栏（与当前筛选同口径）*/
.adv-sumbar { display: flex; align-items: center; gap: 16px; flex-wrap: wrap;
  padding: 8px 12px; margin-top: 8px; border-radius: 9px; font-size: 12.5px;
  background: var(--card); border: 1px solid var(--border); color: var(--text-2, var(--muted)); }
.sb-k { font-weight: 700; color: var(--muted); }
.sb-i b { font-variant-numeric: tabular-nums; color: var(--text); margin-left: 3px; }
.sb-accent { color: var(--primary) !important; }
.sb-warn { color: var(--c-danger) !important; }
.sb-range { margin-left: auto; font-size: 11px; color: var(--muted); opacity: .8; }
.sel-col { width: 34px; text-align: center; }
.sel-col input { cursor: pointer; accent-color: var(--primary); }
.row-sel { background: rgba(201,99,66,.07) !important; }
.sumbar-sel { border-color: var(--primary); background: rgba(201,99,66,.05); }
/* 危险按钮统一走全局 .btn-danger（style.css），页内不再复制 */
.kpi.accent { background: rgba(201,99,66,.06); }
.kpi.accent .kpi-v { color: var(--primary); }
.kpi.warn .kpi-v { color: var(--c-danger); }

.filter-row { display: flex; gap: 7px; flex-wrap: wrap; align-items: center; margin-bottom: 12px; }
.spacer { flex: 1; min-width: 8px; }
.proj-chip { padding: 5px 10px; border: 1px solid var(--primary); border-radius: 999px; background: rgba(var(--primary-rgb,255,138,76),0.1); color: var(--primary); font-size: 12px; cursor: pointer; white-space: nowrap; }
.proj-chip:hover { background: rgba(var(--primary-rgb,255,138,76),0.18); }
.sel, .inp { padding: 6px 9px; border: 1px solid var(--border); border-radius: 7px; background: var(--card); color: var(--text); font-size: 13px; }
.filter-row .sel, .filter-row .inp { width: auto; font-size: 12.5px; }
/* 视图切换：明细 / 按单位聚合 */
.view-seg { display: inline-flex; gap: 2px; background: var(--surface-2, rgba(160,120,80,.08)); border-radius: 8px; padding: 3px; flex-shrink: 0; }
.vs-btn { border: none; background: none; padding: 4px 12px; border-radius: 6px; font-size: 12.5px; font-weight: 600;
  color: var(--muted); cursor: pointer; font-family: inherit; white-space: nowrap; transition: all .15s; }
.vs-btn.on { background: var(--card); color: var(--primary); box-shadow: var(--shadow-sm); }
/* 按单位聚合表 */
.cp-agg-table .cp-row { cursor: pointer; }
.cp-agg-table .cp-row:hover td { background: rgba(201,99,66,.05); }
.cp-name { font-weight: 650; }
.cp-caret { display: inline-block; width: 16px; color: var(--muted); }
.cp-proj-row td { background: rgba(160,120,80,.04); font-size: 12.5px; }
.cp-proj-name { padding-left: 26px; color: var(--muted); }
.loose-tag { margin-left: 4px; font-size: 10.5px; color: var(--c-warn); background: var(--c-warn-bg, rgba(245,166,35,.12)); border-radius: 4px; padding: 0 5px; }
.txt-warn { color: var(--c-warn); }
.sel.sm { padding: 5px 8px; font-size: 12.5px; }
.inp.sm { padding: 5px 9px; font-size: 12.5px; width: 240px; max-width: 100%; }
.btn.disabled { opacity: .6; pointer-events: none; }

.table-scroll { overflow-x: auto; }
/* fixed-viewport: scroll wrappers fill the card; sticky header stays put */
.table-scroll.page-scroll { overflow: auto; }
.table-scroll.page-scroll thead th,
.table-wrap.page-scroll thead th { position: sticky; top: 0; z-index: 5; background: var(--thead-bg); }
.pager { flex-shrink: 0; }
.data-table { width: 100%; border-collapse: collapse; font-size: 13px; min-width: 760px; }
.data-table.compact { min-width: 0; }
.data-table th, .data-table td { padding: 9px 10px; text-align: left; border-bottom: 1px solid var(--border); white-space: nowrap; }
.data-table thead th { color: var(--muted); font-weight: 700; font-size: 12px; background: rgba(180,140,110,.06); }
/* 列头漏斗按钮 / 弹层定位锚点不被单元格裁切 */
.data-table thead th { overflow: visible; }
/* 项目简称 + 部门 两个列头筛选并排 */
.global-search { width: 360px; min-width: 160px; flex: 1 1 300px; max-width: 100%; flex: 0 1 360px; }
.filter-hint { font-size: 11.5px; color: var(--muted); white-space: nowrap; }
.data-table th.amt, .data-table td.amt { text-align: right; }
.data-table th.ctr, .data-table td.ctr { text-align: center; }
.num-strong { font-weight: 700; }
.bal-positive { color: var(--primary); }
.proj-name { font-weight: 600; }
.dept-tag { font-size: 11px; color: var(--muted); }
.empty { text-align: center; color: var(--muted); padding: 28px 0; }
.nowrap { white-space: nowrap; }

/* 状态徽章基准与语义色变体统一走全局 style.css 的 .status-pill/.pill-*（勿在页内复制） */

.lnk { background: none; border: none; color: var(--primary); cursor: pointer; font-size: 13px; padding: 2px 6px; }
.lnk.danger { color: var(--c-danger); }

.pager { display: flex; align-items: center; justify-content: center; gap: 12px; margin-top: 14px; font-size: 13px; color: var(--muted); flex-wrap: wrap; }
.pg-jump{display:inline-flex;align-items:center;gap:4px;font-size:13px;color:var(--muted);margin-left:8px}
.pg-jump-input{width:46px;text-align:center;padding:2px 4px;border:1px solid var(--border);border-radius:6px;font-size:13px}
@media (max-width: 640px) {
  .kpi-row { flex-wrap: wrap !important; }
  .kpi { min-width: calc(50% - 6px) !important; flex: 1 1 calc(50% - 6px) !important; }
}

.modal-mask { position: fixed; inset: 0; background: rgba(20,10,5,0.42); backdrop-filter: blur(8px); display: flex; align-items: center; justify-content: center; z-index: 200; padding: 20px; }
.modal {
  background: rgba(255,252,248,0.97);
  border: 1px solid var(--glass-border);
  border-radius: 18px; padding: 22px 24px; width: 100%; max-width: 640px; max-height: 90vh; overflow-y: auto;
  box-shadow: 0 24px 80px rgba(100,60,30,0.28), 0 1px 0 rgba(255,255,255,0.8) inset;
}
.modal h3 { margin: 0 0 16px; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
@media (max-width: 620px) { .form-grid { grid-template-columns: 1fr; } }
.fld { display: flex; flex-direction: column; gap: 4px; font-size: 13px; }
.fld.full { grid-column: 1 / -1; }
.fld span { color: var(--muted); }
.fld em { color: var(--c-danger); font-style: normal; }
.modal-foot { display: flex; justify-content: flex-end; gap: 10px; margin-top: 18px; }

/* project combobox */
.combo { position: relative; }
.combo .inp { width: 100%; padding-right: 28px; }
.combo-clear { position: absolute; right: 6px; top: 50%; transform: translateY(-50%);
  border: none; background: none; color: var(--muted); font-size: 18px; line-height: 1; cursor: pointer; padding: 0 4px; }
.combo-list {
  position: absolute; z-index: 10; top: calc(100% + 4px); left: 0; right: 0;
  background: var(--row-bg); border: 1px solid var(--border); border-radius: 9px;
  box-shadow: 0 10px 30px rgba(100,60,30,0.18); max-height: 220px; overflow-y: auto;
  list-style: none; margin: 0; padding: 4px;
}
.combo-opt { display: flex; justify-content: space-between; align-items: center; gap: 8px;
  padding: 7px 9px; border-radius: 6px; cursor: pointer; font-size: 13px; }
.combo-opt:hover { background: rgba(201,99,66,.08); }
.combo-opt.on { background: rgba(201,99,66,.12); font-weight: 600; }
.combo-opt.muted { color: var(--muted); }
.combo-dept { font-size: 11px; color: var(--muted); }

.wo-summary { display: flex; gap: 18px; flex-wrap: wrap; font-size: 13px; color: var(--muted); margin-bottom: 12px; }
.wo-summary b { color: var(--text); }
.wo-summary .hl b { color: var(--primary); }
.wo-add { display: flex; flex-direction: column; gap: 8px; margin-top: 12px; padding-top: 12px; border-top: 1px dashed var(--border); }
.wo-offset-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; background: rgba(201,99,66,0.05); border: 1px solid rgba(201,99,66,0.2); border-radius: 8px; padding: 7px 10px; }
.wo-offset-lbl { font-size: 12px; font-weight: 700; color: var(--primary); white-space: nowrap; }
.wo-offset-sel { flex: 1; min-width: 220px; }
.wo-offset-tip { font-size: 11px; color: var(--primary); opacity: 0.8; width: 100%; padding-left: 2px; }
.wo-inputs { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }

/* ── 收付/核销明细弹窗：固定高度、列表内滚（长列表不再撑开整个弹窗）── */
.inst-modal { display: flex; flex-direction: column; max-height: 80vh; overflow: hidden; position: relative; }
.inst-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 4px; }
.inst-head h3 { margin: 0 0 12px; }
.inst-head .btn { flex-shrink: 0; margin-bottom: 8px; }
.inst-scroll { flex: 1; min-height: 80px; overflow-y: auto; border: 1px solid var(--border); border-radius: 10px; }
.inst-scroll .data-table { margin: 0; }
.inst-scroll thead th { position: sticky; top: 0; background: #f6efe7; z-index: 1; box-shadow: 0 1px 0 var(--border); }
.inst-note { font-size: 11px; color: var(--muted); margin: 8px 0 0; }
.row-flash td { animation: inst-flash 1.6s ease; }
@keyframes inst-flash { 0% { background: rgba(201,99,66,0.20); } 100% { background: transparent; } }

/* 新增收付卡片：固定居中浮层（覆盖整屏，不随列表滚动） */
.inst-add-mask {
  position: fixed; inset: 0; z-index: 320;
  background: rgba(20,10,5,0.28); backdrop-filter: blur(3px);
  display: flex; align-items: center; justify-content: center; padding: 20px;
}
.inst-add-card {
  width: 360px; max-width: 92vw;
  background: rgba(255,252,248,0.99);
  border: 1px solid var(--glass-border); border-radius: 16px;
  padding: 18px 20px 16px;
  box-shadow: 0 18px 60px rgba(100,60,30,0.32), 0 1px 0 rgba(255,255,255,0.85) inset;
  animation: ia-pop .16s ease;
}
@keyframes ia-pop { from { transform: scale(.96) translateY(6px); opacity: 0; } to { transform: none; opacity: 1; } }
.inst-add-card h4 { margin: 0 0 14px; font-size: 15px; display: flex; align-items: baseline; gap: 8px; }
.ia-sub { font-size: 11.5px; font-weight: 500; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ia-fld { display: block; margin-bottom: 10px; }
.ia-fld > span { display: block; font-size: 12px; font-weight: 600; color: var(--muted); margin-bottom: 4px; }
.ia-fld > span em { color: var(--c-danger); font-style: normal; }
.ia-fld .inp { width: 100%; }
.ia-hint { font-size: 11px; color: var(--muted); margin: 2px 0 12px; }
.ia-foot { display: flex; justify-content: flex-end; gap: 8px; }

/* ── 转移 ── */
.inst-head-btns { display: flex; gap: 8px; flex-shrink: 0; margin-bottom: 8px; }
.tr-chip { font-size: 11px; padding: 1px 8px; border-radius: 999px; font-weight: 700; }
.tr-chip-in { background: rgba(27,110,53,0.1); color: #1b6e35; }
.tr-chip-out { background: rgba(198,40,40,0.08); color: #c62828; }
.tr-sec { margin-top: 10px; border: 1px dashed var(--border); border-radius: 10px; padding: 8px 10px; max-height: 150px; overflow-y: auto; }
.tr-sec-head { font-size: 11.5px; font-weight: 700; color: var(--muted); margin-bottom: 5px; }
.tr-sec-head i { font-style: normal; font-weight: 400; font-size: 10.5px; margin-left: 8px; }
.tr-item { display: flex; align-items: center; gap: 8px; font-size: 12px; padding: 3px 0; }
.tr-amt-out { color: #c62828; font-weight: 800; }
.tr-amt-in { color: #1b6e35; font-weight: 800; }
.tr-item em { font-style: normal; font-size: 11px; color: var(--muted); }
.tr-reason { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11px; color: var(--muted); }
.tr-card { width: 420px; }
.tr-mode { display: flex; gap: 8px; margin-bottom: 8px; }
.tr-mode label { display: flex; align-items: center; gap: 5px; font-size: 12px; padding: 4px 12px; border: 1.5px solid var(--border); border-radius: 8px; cursor: pointer; }
.tr-mode label.active { border-color: var(--primary); color: var(--primary); font-weight: 700; background: rgba(201,99,66,0.05); }
.tr-opts { margin-top: 6px; border: 1px solid var(--border); border-radius: 8px; max-height: 170px; overflow-y: auto; }
.tr-opt { display: flex; align-items: center; gap: 6px; padding: 6px 10px; font-size: 12px; cursor: pointer; border-bottom: 1px solid rgba(0,0,0,0.04); }
.tr-opt:hover { background: rgba(201,99,66,0.06); }
.tr-opt b { font-weight: 700; }
.tr-opt i { font-style: normal; font-size: 11px; color: var(--muted); }
.tr-opt em { font-style: normal; font-size: 11px; color: var(--primary); margin-left: auto; white-space: nowrap; }
.tr-picked { font-size: 12.5px; font-weight: 600; padding: 6px 10px; background: rgba(201,99,66,0.06); border: 1px solid rgba(201,99,66,0.25); border-radius: 8px; display: flex; align-items: center; gap: 8px; }
.tr-kind { font-size: 10px; font-weight: 700; padding: 0 6px; border-radius: 6px; background: rgba(120,120,120,0.12); color: var(--muted); flex-shrink: 0; }
.tr-kind.cash { background: rgba(21,101,192,0.12); color: var(--c-info); }
.mig-info { font-size: 11.5px; color: var(--c-info); background: rgba(21,101,192,0.06); border: 1px solid rgba(21,101,192,0.18); border-radius: 8px; padding: 6px 10px; margin-bottom: 10px; }
.mig-wo { display: flex; align-items: center; gap: 7px; font-size: 12px; padding: 3px 0; cursor: pointer; }
.mig-wo em { font-style: normal; font-size: 11px; color: var(--muted); }
.mig-preview { margin-top: 6px; font-size: 12px; font-weight: 700; color: #1b6e35; }
.inst-scroll .sel-th { width: 30px; text-align: center; }
.inst-scroll tr.row-sel td { background: rgba(201,99,66,0.06); }
.mig-preview.bad { color: var(--c-danger); }
.offset-badge { display: inline-block; padding: 1px 7px; border-radius: 999px; background: rgba(27,110,53,0.1); color: #1b6e35; font-size: 11px; font-weight: 600; }
.offset-badge.pay-badge { background: rgba(21,101,192,0.1); color: var(--c-info); }

/* supplier modal */
.sup-modal { max-width: 460px; }
.sf-row { margin-bottom: 14px; }
.sf-two { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
@media (max-width: 620px) { .sf-two { grid-template-columns: 1fr; } }
.sf-fld { display: flex; flex-direction: column; gap: 4px; }
.sf-lbl { font-size: 12px; color: var(--muted); margin-bottom: 2px; }
.sf-lbl em { color: var(--c-danger); font-style: normal; }
.sf-hint { font-size: 11px; color: var(--muted); }
.sup-type-row { display: flex; gap: 10px; margin-top: 6px; }
.sup-type-btn {
  flex: 1; display: flex; flex-direction: column; align-items: center; gap: 3px;
  padding: 10px 8px; border: 1.5px solid var(--border); border-radius: 10px;
  cursor: pointer; font-size: 13px; font-weight: 600; text-align: center;
  transition: border-color 0.15s, background 0.15s;
}
.sup-type-btn input[type=radio] { display: none; }
.sup-type-btn.active { border-color: var(--primary); background: rgba(201,99,66,0.06); color: var(--primary); }
.sup-type-desc { font-size: 11px; font-weight: 400; color: var(--muted); }
.sup-type-btn.active .sup-type-desc { color: var(--primary); opacity: 0.75; }

/* ══ 预收/预付列表备注列：限宽省略，整表保持一页宽 ══ */
.adv-notes-col { width: 130px; }
.adv-notes-cell { max-width: 130px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  color: var(--muted); font-size: 12px; }

/* ══ 收付差异（紧凑排版）══ */
.diff-table { width: 100%; table-layout: fixed; border-collapse: collapse; font-size: 12.5px; }
.diff-table th { padding: 7px 10px; text-align: left; font-size: 11px; font-weight: 700; color: var(--muted);
  background: rgba(201,99,66,.05); border-bottom: 1px solid rgba(180,140,110,.15); white-space: nowrap; }
.diff-table td { padding: 6px 10px; border-bottom: 1px solid rgba(180,140,110,.08); vertical-align: middle; }
.dt-proj { width: 23%; }
.dt-amt { width: 14%; text-align: right !important; font-variant-numeric: tabular-nums; }
.dt-notes { width: 31%; }
.dt-caret { width: 4%; text-align: center; font-size: 10px; color: var(--muted); }
td.dt-proj { overflow: hidden; white-space: nowrap; }
.dt-name { font-weight: 700; color: var(--text); }
.dt-dept { font-size: 10.5px; color: var(--muted); background: rgba(120,120,120,.08);
  border-radius: 5px; padding: 1px 6px; margin-left: 6px; white-space: nowrap; }
td.dt-notes { overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  color: var(--muted); font-size: 11.5px; }
.diff-row { cursor: pointer; }
.diff-row:hover td { background: rgba(201,99,66,.04); }
.diff-row .fw { font-weight: 700; }
.diff-detail-row td { background: rgba(250,246,241,.7); padding: 6px 10px; }
.diff-detail { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
@media (max-width: 760px) { .diff-detail { grid-template-columns: 1fr; } }
.dd-col { background: var(--row-bg); border: 1px solid rgba(180,140,110,.14); border-radius: 8px; padding: 5px 10px; }
.dd-head { font-size: 11px; font-weight: 700; margin-bottom: 2px; }
.dd-head.in { color: var(--c-success); } .dd-head.out { color: #ef6c00; }
.dd-empty { font-size: 11.5px; color: var(--muted); padding: 2px 0; }
.dd-item { display: flex; align-items: center; gap: 8px; font-size: 12px; padding: 2.5px 0;
  border-top: 1px dashed rgba(180,140,110,.12); line-height: 1.5; }
.dd-item:first-of-type { border-top: none; }
.dd-date { color: var(--muted); font-variant-numeric: tabular-nums; min-width: 74px; }
.dd-amt { font-variant-numeric: tabular-nums; min-width: 78px; text-align: right; }
.dd-amt.in { color: var(--c-success); } .dd-amt.out { color: #ef6c00; }
.dd-party { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text); }
.dd-bal { font-style: normal; font-size: 10.5px; color: var(--c-info); background: rgba(21,101,192,.07);
  border-radius: 5px; padding: 0 6px; white-space: nowrap; }

.amt-pos { color: var(--c-success); }
.amt-neg { color: var(--c-danger); }

/* ── 收付差异 · 视角切换条（按项目 / 按月 / 按周） ── */
.diff-viewbar { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; flex-wrap: wrap; }
.diff-view-tabs { display: inline-flex; border: 1px solid var(--border); border-radius: 9px; overflow: hidden; }
.diff-view-tabs button { padding: 6px 16px; border: none; background: transparent; cursor: pointer;
  color: var(--muted); font-size: 12.5px; font-weight: 600; border-right: 1px solid var(--border); }
.diff-view-tabs button:last-child { border-right: none; }
.diff-view-tabs button.act { background: var(--primary); color: #fff; }
.tl-hint { font-size: 11px; color: var(--muted); }
.tl-stat { font-size: 12px; color: var(--text); font-weight: 600; }
.tl-stat b { font-weight: 800; }
.wo-fill-chip { border: 1px solid rgba(46,158,91,.4); background: rgba(46,158,91,.08); color: #1b5e20;
  font-size: 12px; font-weight: 600; padding: 3px 10px; border-radius: 14px; cursor: pointer; white-space: nowrap; transition: all .12s; }
.wo-fill-chip:hover { background: rgba(46,158,91,.16); }
.inp.inp-bad { border-color: var(--c-danger); }
.wo-over-tip { font-size: 12px; color: var(--c-danger); margin-top: 6px; }
</style>
