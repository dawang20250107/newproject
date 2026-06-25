<script setup>
import { ref, reactive, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { useAuthStore } from '../../stores/auth.js'
import { DEPARTMENTS, yearCST, monthCST } from '../../constants.js'
import ar from '../../api/ar.js'
import { fmtCompact } from '../../utils/format.js'
import { topLabel, rightLabel, HIDE_OVERLAP } from '../../utils/chartTheme.js'
import { downloadBlob } from '../../utils/download.js'
import EmptyState from '../../components/EmptyState.vue'
import BaseChart from '../../components/ar/BaseChart.vue'
import ProjectPnlCard from '../caiwu/ProjectPnlCard.vue'
import ImportPrecheckModal from '../../components/ImportPrecheckModal.vue'
import ColumnFilter from '../../components/ColumnFilter.vue'
import { useToast } from '../../composables/useToast.js'
import ContextMenu from '../../components/ContextMenu.vue'
import { useContextMenu } from '../../composables/useContextMenu.js'
import { copyText, copyRowTSV } from '../../utils/clipboard.js'
const toast = useToast()

const auth = useAuthStore()
const activeTab = ref('summary')
const selectedDept = ref('')

// 日期区间筛选，默认本月
function _monthStart(y, m) {
  return `${y}-${String(m).padStart(2, '0')}-01`
}
function _monthEnd(y, m) {
  const last = new Date(y, m, 0).getDate()
  return `${y}-${String(m).padStart(2, '0')}-${String(last).padStart(2, '0')}`
}
const dateStart = ref(_monthStart(yearCST(), monthCST()))
const dateEnd = ref(_monthEnd(yearCST(), monthCST()))

const accessibleDepts = computed(() => auth.effectiveDepts.filter(d => DEPARTMENTS.includes(d)))

const summary = ref(null)
const collItems = ref([])
const payItems = ref([])
const collTotal = ref(0)
const payTotal = ref(0)
const summLoading = ref(false)
const listLoading = ref(false)

const showModal = ref(false)
const modalType = ref('collection')
const editItem = ref(null)
const saving = ref(false)
const form = reactive({ project_no: '', short_name: '', expected_date: '', sub_dept: '', delivery_dept: '', amount: '', notes: '' })
const projects = ref([])
const shortNameOptions = computed(() => {
  const seen = new Set()
  return projects.value
    .filter(p => p.short_name)
    .filter(p => {
      if (seen.has(p.short_name)) return false
      seen.add(p.short_name)
      return true
    })
})

// 选项目简称时实时带出项目编号/交付部门/二级部门
watch(() => form.short_name, name => {
  const matched = projects.value.find(p => p.short_name === name)
  if (matched) {
    form.project_no = matched.project_no || form.project_no
    form.delivery_dept = matched.delivery_dept || form.delivery_dept
    form.sub_dept = matched.sub_dept || form.sub_dept
  }
})

// ── Computed ──────────────────────────────────────────────────────────────────

// 从 dateStart 派生参考年月（用于时间进度条和标题）
const refYear = computed(() => dateStart.value ? parseInt(dateStart.value.slice(0, 4)) : yearCST())
const refMonth = computed(() => dateStart.value ? parseInt(dateStart.value.slice(5, 7)) : monthCST())

const monthProgress = computed(() => {
  const y = refYear.value, m = refMonth.value
  const daysInMonth = new Date(y, m, 0).getDate()
  const today = new Date()
  const isCurrentMonth = today.getFullYear() === y && today.getMonth() + 1 === m
  const isPast = new Date(y, m - 1) < new Date(today.getFullYear(), today.getMonth())
  const daysPassed = isCurrentMonth ? today.getDate() : (isPast ? daysInMonth : 0)
  return { daysPassed, daysInMonth, pct: Math.round(daysPassed / daysInMonth * 100), isCurrentMonth, isPast }
})

// 期间标签：同年月显示"YYYY年M月"，跨月显示区间
const periodLabel = computed(() => {
  if (!dateStart.value || !dateEnd.value) return '—'
  const s = new Date(dateStart.value + 'T00:00:00')
  const e = new Date(dateEnd.value + 'T00:00:00')
  if (s.getFullYear() === e.getFullYear() && s.getMonth() === e.getMonth())
    return `${s.getFullYear()}年${s.getMonth() + 1}月`
  return `${dateStart.value} ~ ${dateEnd.value}`
})

const collAchievement = computed(() => {
  if (!summary.value) return { pct: 0, over: false }
  const b = parseFloat(summary.value.budget_collection) || 0
  if (!b) return { pct: 0, over: false }
  const pct = parseFloat(summary.value.actual_collection) / b * 100
  return { pct: Math.min(pct, 100), rawPct: pct.toFixed(1), over: pct > 100 }
})

const payAchievement = computed(() => {
  if (!summary.value) return { pct: 0, over: false }
  const b = parseFloat(summary.value.budget_payment) || 0
  if (!b) return { pct: 0, over: false }
  const pct = parseFloat(summary.value.actual_payment) / b * 100
  return { pct: Math.min(pct, 100), rawPct: pct.toFixed(1), over: pct > 100 }
})

// 净现金流采用后端统一口径（剔除非现金回款 + 扣预付冲抵 + 含预收/预付），与驾驶舱「现金流分析」一致。
const netCashflow = computed(() => parseFloat(summary.value?.net_cashflow ?? 0) || 0)
const cashInflow = computed(() => parseFloat(summary.value?.cash_inflow ?? 0) || 0)
const cashOutflow = computed(() => parseFloat(summary.value?.cash_outflow ?? 0) || 0)

const comparisonChartOption = computed(() => {
  if (!summary.value) return null
  const bc = parseFloat(summary.value.budget_collection) || 0
  const ac = parseFloat(summary.value.actual_collection) || 0
  const bp = parseFloat(summary.value.budget_payment) || 0
  const ap = parseFloat(summary.value.actual_payment) || 0
  return {
    tooltip: {
      trigger: 'axis', axisPointer: { type: 'shadow' },
      backgroundColor: 'rgba(255,255,255,0.97)', borderColor: 'rgba(0,0,0,0.08)', textStyle: { fontSize: 12 },
      formatter(params) {
        let html = `<div style="font-weight:700;margin-bottom:5px">${params[0].axisValueLabel}</div>`
        params.forEach(p => {
          html += `<div style="display:flex;gap:8px"><span style="color:${p.color}">●</span><span style="flex:1">${p.seriesName}</span><b>${fmtAmt(p.value)}</b></div>`
        })
        return html
      }
    },
    legend: { bottom: 0, icon: 'roundRect', itemWidth: 14, itemHeight: 8, textStyle: { fontSize: 11 }, data: ['预算', '实际'] },
    grid: { top: 16, right: 60, bottom: 40, left: 16, containLabel: true },
    xAxis: { type: 'value', axisLabel: { formatter: v => fmtAmt(v), fontSize: 11, color: '#888' },
             splitLine: { lineStyle: { color: 'rgba(0,0,0,0.06)' } } },
    yAxis: { type: 'category', data: ['付款', '收款'], axisLabel: { fontSize: 12, color: '#555' } },
    series: [
      {
        name: '预算', type: 'bar', barMaxWidth: 26,
        data: [bp, bc],
        itemStyle: { color: 'rgba(155,128,112,0.18)', borderRadius: [0, 4, 4, 0],
          borderColor: 'rgba(155,128,112,0.45)', borderWidth: 1.5 },
        label: rightLabel(p => fmtAmt(p.value)), labelLayout: HIDE_OVERLAP,
      },
      {
        name: '实际', type: 'bar', barMaxWidth: 26,
        data: [
          { value: ap, itemStyle: { borderRadius: [0, 4, 4, 0],
            color: ap > ac ? { type: 'linear', x: 0, y: 0, x2: 1, y2: 0, colorStops: [{ offset: 0, color: '#c62828' }, { offset: 1, color: '#ef5350' }] }
                            : { type: 'linear', x: 0, y: 0, x2: 1, y2: 0, colorStops: [{ offset: 0, color: '#e65100' }, { offset: 1, color: '#ffa726' }] } } },
          { value: ac, itemStyle: { borderRadius: [0, 4, 4, 0],
            color: { type: 'linear', x: 0, y: 0, x2: 1, y2: 0, colorStops: [{ offset: 0, color: '#2e7d32' }, { offset: 1, color: '#66bb6a' }] } } },
        ],
        label: rightLabel(p => fmtAmt(p.value)), labelLayout: HIDE_OVERLAP,
      },
    ],
  }
})

const deptCompareOption = computed(() => {
  const byDept = summary.value?.by_dept
  if (!byDept || byDept.length <= 1) return null
  const deptNames = byDept.map(d => d.dept)
  const SL = { color: 'rgba(0,0,0,0.06)' }
  function grad(c1, c2, horiz = false) {
    return { type: 'linear', x: 0, y: 0, x2: horiz ? 1 : 0, y2: horiz ? 0 : 1,
      colorStops: [{ offset: 0, color: c1 }, { offset: 1, color: c2 }] }
  }
  return {
    tooltip: {
      trigger: 'axis', axisPointer: { type: 'shadow' },
      backgroundColor: 'rgba(255,255,255,0.97)', borderColor: 'rgba(0,0,0,0.08)', textStyle: { fontSize: 12 },
    },
    legend: { bottom: 4, icon: 'roundRect', itemWidth: 14, itemHeight: 8,
              textStyle: { fontSize: 11, color: '#555' },
              data: ['实收', '实付', '收款预算', '付款预算'] },
    grid: { top: 14, right: 14, bottom: deptNames.length > 5 ? 64 : 48, left: 14, containLabel: true },
    xAxis: { type: 'category', data: deptNames,
             axisLine: { show: false }, axisTick: { show: false },
             axisLabel: { fontSize: 11, color: '#888', interval: 0, rotate: deptNames.length > 5 ? 22 : 0 } },
    yAxis: { type: 'value', axisLabel: { formatter: v => fmtAmt(v), fontSize: 11, color: '#888' },
             splitLine: { lineStyle: SL } },
    series: [
      { name: '实收', type: 'bar', barGap: '12%', barMaxWidth: 26,
        data: byDept.map(d => d.actual_collection),
        itemStyle: { color: grad('#66bb6a', '#2e7d32'), borderRadius: [4, 4, 0, 0] },
        label: topLabel(p => fmtAmt(p.value)), labelLayout: HIDE_OVERLAP },
      { name: '实付', type: 'bar', barMaxWidth: 26,
        data: byDept.map(d => ({ value: d.actual_payment,
          itemStyle: { borderRadius: [4, 4, 0, 0],
            color: d.actual_payment > d.actual_collection ? grad('#ef5350', '#c62828') : grad('#ffa726', '#e65100') } })),
        label: topLabel(p => fmtAmt(p.value)), labelLayout: HIDE_OVERLAP },
      { name: '收款预算', type: 'bar', barGap: '40%', barMaxWidth: 14,
        data: byDept.map(d => d.budget_collection),
        itemStyle: { color: 'rgba(46,125,50,0.22)', borderColor: '#2e7d32', borderWidth: 1.5, borderRadius: [4, 4, 0, 0] } },
      { name: '付款预算', type: 'bar', barMaxWidth: 14,
        data: byDept.map(d => d.budget_payment),
        itemStyle: { color: 'rgba(230,81,0,0.22)', borderColor: '#e65100', borderWidth: 1.5, borderRadius: [4, 4, 0, 0] } },
    ],
  }
})

// ── Helpers ───────────────────────────────────────────────────────────────────

// 亿/万 两级单位（无空格），万元以下两位小数；空值显示 0.00（保持原表现）
const fmtAmt = (v) => fmtCompact(v, { dash: '0.00' })

// ── Data loading ──────────────────────────────────────────────────────────────

async function loadSummary() {
  summLoading.value = true
  try {
    const res = await ar.budgetSummary({ date_start: dateStart.value, date_end: dateEnd.value, dept: selectedDept.value })
    summary.value = res.data
  } finally { summLoading.value = false }
}

async function loadLists() {
  listLoading.value = true
  try {
    const params = { date_start: dateStart.value, date_end: dateEnd.value, dept: selectedDept.value, size: 200 }
    const [c, p] = await Promise.all([ar.listCollectionBudget(params), ar.listPaymentBudget(params)])
    collItems.value = c.data.items; collTotal.value = c.data.total_amount
    payItems.value = p.data.items; payTotal.value = p.data.total_amount
  } finally { listLoading.value = false }
}
async function loadProjects() {
  const res = await ar.listProjects({ size: 500 })
  projects.value = res.data.items || []
}

// ── 项目对照（预算 vs 实际，按项目简称打通）──────────────────────────────────
const compareData = ref(null)
const compareLoading = ref(false)
const compareQ = ref('')
const pnlTarget = ref(null)   // 点击项目行 → 业财损益卡

async function loadCompare() {
  compareLoading.value = true
  try {
    const res = await ar.budgetProjectCompare({
      date_start: dateStart.value, date_end: dateEnd.value, dept: selectedDept.value })
    compareData.value = res.data
  } catch (_) { compareData.value = null }
  finally { compareLoading.value = false }
}
// ── 对比表 Excel 风格列头筛选 + 排序（客户端：对比数据为后端聚合结果）──────────
const CMP_TAG_OPTS = ['收款达成', '收款滞后', '付款超预算', '计划外收款', '计划外付款']
const CMP_COL_META = {
  project:    { type: 'text',   get: r => r.project },
  budget_in:  { type: 'number', get: r => r.budget_in },
  actual_in:  { type: 'number', get: r => r.actual_in },
  budget_out: { type: 'number', get: r => r.budget_out },
  actual_out: { type: 'number', get: r => r.actual_out },
  actual_net: { type: 'number', get: r => r.actual_net },
  tags:       { type: 'enum',   get: r => r.tags || [] },
}
const cmpColFilters = reactive({})
const cmpSortField = ref('')
const cmpSortOrder = ref('')
function cmpClauseMatch(val, clause, type) {
  if (!clause || !clause.op) return true
  const v = clause.value
  if (type === 'enum') {
    if (!Array.isArray(v) || !v.length) return true
    return Array.isArray(val) ? val.some(x => v.includes(x)) : v.includes(val)
  }
  if (type === 'number') {
    const n = parseFloat(val); if (isNaN(n)) return false
    if (clause.op === 'between') {
      const [a, b] = Array.isArray(v) ? v : []
      if (a !== '' && a != null && n < parseFloat(a)) return false
      if (b !== '' && b != null && n > parseFloat(b)) return false
      return true
    }
    const t = parseFloat(v); if (isNaN(t)) return true
    return { eq: n === t, gt: n > t, lt: n < t, gte: n >= t, lte: n <= t }[clause.op] ?? true
  }
  const s = String(val ?? '').toLowerCase(); const qq = String(v ?? '').toLowerCase()
  return clause.op === 'eq' ? s === qq : s.includes(qq)
}
function cmpSetColFilter(field, val) {
  if (val == null) delete cmpColFilters[field]; else cmpColFilters[field] = val
}
function cmpSetSort(field, order) {
  cmpSortField.value = order ? field : ''
  cmpSortOrder.value = order || ''
}
const compareRows = computed(() => {
  let rows = compareData.value?.rows || []
  const q = compareQ.value.trim().toLowerCase()
  if (q) {
    rows = rows.filter(r => r.project.toLowerCase().includes(q)
      || (r.customer || '').toLowerCase().includes(q)
      || (r.dept || '').toLowerCase().includes(q))
  }
  const fields = Object.keys(cmpColFilters)
  if (fields.length) {
    rows = rows.filter(r => fields.every(f =>
      cmpClauseMatch(CMP_COL_META[f].get(r), cmpColFilters[f], CMP_COL_META[f].type)))
  }
  if (cmpSortField.value) {
    const meta = CMP_COL_META[cmpSortField.value]
    const dir = cmpSortOrder.value === 'desc' ? -1 : 1
    rows = [...rows].sort((a, b) => {
      let x = meta.get(a), y = meta.get(b)
      if (meta.type === 'number') { x = parseFloat(x) || 0; y = parseFloat(y) || 0 }
      else { x = String(x ?? ''); y = String(y ?? '') }
      return (x > y ? 1 : x < y ? -1 : 0) * dir
    })
  }
  return rows
})
const TAG_STYLE = {
  '收款达成': { bg: 'rgba(46,125,50,.12)', c: '#2e7d32' },
  '收款滞后': { bg: 'rgba(230,81,0,.12)', c: '#e65100' },
  '付款超预算': { bg: 'rgba(198,40,40,.12)', c: '#c62828' },
  '计划外收款': { bg: 'rgba(21,101,192,.1)', c: '#1565c0' },
  '计划外付款': { bg: 'rgba(123,31,162,.1)', c: '#7b1fa2' },
}
const barPct = (actual, budget) => {
  const b = parseFloat(budget) || 0
  if (!b) return 0
  return Math.min(100, (parseFloat(actual) || 0) / b * 100)
}
function openPnl(r) {
  pnlTarget.value = { name: r.project, year: refYear.value }
}

async function loadAll() {
  await Promise.all([loadSummary(), loadLists(), loadCompare()])
}

// ── CRUD ──────────────────────────────────────────────────────────────────────

function openCreate(type) {
  modalType.value = type; editItem.value = null
  const d = dateStart.value
  Object.assign(form, { project_no: '', short_name: '', expected_date: d, sub_dept: '', delivery_dept: selectedDept.value || (accessibleDepts.value[0] || ''), amount: '', notes: '' })
  showModal.value = true
}

function openEdit(type, item) {
  modalType.value = type; editItem.value = item
  Object.assign(form, { ...item })
  showModal.value = true
}

async function save() {
  if (!form.short_name || !form.expected_date || !form.amount) {
    toast.error('请填写项目简称、预计日期和金额'); return
  }
  saving.value = true
  try {
    if (modalType.value === 'collection') {
      if (editItem.value) await ar.updateCollectionBudget(editItem.value.id, form)
      else await ar.createCollectionBudget(form)
    } else {
      if (editItem.value) await ar.updatePaymentBudget(editItem.value.id, form)
      else await ar.createPaymentBudget(form)
    }
    showModal.value = false; await loadAll()
  } catch (e) { toast.error(e?.msg || e?.error || '操作失败')
  } finally { saving.value = false }
}

async function remove(type, item) {
  if (!confirm(`确定删除「${item.short_name}」的${type === 'collection' ? '收款' : '付款'}预算？`)) return
  try {
    if (type === 'collection') await ar.deleteCollectionBudget(item.id)
    else await ar.deletePaymentBudget(item.id)
    await loadAll()
  } catch (e) { toast.error(e?.msg || e?.error || '操作失败') }
}

// ── 右键上下文菜单 ────────────────────────────────────────────────────────────
async function copyField(val, label) {
  const ok = await copyText(val)
  ok ? toast.success(`已复制：${label}`) : toast.error('复制失败')
}

// 预算对比表（compareRows）
const ctxCmp = useContextMenu()
const CMP_COPY_COLS = [
  { key: 'project', label: '项目' },
  { key: 'budget_in', label: '收款预算', format: v => fmtAmt(v) },
  { key: 'actual_in', label: '实际收款', format: v => fmtAmt(v) },
  { key: 'budget_out', label: '付款预算', format: v => fmtAmt(v) },
  { key: 'actual_out', label: '实际付款', format: v => fmtAmt(v) },
  { key: 'actual_net', label: '净流量', format: v => fmtAmt(v) },
]
const ctxCmpItems = computed(() => {
  const r = ctxCmp.menu.payload
  if (!r) return []
  return [
    { key: 'pnl', label: '查看业财损益卡', icon: 'chart', action: row => openPnl(row) },
    { divider: true },
    { key: 'copy', label: '复制', icon: 'copy', children: [
      { key: 'copy-row', label: '复制整行', icon: 'copy', shortcut: '⌘C', action: row => copyRowTSV(row, CMP_COPY_COLS, { header: true }).then(ok => ok ? toast.success('已复制整行') : toast.error('复制失败')) },
      { divider: true },
      { key: 'copy-name', label: '项目名称', icon: 'cell', action: row => copyField(row.project, row.project) },
      { key: 'copy-net', label: '净流量', icon: 'cell', action: row => copyField(fmtAmt(row.actual_net), fmtAmt(row.actual_net)) },
    ]},
  ]
})

// 预算明细行（收款 + 付款，通过 btype 区分）
const ctxBudget = useContextMenu()
const BUDGET_COPY_COLS = [
  { key: 'project_no', label: '项目编号' },
  { key: 'short_name', label: '项目' },
  { key: 'expected_date', label: '预计日期' },
  { key: 'delivery_dept', label: '交付部门' },
  { key: 'amount', label: '金额', format: v => fmtAmt(v) },
  { key: 'notes', label: '备注' },
]
const ctxBudgetItems = computed(() => {
  const p = ctxBudget.menu.payload
  if (!p) return []
  const { btype, item: it } = p
  return [
    { key: 'edit', label: '编辑', icon: 'edit', shortcut: 'E', hidden: !auth.canArWrite, action: ({ btype: t, item: r }) => openEdit(t, r) },
    { divider: true },
    { key: 'copy', label: '复制', icon: 'copy', children: [
      { key: 'copy-row', label: '复制整行', icon: 'copy', shortcut: '⌘C', action: ({ item: r }) => copyRowTSV(r, BUDGET_COPY_COLS, { header: true }).then(ok => ok ? toast.success('已复制整行') : toast.error('复制失败')) },
      { divider: true },
      { key: 'copy-proj', label: '项目简称', icon: 'cell', hidden: !it.short_name, action: ({ item: r }) => copyField(r.short_name, r.short_name) },
      { key: 'copy-amt', label: '金额', icon: 'cell', action: ({ item: r }) => copyField(fmtAmt(r.amount), fmtAmt(r.amount)) },
    ]},
    { divider: true },
    { key: 'del', label: '删除', icon: 'trash', danger: true, hidden: !auth.canDelete, action: ({ btype: t, item: r }) => remove(t, r) },
  ]
})

// 双击数据行 → 打开编辑
function onRowDblClick(type, item, e) {
  if (e.target.closest('input, button, select, textarea, a')) return
  if (!auth.canArWrite) return
  openEdit(type, item)
}

// ── Template / Import / Export ─────────────────────────────────────────────────
const importing = ref(false)
const exporting = ref(false)
const collFileInput = ref(null)
const payFileInput = ref(null)
const precheckResult = ref(null)
const precheckBusy = ref(false)
const pendingFile = ref(null)
const pendingType = ref(null)

const saveBlob = downloadBlob

async function downloadTemplate(type) {
  try {
    const res = type === 'collection'
      ? await ar.collectionBudgetTemplate() : await ar.paymentBudgetTemplate()
    saveBlob(res, `${type === 'collection' ? '收款' : '付款'}预算导入模板.xlsx`)
  } catch (e) { toast.error(e?.msg || e?.error || '操作失败') }
}

async function handleImport(type, ev) {
  const file = ev.target.files?.[0]
  if (!file) return
  pendingFile.value = file
  pendingType.value = type
  precheckResult.value = null
  importing.value = true
  try {
    const fd = new FormData(); fd.append('file', file)
    const pr = type === 'collection'
      ? await ar.precheckCollectionBudget(fd) : await ar.precheckPaymentBudget(fd)
    const pd = pr.data
    if (pd.skipPrecheck) { await doImport(type, file); return }
    if ((pd.attention || 0) > 0) { precheckResult.value = pd; return }
    await doImport(type, file)
  } catch (e) { toast.error(e?.msg || e?.error || '操作失败')
  } finally { importing.value = false; ev.target.value = '' }
}

async function doImport(type, file) {
  importing.value = true
  try {
    const fd = new FormData(); fd.append('file', file)
    const res = type === 'collection'
      ? await ar.importCollectionBudget(fd) : await ar.importPaymentBudget(fd)
    const d = res.data
    if (d.rejected) {
      let msg = d.message || '导入未执行，请按提示修正后重新导入'
      if (d.errors?.length) msg += `\n\n需修正：\n${d.errors.slice(0, 20).join('\n')}`
      toast.error(msg)
    } else {
      let msg = `导入完成：新增 ${d.created} 条`
      if (d.corrected) msg += `，按项目台账自动更正 ${d.corrected} 条`
      if (d.warnings?.length) msg += `\n\n已更正：\n${d.warnings.slice(0, 15).join('\n')}`
      toast.success(msg)
    }
    await loadAll()
  } catch (e) { toast.error(e?.msg || e?.error || '操作失败')
  } finally { importing.value = false }
}

async function onPrecheckApply({ mode }) {
  if (mode !== 'import') return
  precheckBusy.value = true
  try {
    await doImport(pendingType.value, pendingFile.value)
    precheckResult.value = null
  } finally { precheckBusy.value = false; importing.value = false }
}

async function exportData(type) {
  exporting.value = true
  try {
    const params = { date_start: dateStart.value, date_end: dateEnd.value, dept: selectedDept.value }
    const res = type === 'collection'
      ? await ar.exportCollectionBudget(params) : await ar.exportPaymentBudget(params)
    saveBlob(res, `${type === 'collection' ? '收款' : '付款'}预算.xlsx`)
  } catch (e) { toast.error(e?.response?.data?.msg || e?.msg || e?.error || '操作失败')
  } finally { exporting.value = false }
}

onMounted(loadAll)
onMounted(loadProjects)

const onScopeChange = () => {
  if (selectedDept.value && !accessibleDepts.value.includes(selectedDept.value)) selectedDept.value = ''
  loadAll(); loadProjects()
}
onMounted(() => window.addEventListener('pk:depts-changed', onScopeChange))
onBeforeUnmount(() => window.removeEventListener('pk:depts-changed', onScopeChange))
</script>

<template>
  <div>
    <div class="topbar">
      <div>
        <h1>预算管理</h1>
        <div style="font-size:13px;color:var(--muted);margin-top:2px">
          收款预算 · 付款预算 · 执行对比
        </div>
      </div>
    </div>

    <!-- Polished filter bar -->
    <div class="bgt-filterbar">
      <div class="fbg">
        <svg class="fb-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
        <span class="fb-label">日期</span>
        <input type="date" v-model="dateStart" class="fb-sel fb-date" @change="loadAll" />
        <span class="fb-sep">~</span>
        <input type="date" v-model="dateEnd" class="fb-sel fb-date" @change="loadAll" />
      </div>
      <div class="fb-divider"></div>
      <div class="fbg">
        <svg class="fb-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>
        <span class="fb-label">事业部</span>
        <select v-model="selectedDept" class="fb-sel fb-sel-dept" @change="loadAll">
          <option value="">全部事业部</option>
          <option v-for="d in accessibleDepts" :key="d" :value="d">{{ d }}</option>
        </select>
      </div>
      <div v-if="summLoading || listLoading" class="fb-loading">
        <span class="fb-spin">↻</span> 加载中
      </div>
    </div>

    <!-- Tab bar -->
    <div class="segment-ctrl" style="margin-bottom:20px">
      <button :class="['seg-btn', activeTab === 'summary' ? 'active' : '']" @click="activeTab = 'summary'">执行概览</button>
      <button :class="['seg-btn', activeTab === 'compare' ? 'active' : '']" @click="activeTab = 'compare'">项目对照</button>
      <button :class="['seg-btn', activeTab === 'collection' ? 'active' : '']" @click="activeTab = 'collection'">收款预算</button>
      <button :class="['seg-btn', activeTab === 'payment' ? 'active' : '']" @click="activeTab = 'payment'">付款预算</button>
      <button :class="['seg-btn', activeTab === 'data' ? 'active' : '']" @click="activeTab = 'data'">数据加工</button>
    </div>

    <!-- Tab body: scrolls inside the locked viewport while header/tabs stay fixed -->
    <div class="bgt-body page-scroll">

    <!-- ── Summary Tab ── -->
    <template v-if="activeTab === 'summary'">

      <!-- Month progress bar -->
      <div class="progress-card" style="margin-bottom:16px">
        <div class="progress-header">
          <div class="progress-label">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
            {{ periodLabel }}时间进度
          </div>
          <div class="progress-meta">
            {{ monthProgress.daysPassed }} / {{ monthProgress.daysInMonth }} 天
            <span class="progress-pct-tag">{{ monthProgress.pct }}%</span>
          </div>
        </div>
        <div class="progress-track">
          <div class="progress-fill progress-fill-time" :style="`width:${monthProgress.pct}%`"></div>
        </div>
        <div class="progress-sublabel">
          <span v-if="monthProgress.isCurrentMonth">今天是 {{ periodLabel }} 第 {{ monthProgress.daysPassed }} 天，预算执行应与时间进度匹配</span>
          <span v-else-if="monthProgress.isPast">该月已结束</span>
          <span v-else>该月尚未开始</span>
        </div>
      </div>

      <!-- Two big comparison cards -->
      <div class="comparison-grid">
        <!-- Collection card -->
        <div class="compare-card compare-card-coll">
          <div class="compare-icon">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6"/></svg>
          </div>
          <div class="compare-content">
            <div class="compare-title">收款执行</div>
            <div class="compare-nums">
              <div class="compare-actual">
                <div class="cn-label">实际收款</div>
                <div class="cn-value cn-coll">{{ fmtAmt(summary?.actual_collection || 0) }}</div>
              </div>
              <div class="compare-sep">vs</div>
              <div class="compare-budget">
                <div class="cn-label">收款预算</div>
                <div class="cn-value cn-muted">{{ fmtAmt(summary?.budget_collection || 0) }}</div>
              </div>
            </div>
            <div class="compare-bar-wrap">
              <div class="compare-bar-track">
                <div class="compare-bar-fill fill-coll"
                  :style="`width:${collAchievement.pct}%`"></div>
                <div class="time-marker" :style="`left:${monthProgress.pct}%`" title="本月时间进度"></div>
              </div>
              <div class="compare-bar-labels">
                <span class="bar-achievement" :class="collAchievement.over ? 'ach-over' : ''">
                  {{ collAchievement.rawPct || '0.0' }}%
                </span>
                <span class="bar-gap" :class="parseFloat(summary?.collection_gap || 0) > 0 ? 'gap-behind' : 'gap-ok'">
                  差额 {{ fmtAmt(summary?.collection_gap || 0) }}
                </span>
              </div>
            </div>
          </div>
        </div>

        <!-- Payment card -->
        <div class="compare-card compare-card-pay">
          <div class="compare-icon">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="1" y="4" width="22" height="16" rx="2"/><line x1="1" y1="10" x2="23" y2="10"/></svg>
          </div>
          <div class="compare-content">
            <div class="compare-title">付款执行</div>
            <div class="compare-nums">
              <div class="compare-actual">
                <div class="cn-label">实际付款</div>
                <div class="cn-value" :class="summary?.has_alert ? 'cn-danger' : 'cn-pay'">{{ fmtAmt(summary?.actual_payment || 0) }}</div>
              </div>
              <div class="compare-sep">vs</div>
              <div class="compare-budget">
                <div class="cn-label">付款预算</div>
                <div class="cn-value cn-muted">{{ fmtAmt(summary?.budget_payment || 0) }}</div>
              </div>
            </div>
            <div class="compare-bar-wrap">
              <div class="compare-bar-track">
                <div class="compare-bar-fill" :class="summary?.has_alert ? 'fill-danger' : 'fill-pay'"
                  :style="`width:${payAchievement.pct}%`"></div>
                <div class="time-marker" :style="`left:${monthProgress.pct}%`" title="本月时间进度"></div>
              </div>
              <div class="compare-bar-labels">
                <span class="bar-achievement" :class="payAchievement.over ? 'ach-over' : ''">
                  {{ payAchievement.rawPct || '0.0' }}%
                </span>
                <span class="bar-gap">
                  差额 {{ fmtAmt(summary?.payment_gap || 0) }}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Net cashflow + chart -->
      <div class="bottom-grid">
        <!-- Net metric -->
        <div class="card net-card">
          <div class="net-label">净现金流（现金流入 − 现金流出）</div>
          <div class="net-value" :class="netCashflow >= 0 ? 'net-pos' : 'net-neg'">
            {{ netCashflow >= 0 ? '+' : '' }}{{ fmtAmt(netCashflow) }}
          </div>
          <div class="net-sub">{{ periodLabel }} · {{ selectedDept || '全部事业部' }} · 同「现金流分析」口径</div>
          <div class="net-breakdown">
            <div class="nb-item"><span class="nb-dot nb-coll"></span>现金流入 {{ fmtAmt(cashInflow) }}</div>
            <div class="nb-item"><span class="nb-dot nb-pay"></span>现金流出 {{ fmtAmt(cashOutflow) }}</div>
          </div>
        </div>

        <!-- Bar chart -->
        <div class="card" style="padding:20px">
          <div class="section-title">预算 vs 实际对比</div>
          <BaseChart v-if="comparisonChartOption" :option="comparisonChartOption" height="180px" />
          <EmptyState v-else icon="📊" text="暂无预算数据" />
        </div>
      </div>

      <!-- Per-dept comparison (only when user has access to multiple depts and no specific dept selected) -->
      <div v-if="summary?.by_dept?.length > 1" class="card" style="margin-top:16px;padding:20px">
        <div class="section-title">各事业部对比</div>
        <BaseChart v-if="deptCompareOption" :option="deptCompareOption" height="240px" />
      </div>

    </template>

    <!-- ── 项目对照 Tab：预算 vs 实际，按项目简称打通 ── -->
    <template v-else-if="activeTab === 'compare'">
      <!-- 汇总条 -->
      <div v-if="compareData?.summary" class="cmp-kpi-bar">
        <div class="cmp-kpi">
          <span class="k">收款预算 → 实际</span>
          <span class="v"><i class="muted">{{ fmtAmt(compareData.summary.budget_in) }}</i> → <b class="ok">{{ fmtAmt(compareData.summary.actual_in) }}</b></span>
          <span class="r" :class="(compareData.summary.in_rate ?? 0) >= 100 ? 'ok' : 'warn'">{{ compareData.summary.in_rate != null ? compareData.summary.in_rate + '%' : '—' }}</span>
        </div>
        <div class="cmp-kpi-sep"></div>
        <div class="cmp-kpi">
          <span class="k">付款预算 → 实际</span>
          <span class="v"><i class="muted">{{ fmtAmt(compareData.summary.budget_out) }}</i> → <b class="bad">{{ fmtAmt(compareData.summary.actual_out) }}</b></span>
          <span class="r" :class="(compareData.summary.out_rate ?? 0) > 100 ? 'bad' : ''">{{ compareData.summary.out_rate != null ? compareData.summary.out_rate + '%' : '—' }}</span>
        </div>
        <div class="cmp-kpi-sep"></div>
        <div class="cmp-kpi">
          <span class="k">净现金 计划 vs 实际</span>
          <span class="v">
            <i class="muted">{{ fmtAmt(compareData.summary.budget_net) }}</i> vs
            <b :style="{ color: parseFloat(compareData.summary.actual_net) >= 0 ? '#2e7d32' : '#c62828' }">{{ fmtAmt(compareData.summary.actual_net) }}</b>
          </span>
        </div>
        <div class="cmp-kpi-sep"></div>
        <div class="cmp-chips">
          <span class="cmp-chip ok">达成 {{ compareData.summary.achieved }}</span>
          <span class="cmp-chip warn">滞后 {{ compareData.summary.lagging }}</span>
          <span class="cmp-chip bad">超支 {{ compareData.summary.over_budget }}</span>
          <span class="cmp-chip blue">计划外 {{ compareData.summary.unplanned }}</span>
        </div>
      </div>

      <div class="card">
        <div class="list-header">
          <div>
            <div class="section-title" style="margin:0">项目维度对照<span style="font-size:12px;font-weight:400;color:var(--muted);margin-left:8px">{{ periodLabel }} · 预算与实际收付经「项目简称」对齐 · 点击行查看业财损益卡</span></div>
          </div>
          <div class="hdr-acts">
            <input v-model="compareQ" class="cmp-search" placeholder="搜项目 / 客户 / 部门" />
          </div>
        </div>
        <EmptyState v-if="compareLoading" loading />
        <div v-else-if="!compareRows.length" class="empty-cell" style="padding:36px;text-align:center">
          {{ compareQ ? '无匹配项目' : '该时段内没有关联项目简称的预算或实际收付——预算录入和回款/排款都填了项目简称才能对上' }}
        </div>
        <div v-else class="table-wrap">
          <table class="cmp-table">
            <thead>
              <tr>
                <th style="min-width:150px"><ColumnFilter label="项目" field="project" type="text" :model-value="cmpColFilters.project" :sort-field="cmpSortField" :sort-order="cmpSortOrder" @update:model-value="v=>cmpSetColFilter('project',v)" @sort="o=>cmpSetSort('project',o)" /></th>
                <th class="amt"><ColumnFilter label="收款预算" field="budget_in" type="number" :model-value="cmpColFilters.budget_in" :sort-field="cmpSortField" :sort-order="cmpSortOrder" @update:model-value="v=>cmpSetColFilter('budget_in',v)" @sort="o=>cmpSetSort('budget_in',o)" /></th>
                <th style="min-width:150px"><ColumnFilter label="实际收款 / 达成" field="actual_in" type="number" :model-value="cmpColFilters.actual_in" :sort-field="cmpSortField" :sort-order="cmpSortOrder" @update:model-value="v=>cmpSetColFilter('actual_in',v)" @sort="o=>cmpSetSort('actual_in',o)" /></th>
                <th class="amt"><ColumnFilter label="付款预算" field="budget_out" type="number" :model-value="cmpColFilters.budget_out" :sort-field="cmpSortField" :sort-order="cmpSortOrder" @update:model-value="v=>cmpSetColFilter('budget_out',v)" @sort="o=>cmpSetSort('budget_out',o)" /></th>
                <th style="min-width:150px"><ColumnFilter label="实际付款 / 执行" field="actual_out" type="number" :model-value="cmpColFilters.actual_out" :sort-field="cmpSortField" :sort-order="cmpSortOrder" @update:model-value="v=>cmpSetColFilter('actual_out',v)" @sort="o=>cmpSetSort('actual_out',o)" /></th>
                <th class="amt"><ColumnFilter label="净现金(实际)" field="actual_net" type="number" :model-value="cmpColFilters.actual_net" :sort-field="cmpSortField" :sort-order="cmpSortOrder" @update:model-value="v=>cmpSetColFilter('actual_net',v)" @sort="o=>cmpSetSort('actual_net',o)" /></th>
                <th><ColumnFilter label="状态" field="tags" type="enum" :sortable="false" :options="CMP_TAG_OPTS" :model-value="cmpColFilters.tags" @update:model-value="v=>cmpSetColFilter('tags',v)" /></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in compareRows" :key="r.project" class="cmp-row" @click="openPnl(r)" @contextmenu.prevent="ctxCmp.open($event, r)">
                <td>
                  <div class="fw">{{ r.project }}</div>
                  <div class="cmp-sub">{{ r.dept || '—' }}<template v-if="r.manager"> · {{ r.manager }}</template></div>
                </td>
                <td class="amt muted">{{ parseFloat(r.budget_in) ? fmtAmt(r.budget_in) : '—' }}</td>
                <td>
                  <div class="cmp-bar-line">
                    <b class="ok">{{ parseFloat(r.actual_in) ? fmtAmt(r.actual_in) : '—' }}</b>
                    <span v-if="r.in_rate != null" class="cmp-rate" :class="r.in_rate >= 100 ? 'ok' : (r.in_rate >= monthProgress.pct ? '' : 'warn')">{{ r.in_rate }}%</span>
                  </div>
                  <div v-if="parseFloat(r.budget_in)" class="cmp-track">
                    <div class="cmp-fill in" :style="`width:${barPct(r.actual_in, r.budget_in)}%`"></div>
                    <i class="cmp-tick" :style="`left:${monthProgress.pct}%`" title="时间进度"></i>
                  </div>
                </td>
                <td class="amt muted">{{ parseFloat(r.budget_out) ? fmtAmt(r.budget_out) : '—' }}</td>
                <td>
                  <div class="cmp-bar-line">
                    <b class="bad">{{ parseFloat(r.actual_out) ? fmtAmt(r.actual_out) : '—' }}</b>
                    <span v-if="r.out_rate != null" class="cmp-rate" :class="r.out_rate > 100 ? 'bad' : ''">{{ r.out_rate }}%</span>
                  </div>
                  <div v-if="parseFloat(r.budget_out)" class="cmp-track">
                    <div class="cmp-fill out" :class="{ over: r.out_rate > 100 }" :style="`width:${barPct(r.actual_out, r.budget_out)}%`"></div>
                  </div>
                </td>
                <td class="amt fw" :style="{ color: parseFloat(r.actual_net) >= 0 ? '#2e7d32' : '#c62828' }">{{ fmtAmt(r.actual_net) }}</td>
                <td>
                  <span v-for="t in r.tags" :key="t" class="cmp-tag"
                    :style="{ background: TAG_STYLE[t]?.bg, color: TAG_STYLE[t]?.c }">{{ t }}</span>
                  <span v-if="!r.tags.length" class="muted" style="font-size:11px">—</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>

    <!-- ── Collection Budget Tab ── -->
    <template v-else-if="activeTab === 'collection'">
      <div class="card">
        <div class="list-header">
          <div>
            <div class="section-title" style="margin:0">收款预算</div>
            <div style="font-size:13px;color:var(--muted);margin-top:3px">
              合计 <b style="color:var(--text)">{{ fmtAmt(collTotal) }}</b>
            </div>
          </div>
          <div class="hdr-acts">
            <button class="btn btn-ghost btn-sm" @click="activeTab = 'data'">⇅ 模板/导入/导出</button>
            <button v-if="auth.canArWrite" class="btn btn-primary btn-sm" @click="openCreate('collection')">+ 新增收款预算</button>
          </div>
        </div>
        <div class="table-wrap">
          <table class="budget-table">
            <thead>
              <tr>
                <th>项目编号</th><th>项目简称 / 摘要</th>
                <th class="ctr">预计收款日期</th><th>二级部门</th>
                <th>交付部门</th><th class="amt">金额</th>
                <th>备注</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="!collItems.length">
                <td colspan="7" class="empty-cell">暂无收款预算数据</td>
              </tr>
              <tr v-for="item in collItems" :key="item.id" class="data-row" @contextmenu.prevent="ctxBudget.open($event, { btype: 'collection', item })" @dblclick="onRowDblClick('collection', item, $event)">
                <td><span class="proj-no-tag">{{ item.project_no || '—' }}</span></td>
                <td class="fw">{{ item.short_name }}</td>
                <td class="ctr text-sm">{{ item.expected_date }}</td>
                <td class="text-muted">{{ item.sub_dept }}</td>
                <td><span class="dept-chip">{{ item.delivery_dept || '—' }}</span></td>
                <td class="amt coll-amt fw">{{ fmtAmt(item.amount) }}</td>
                <td class="text-muted">{{ item.notes }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>

    <!-- ── Payment Budget Tab ── -->
    <template v-else-if="activeTab === 'payment'">
      <div class="card">
        <div class="list-header">
          <div>
            <div class="section-title" style="margin:0">付款预算</div>
            <div style="font-size:13px;color:var(--muted);margin-top:3px">
              合计 <b style="color:var(--text)">{{ fmtAmt(payTotal) }}</b>
            </div>
          </div>
          <div class="hdr-acts">
            <button class="btn btn-ghost btn-sm" @click="activeTab = 'data'">⇅ 模板/导入/导出</button>
            <button v-if="auth.canArWrite" class="btn btn-primary btn-sm" @click="openCreate('payment')">+ 新增付款预算</button>
          </div>
        </div>
        <div class="table-wrap">
          <table class="budget-table">
            <thead>
              <tr>
                <th>项目编号</th><th>项目简称 / 摘要</th>
                <th class="ctr">预计付款日期</th><th>二级部门</th>
                <th>交付部门</th><th class="amt">金额</th>
                <th>备注</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="!payItems.length">
                <td colspan="7" class="empty-cell">暂无付款预算数据</td>
              </tr>
              <tr v-for="item in payItems" :key="item.id" class="data-row" @contextmenu.prevent="ctxBudget.open($event, { btype: 'payment', item })" @dblclick="onRowDblClick('payment', item, $event)">
                <td><span class="proj-no-tag">{{ item.project_no || '—' }}</span></td>
                <td class="fw">{{ item.short_name }}</td>
                <td class="ctr text-sm">{{ item.expected_date }}</td>
                <td class="text-muted">{{ item.sub_dept }}</td>
                <td><span class="dept-chip">{{ item.delivery_dept || '—' }}</span></td>
                <td class="amt pay-amt fw">{{ fmtAmt(item.amount) }}</td>
                <td class="text-muted">{{ item.notes }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>

    <!-- ── 数据加工 Tab：模板 / 导入 / 导出 集中处理 ── -->
    <template v-else-if="activeTab === 'data'">
      <div class="data-grid">
        <div class="data-card">
          <div class="dc-head">
            <span class="dc-icon coll">↓</span>
            <div>
              <div class="dc-title">收款预算</div>
              <div class="dc-sub">按「项目简称」关联台账；导入时自动校正项目编号/部门</div>
            </div>
          </div>
          <div class="dc-acts">
            <button class="btn btn-ghost" @click="downloadTemplate('collection')">↓ 下载模板</button>
            <label class="btn btn-ghost" style="cursor:pointer">
              {{ importing ? '导入中…' : '↑ 导入数据' }}
              <input type="file" accept=".xlsx,.xls" style="display:none" @change="handleImport('collection', $event)" />
            </label>
            <button class="btn btn-ghost" :disabled="exporting" @click="exportData('collection')">↓ 导出（当前筛选）</button>
          </div>
          <ul class="dc-tips">
            <li>模板含填写说明行与示例行（导入时自动跳过）</li>
            <li>整表校验：任一行有问题全表拒绝并列出原因，不会半截写入</li>
            <li>导出范围 = 顶部日期区间 + 事业部筛选（{{ periodLabel }}）</li>
          </ul>
        </div>
        <div class="data-card">
          <div class="dc-head">
            <span class="dc-icon pay">↑</span>
            <div>
              <div class="dc-title">付款预算</div>
              <div class="dc-sub">同收款预算；项目简称对齐后可在「项目对照」追踪执行</div>
            </div>
          </div>
          <div class="dc-acts">
            <button class="btn btn-ghost" @click="downloadTemplate('payment')">↓ 下载模板</button>
            <label class="btn btn-ghost" style="cursor:pointer">
              {{ importing ? '导入中…' : '↑ 导入数据' }}
              <input type="file" accept=".xlsx,.xls" style="display:none" @change="handleImport('payment', $event)" />
            </label>
            <button class="btn btn-ghost" :disabled="exporting" @click="exportData('payment')">↓ 导出（当前筛选）</button>
          </div>
          <ul class="dc-tips">
            <li>预算填了项目简称，实际收付也填了，项目对照才能对上账</li>
            <li>非项目类预算（如房租水电）简称可手填摘要，不参与项目对照</li>
          </ul>
        </div>
      </div>
    </template>

    </div><!-- /.bgt-body -->

    <!-- 业财损益卡（项目对照点击行） -->
    <ProjectPnlCard v-if="pnlTarget" :name="pnlTarget.name" :year="pnlTarget.year"
      :askable="false" @close="pnlTarget = null" />

    <!-- Modal -->
    <Teleport to="body">
      <div v-if="showModal" class="modal-overlay" @click.self="showModal = false">
        <div class="modal-box" style="max-width:480px">
          <div class="modal-header">
            <div>
              <h3>{{ editItem ? '编辑' : '新增' }}{{ modalType === 'collection' ? '收款' : '付款' }}预算</h3>
              <div style="font-size:12px;color:var(--muted);margin-top:2px">{{ periodLabel }}</div>
            </div>
            <button class="modal-close" @click="showModal = false">✕</button>
          </div>
          <div class="modal-body">
            <div class="form-grid">
              <label class="form-field">
                <span>项目编号{{ modalType === 'payment' ? '（不强制）' : '（可选）' }}</span>
                <input v-model="form.project_no" placeholder="填写后可关联项目" />
              </label>
              <label class="form-field">
                <span>项目简称 / 摘要 <em>*</em></span>
                <input v-model="form.short_name" list="budget-project-shortnames" placeholder="可手填非项目信息；也可下拉选择项目简称" />
                <datalist id="budget-project-shortnames">
                  <option v-for="p in shortNameOptions" :key="p.id" :value="p.short_name">
                    {{ p.project_no }} · {{ p.short_name }}
                  </option>
                </datalist>
              </label>
              <label class="form-field">
                <span>预计{{ modalType === 'collection' ? '收款' : '付款' }}日期 <em>*</em></span>
                <input v-model="form.expected_date" type="date" />
              </label>
              <label class="form-field">
                <span>金额 <em>*</em></span>
                <input v-model="form.amount" type="number" step="0.01" placeholder="0.00" />
              </label>
              <label class="form-field">
                <span>交付部门</span>
                <select v-model="form.delivery_dept">
                  <option value="">不限</option>
                  <option v-for="d in accessibleDepts" :key="d" :value="d">{{ d }}</option>
                </select>
              </label>
              <label class="form-field">
                <span>二级部门</span>
                <input v-model="form.sub_dept" />
              </label>
              <label class="form-field span2">
                <span>备注</span>
                <input v-model="form.notes" />
              </label>
            </div>
          </div>
          <div class="modal-footer">
            <button class="btn btn-ghost" @click="showModal = false">取消</button>
            <button class="btn btn-primary" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存' }}</button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- 导入预检弹窗 -->
    <ImportPrecheckModal :report="precheckResult" :busy="precheckBusy" :readonly="true"
      @close="precheckResult = null" @apply="onPrecheckApply" />

    <!-- 右键上下文菜单 -->
    <ContextMenu :ctx="ctxCmp" :items="ctxCmpItems" />
    <ContextMenu :ctx="ctxBudget" :items="ctxBudgetItems" />
  </div>
</template>

<style scoped>
/* ── Fixed-viewport layout: header/tabs stay put, tab body scrolls ── */
.bgt-body { /* .page-scroll (global) handles flex-grow + overflow */ }
.topbar,
.bgt-filterbar,
.segment-ctrl { flex-shrink: 0; }

/* ── Filter bar ── */
.bgt-filterbar {
  display: flex; align-items: center;
  background: rgba(255,255,255,0.96); border: 1px solid rgba(255,255,255,0.9);
  border-radius: 14px; padding: 4px 10px;
  box-shadow: 0 2px 14px rgba(0,0,0,0.06);
  margin-bottom: 20px;
  flex-wrap: nowrap; overflow-x: auto;
}
.fbg { display: flex; align-items: center; gap: 7px; padding: 5px 10px; }
.fb-icon { color: var(--muted); flex-shrink: 0; }
.fb-label { font-size: 11.5px; font-weight: 600; color: var(--muted); white-space: nowrap; }
.fb-divider { width: 1px; height: 24px; background: rgba(0,0,0,0.09); margin: 0 4px; flex-shrink: 0; }
.fb-sel {
  height: 30px; padding: 0 10px; border: none;
  background: rgba(0,0,0,0.04); border-radius: 8px;
  font-size: 12.5px; color: var(--text); cursor: pointer; outline: none;
  transition: background .15s, color .15s;
}
.fb-sel:hover, .fb-sel:focus { background: rgba(201,99,66,0.09); color: var(--primary); }
.fb-sel-mo   { width: 60px; }
.fb-sel-dept { min-width: 110px; }
.fb-date     { width: 126px; padding: 0 7px; }
.fb-sep      { font-size: 12px; color: var(--muted); margin: 0 2px; }
.fb-loading  { margin-left: auto; padding-left: 12px; font-size: 12px; color: var(--primary); display: flex; align-items: center; gap: 5px; }
.fb-spin { display: inline-block; animation: fbSpin 0.9s linear infinite; }
@keyframes fbSpin { to { transform: rotate(360deg); } }

/* ── Compact alert strip (top of summary tab) ── */
.alert-strip {
  position: relative; overflow: hidden;
  display: flex; align-items: center; gap: 10px;
  padding: 10px 16px; margin-bottom: 16px;
  background: rgba(198,40,40,.05);
  border-left: 3.5px solid #c62828;
  border-radius: 0 10px 10px 0;
}
.ast-pulse {
  position: absolute; inset: 0;
  background: linear-gradient(90deg, rgba(198,40,40,.06) 0%, transparent 60%);
}
.ast-icon { color: #c62828; flex-shrink: 0; z-index: 1; display: flex; }
.ast-body { display: flex; align-items: center; gap: 0; flex-wrap: wrap; z-index: 1; }
.ast-title { font-weight: 700; color: #c62828; font-size: 13px; }
.ast-sep    { margin: 0 6px; color: rgba(198,40,40,.4); font-size: 12px; }
.ast-desc   { font-size: 12px; color: #c62828; opacity: .82; }

/* Segment control */
.segment-ctrl { display: inline-flex; gap: 0; padding: 4px; background: rgba(0,0,0,0.04); border-radius: 12px; }
.seg-btn { padding: 7px 20px; border-radius: 9px; border: none; font-size: 13px; font-weight: 500; color: var(--muted); background: transparent; cursor: pointer; transition: all 0.18s; }
.seg-btn.active { background: white; color: var(--primary); font-weight: 700; box-shadow: 0 2px 8px rgba(0,0,0,0.12); }

/* Month progress card */
.progress-card {
  background: rgba(255,255,255,0.85); border: 1px solid rgba(255,255,255,0.8);
  border-radius: 14px; padding: 18px 22px;
  box-shadow: 0 2px 16px rgba(0,0,0,0.06);
}
.progress-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.progress-label { display: flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 600; color: var(--text); }
.progress-meta { font-size: 13px; color: var(--muted); display: flex; align-items: center; gap: 8px; }
.progress-pct-tag { background: rgba(21,101,192,0.1); color: #1565c0; font-weight: 700; font-size: 13px; padding: 2px 8px; border-radius: 8px; }
.progress-track { height: 8px; background: rgba(0,0,0,0.07); border-radius: 99px; overflow: hidden; }
.progress-fill { height: 100%; border-radius: 99px; transition: width 0.6s cubic-bezier(0.25,0.46,0.45,0.94); }
.progress-fill-time { background: linear-gradient(90deg, #1565c0, #42a5f5); }
.progress-sublabel { margin-top: 8px; font-size: 12px; color: var(--muted); }

/* Comparison grid */
.comparison-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px; }
@media (max-width: 760px) { .comparison-grid { grid-template-columns: 1fr; } }

.compare-card {
  background: rgba(255,255,255,0.88); border: 1px solid rgba(255,255,255,0.8);
  border-radius: 16px; padding: 22px; display: flex; gap: 16px; align-items: flex-start;
  box-shadow: 0 4px 20px rgba(0,0,0,0.07);
  transition: box-shadow 0.2s, transform 0.2s;
}
.compare-card:hover { box-shadow: 0 8px 32px rgba(0,0,0,0.10); transform: translateY(-2px); }
.compare-card-coll { border-top: 3px solid #2e7d32; }
.compare-card-pay  { border-top: 3px solid #f57f17; }
.compare-icon {
  width: 44px; height: 44px; border-radius: 12px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
}
.compare-card-coll .compare-icon { background: rgba(46,125,50,0.1); color: #2e7d32; }
.compare-card-pay  .compare-icon { background: rgba(245,127,23,0.1); color: #f57f17; }

.compare-content { flex: 1; min-width: 0; }
.compare-title { font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.07em; color: var(--muted); margin-bottom: 12px; }
.compare-nums { display: flex; align-items: center; gap: 14px; margin-bottom: 16px; }
.compare-actual, .compare-budget { flex: 1; }
.cn-label { font-size: 11px; color: var(--muted); margin-bottom: 3px; }
.cn-value { font-size: 22px; font-weight: 800; line-height: 1; }
.cn-coll   { color: #2e7d32; }
.cn-pay    { color: #e65100; }
.cn-danger { color: #c62828; }
.cn-muted  { color: var(--muted); font-size: 18px; font-weight: 600; }
.compare-sep { font-size: 12px; color: var(--muted); flex-shrink: 0; padding-top: 16px; }

.compare-bar-wrap { margin-top: 4px; }
.compare-bar-track {
  height: 10px; background: rgba(0,0,0,0.07); border-radius: 99px;
  overflow: visible; position: relative; margin-bottom: 8px;
}
.compare-bar-fill {
  height: 100%; border-radius: 99px; position: absolute; top: 0; left: 0;
  transition: width 0.7s cubic-bezier(0.25,0.46,0.45,0.94);
}
.fill-coll    { background: linear-gradient(90deg, #2e7d32, #66bb6a); }
.fill-pay     { background: linear-gradient(90deg, #e65100, #ffa726); }
.fill-danger  { background: linear-gradient(90deg, #c62828, #ef5350); }
.time-marker {
  position: absolute; top: -4px; width: 2px; height: 18px; background: rgba(21,101,192,0.6);
  border-radius: 2px; transform: translateX(-50%);
  transition: left 0.4s ease;
}
.compare-bar-labels { display: flex; justify-content: space-between; align-items: center; }
.bar-achievement { font-size: 13px; font-weight: 700; color: var(--text); }
.ach-over { color: #2e7d32; }
.bar-gap { font-size: 12px; color: var(--muted); }
.gap-behind { color: #e65100; }
.gap-ok { color: #2e7d32; }

/* Bottom grid */
.bottom-grid { display: grid; grid-template-columns: 1fr 2fr; gap: 16px; }
@media (max-width: 760px) { .bottom-grid { grid-template-columns: 1fr; } }

.net-card { display: flex; flex-direction: column; gap: 8px; }
.net-label { font-size: 12px; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; }
.net-value { font-size: 32px; font-weight: 800; line-height: 1; }
.net-pos { color: #2e7d32; }
.net-neg { color: #c62828; }
.net-sub { font-size: 12px; color: var(--muted); }
.net-breakdown { display: flex; flex-direction: column; gap: 5px; margin-top: 4px; padding-top: 12px; border-top: 1px solid var(--border); }
.nb-item { display: flex; align-items: center; gap: 7px; font-size: 12.5px; color: var(--muted); }
.nb-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.nb-coll { background: #2e7d32; }
.nb-pay  { background: #f57f17; }

/* List header */
.list-header { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 16px; gap: 12px; flex-wrap: wrap; }
.hdr-acts { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.act-btn {
  padding: 6px 12px; border-radius: 8px; font-size: 12.5px; font-weight: 500;
  border: 1px solid var(--border); background: rgba(255,252,250,0.8); color: var(--muted);
  cursor: pointer; transition: all 0.14s; white-space: nowrap;
}
.act-btn:hover { border-color: var(--primary); color: var(--primary); }
.act-btn:disabled { opacity: 0.4; cursor: default; }

/* Budget table */
.budget-table { width: 100%; }
.budget-table th { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); padding: 9px 12px; background: rgba(0,0,0,0.02); }
.budget-table td { padding: 10px 12px; vertical-align: middle; }
.data-row:hover { background: rgba(201,99,66,0.03); }
.data-row:not(:last-child) td { border-bottom: 1px solid rgba(0,0,0,0.04); }
.empty-cell { text-align: center; padding: 40px !important; color: var(--muted); }

.proj-no-tag { font-family: monospace; font-size: 11.5px; color: var(--muted); background: rgba(0,0,0,0.04); padding: 2px 7px; border-radius: 5px; }
.dept-chip { font-size: 11.5px; padding: 2px 9px; border-radius: 10px; background: rgba(201,99,66,0.1); color: var(--primary); font-weight: 600; }
.fw { font-weight: 600; }
.ctr { text-align: center; }
.amt { text-align: right; }
.text-muted { color: var(--muted); }
.text-sm { font-size: 12.5px; }
.coll-amt { color: #2e7d32; }
.pay-amt  { color: #e65100; }

.row-acts { display: flex; gap: 4px; justify-content: center; }
.icon-btn { width: 26px; height: 26px; border-radius: 6px; border: 1px solid var(--border); background: rgba(255,252,250,0.7); display: flex; align-items: center; justify-content: center; color: var(--muted); cursor: pointer; transition: all 0.13s; }
.icon-btn:hover { border-color: var(--primary); color: var(--primary); }
.icon-btn-del:hover { border-color: var(--danger); color: var(--danger); background: rgba(198,40,40,0.07); }

/* ══ 项目对照 ══ */
.cmp-kpi-bar { display: flex; align-items: center; gap: 0; flex-wrap: wrap; margin-bottom: 16px;
  background: rgba(255,255,255,.7); border: 1px solid rgba(180,140,110,.18); border-radius: 12px;
  padding: 12px 18px; box-shadow: 0 2px 8px rgba(100,60,30,.07); }
.cmp-kpi { display: flex; flex-direction: column; gap: 3px; padding: 0 16px; }
.cmp-kpi .k { font-size: 11px; color: var(--muted); }
.cmp-kpi .v { font-size: 14.5px; font-variant-numeric: tabular-nums; color: var(--text); }
.cmp-kpi .v i { font-style: normal; }
.cmp-kpi .v .muted, .cmp-kpi .muted { color: var(--muted); }
.cmp-kpi .ok { color: #2e7d32; } .cmp-kpi .bad { color: #c62828; } .cmp-kpi .warn { color: #e65100; }
.cmp-kpi .r { font-size: 12px; font-weight: 800; }
.cmp-kpi-sep { width: 1px; height: 34px; background: rgba(180,140,110,.2); flex-shrink: 0; }
.cmp-chips { display: flex; gap: 8px; padding: 0 16px; flex-wrap: wrap; }
.cmp-chip { font-size: 11.5px; font-weight: 700; padding: 3px 11px; border-radius: 11px; }
.cmp-chip.ok { background: rgba(46,125,50,.1); color: #2e7d32; }
.cmp-chip.warn { background: rgba(230,81,0,.1); color: #e65100; }
.cmp-chip.bad { background: rgba(198,40,40,.1); color: #c62828; }
.cmp-chip.blue { background: rgba(21,101,192,.08); color: #1565c0; }

.cmp-search { border: 1px solid var(--border); border-radius: 8px; padding: 6px 12px; font-size: 13px; width: 210px; background: rgba(255,255,255,.8); }
.cmp-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.cmp-table th { padding: 9px 12px; text-align: left; font-size: 11.5px; font-weight: 700; color: var(--muted);
  background: rgba(201,99,66,.05); border-bottom: 1px solid rgba(180,140,110,.15); white-space: nowrap; overflow: visible; }
.cmp-table th.amt { text-align: right; }
.cmp-table td { padding: 9px 12px; border-bottom: 1px solid rgba(180,140,110,.08); vertical-align: middle; }
.cmp-table td.amt { text-align: right; font-variant-numeric: tabular-nums; }
.cmp-row { cursor: pointer; }
.cmp-row:hover td { background: rgba(201,99,66,.04); }
.cmp-sub { font-size: 11px; color: var(--muted); margin-top: 2px; }
.cmp-bar-line { display: flex; align-items: center; gap: 8px; }
.cmp-bar-line b { font-variant-numeric: tabular-nums; }
.cmp-bar-line .ok { color: #2e7d32; } .cmp-bar-line .bad { color: #c62828; }
.cmp-rate { font-size: 11px; font-weight: 800; color: var(--muted); }
.cmp-rate.ok { color: #2e7d32; } .cmp-rate.warn { color: #e65100; } .cmp-rate.bad { color: #c62828; }
.cmp-track { position: relative; height: 5px; border-radius: 3px; background: rgba(120,120,120,.12); margin-top: 5px; overflow: visible; }
.cmp-fill { height: 100%; border-radius: 3px; transition: width .4s ease; }
.cmp-fill.in { background: linear-gradient(90deg, #66bb6a, #2e7d32); }
.cmp-fill.out { background: linear-gradient(90deg, #ffb74d, #ef6c00); }
.cmp-fill.out.over { background: linear-gradient(90deg, #ef5350, #c62828); }
.cmp-tick { position: absolute; top: -3px; bottom: -3px; width: 2px; background: rgba(60,60,60,.45); border-radius: 1px; }
.cmp-tag { display: inline-block; font-size: 10.5px; font-weight: 700; padding: 2px 8px; border-radius: 9px; margin: 1px 3px 1px 0; white-space: nowrap; }
.muted { color: var(--muted); }

/* ══ 数据加工 ══ */
.data-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
@media (max-width: 860px) { .data-grid { grid-template-columns: 1fr; } }
.data-card { background: rgba(255,255,255,.7); border: 1px solid rgba(180,140,110,.18); border-radius: 14px;
  padding: 18px 20px; box-shadow: 0 2px 10px rgba(100,60,30,.07); }
.dc-head { display: flex; align-items: center; gap: 12px; margin-bottom: 14px; }
.dc-icon { width: 38px; height: 38px; border-radius: 10px; display: flex; align-items: center; justify-content: center;
  font-size: 18px; font-weight: 800; flex-shrink: 0; }
.dc-icon.coll { background: rgba(46,125,50,.1); color: #2e7d32; }
.dc-icon.pay { background: rgba(230,81,0,.1); color: #ef6c00; }
.dc-title { font-size: 15px; font-weight: 800; color: var(--text); }
.dc-sub { font-size: 12px; color: var(--muted); margin-top: 2px; }
.dc-acts { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
.dc-tips { margin: 0; padding-left: 18px; }
.dc-tips li { font-size: 12px; color: var(--muted); line-height: 1.9; }

@media (max-width: 640px) {
  .cmp-kpi-bar { flex-wrap: wrap !important; }
}
</style>
