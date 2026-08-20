<script setup>
import { ref, computed, reactive, watch, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../../stores/auth.js'
import { DEPARTMENTS, yearCST, monthCST } from '../../constants.js'
import ar from '../../api/ar.js'
import ContextMenu from '../../components/ContextMenu.vue'
import DateRangeChips from '../../components/DateRangeChips.vue'
import { useContextMenu } from '../../composables/useContextMenu.js'
import { useToast } from '../../composables/useToast.js'
import { copyText, copyRowTSV } from '../../utils/clipboard.js'
import { loadPref, savePref } from '../../utils/prefs.js'
import { downloadBlob } from '../../utils/download.js'
import { fmtCompact } from '../../utils/format.js'
import { HIDE_OVERLAP } from '../../utils/chartTheme.js'
import { activeIndices, densityOf } from '../../utils/chartDensity.js'
import BaseChart from '../../components/ar/BaseChart.vue'
import CashStory from '../../components/ar/CashStory.vue'
import Amt from '../../components/Amt.vue'

defineProps({ embedded: { type: Boolean, default: false } })

const auth = useAuthStore()
const router = useRouter()

const CY = yearCST()
const CM = monthCST()

// Default: current month start → current month end (day-level)
function monthStartISO(y, m) { return `${y}-${String(m).padStart(2, '0')}-01` }
function monthEndISO(y, m) {
  const d = new Date(y, m, 0)  // last day of month m (1-12)
  return `${y}-${String(m).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
const filters = reactive({
  start_date: monthStartISO(CY, CM),
  end_date: monthEndISO(CY, CM),
  dept: '',   // '' = all accessible depts; specific name = one dept
})

const accessibleDepts = computed(() => auth.effectiveDepts.filter(d => DEPARTMENTS.includes(d)))
const cfData = ref(null)
const loading = ref(false)


// 亿/万 两级单位（无空格，两位小数），万元以下取整；空值显示「0」
const fmtWan = (v) => fmtCompact(v, { smallRound: true, dash: '0' })

// ── 右键上下文菜单 ────────────────────────────────────────────────────────────
const toast = useToast()
const ctx = useContextMenu()
const CF_COPY_COLS = [
  { key: 'ym', label: '月份' },
  { key: 'collected', label: '实收', format: v => fmtWan(v) },
  { key: 'paid', label: '实付', format: v => fmtWan(v) },
  { key: 'budget_collection', label: '收款预算', format: v => fmtWan(v) },
  { key: 'budget_payment', label: '付款预算', format: v => fmtWan(v) },
  { key: 'net', label: '净现金流', format: v => fmtWan(v) },
  { key: 'cumulative_net', label: '累计净现金流', format: v => fmtWan(v) },
]
async function cfCopyField(val, label) {
  const ok = await copyText(val == null ? '' : String(val))
  ok ? toast.success(`已复制：${label}`) : toast.error('复制失败')
}
const ctxItems = computed(() => {
  const r = ctx.menu.payload
  if (!r) return []
  return [
    { key: 'copy', label: '复制', icon: 'copy', children: [
      { key: 'copy-row', label: '复制整行', icon: 'copy', shortcut: '⌘C', action: row => copyRowTSV(row, CF_COPY_COLS, { header: true }).then(ok => ok ? toast.success('已复制整行（含表头，可粘贴到 Excel）') : toast.error('复制失败')) },
      { divider: true },
      { key: 'copy-ym', label: '月份', icon: 'chart', hidden: !r.ym, action: row => cfCopyField(row.ym, row.ym) },
      { key: 'copy-net', label: '净现金流', icon: 'chart', action: row => cfCopyField(row.net, '净现金流') },
      { key: 'copy-cumulative', label: '累计净现金流', icon: 'chart', action: row => cfCopyField(row.cumulative_net, '累计净现金流') },
    ]},
  ]
})

async function load() {
  if (!filters.start_date || !filters.end_date) return
  if (filters.end_date < filters.start_date) { toast.error('结束日期不能早于起始日期'); return }
  loading.value = true
  try {
    const params = {
      start_date: filters.start_date,
      end_date: filters.end_date,
    }
    // Single dept OR all accessible depts
    if (filters.dept) {
      params.depts = filters.dept
    } else if (accessibleDepts.value.length) {
      params.depts = accessibleDepts.value.join(',')
    }
    const res = await ar.cashflow(params)
    cfData.value = res.data
  } catch (e) {
    cfData.value = null
  } finally { loading.value = false }
}

const onScopeChange = () => {
  if (filters.dept && !accessibleDepts.value.includes(filters.dept)) filters.dept = ''
  load()
}

// 部门记忆：跨会话沿用上次选的事业部；日期区间不记——过期区间比默认本月更误导
watch(() => filters.dept, d => savePref('ar_cf_dept', d))

// 导出 Excel：与页面完全同参数（区间+部门作用域），后端同口径共用 _cashflow_payload
// 图表下钻:点击月度图任一柱/点 → 月度明细表定位并高亮该月
const hiYm = ref('')
function drillYm(ym) {
  if (!ym) return
  hiYm.value = ym
  requestAnimationFrame(() => {
    document.querySelector(`[data-ym="${ym}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  })
  setTimeout(() => { if (hiYm.value === ym) hiYm.value = '' }, 2600)
}
function drillMonth(p) {
  const label = p?.name || p?.axisValueLabel
  if (!label) return
  // 呼吸图类目是「MM月」、桥图是步骤名，台账行 key 是「YYYY-MM」：按月份后缀映射
  drillYm((cfData.value?.months || []).find(m => m === label || m.slice(5) + '月' === label))
}

const exporting = ref(false)
async function exportXlsx() {
  if (exporting.value || !filters.start_date || !filters.end_date) return
  exporting.value = true
  try {
    const params = { start_date: filters.start_date, end_date: filters.end_date }
    if (filters.dept) params.depts = filters.dept
    else if (accessibleDepts.value.length) params.depts = accessibleDepts.value.join(',')
    const res = await ar.exportCashflow(params)
    downloadBlob(res, `现金流分析_${filters.start_date}_${filters.end_date}.xlsx`)
  } catch (e) { toast.error(e?.error || '导出失败，请重试') }
  finally { exporting.value = false }
}
onMounted(() => {
  // 部门记忆：须仍在当前可选范围内（权限变化后失效值静默回落「全部」）
  const dept = loadPref('ar_cf_dept')
  if (dept && accessibleDepts.value.includes(dept)) filters.dept = dept
  load()
  window.addEventListener('pk:depts-changed', onScopeChange)
})
onBeforeUnmount(() => window.removeEventListener('pk:depts-changed', onScopeChange))

// ── KPI roll-ups (reactive — recompute whenever cfData changes after load()) ────
const totals = computed(() => cfData.value?.totals)
const _sum = arr => (arr || []).reduce((a, b) => a + b, 0)
const sumColl = computed(() => _sum(totals.value?.collected))
const sumDaily = computed(() => _sum(totals.value?.daily_receipts))
const sumPaid = computed(() => _sum(totals.value?.paid))
const sumAdvRecv = computed(() => _sum(totals.value?.advance_received))
const sumAdvPaid = computed(() => _sum(totals.value?.advance_paid))
const sumInflow = computed(() => _sum(totals.value?.inflow))
const sumOutflow = computed(() => _sum(totals.value?.outflow))
const netTotal = computed(() => sumInflow.value - sumOutflow.value)
const endCumulative = computed(() => {
  const c = totals.value?.cumulative_net
  return c?.length ? c[c.length - 1] : 0
})
const sumBudgetColl = computed(() => (totals.value?.budget_collection || []).reduce((a, b) => a + b, 0))
const sumBudgetPaid = computed(() => (totals.value?.budget_payment || []).reduce((a, b) => a + b, 0))
const collAchieve = computed(() => sumBudgetColl.value ? (sumColl.value / sumBudgetColl.value * 100) : null)
const payAchieve = computed(() => sumBudgetPaid.value ? (sumPaid.value / sumBudgetPaid.value * 100) : null)

const hasAlert = computed(() => cfData.value?.has_alert)
const alertMonths = computed(() => cfData.value?.totals?.alert_months || [])

// Show per-dept comparison when "全部" is selected AND multiple depts exist
const showDeptComparison = computed(() =>
  !filters.dept && (cfData.value?.by_dept?.length || 0) > 1)

// ── 数据密度感知：稀疏（≤2 个有效月）切资金故事卡，密集走完整图表 ──────────────
// 小事业部/单月区间的时间轴大图只剩空格子——数据少讲结论，数据多讲结构。
const activeIdx = computed(() => {
  const t = totals.value
  if (!t) return []
  return activeIndices([t.collected, t.daily_receipts, t.advance_received, t.paid, t.advance_paid])
})
const density = computed(() => densityOf(activeIdx.value.length))
const forceCharts = ref(false)   // 稀疏时用户仍可手动切回图表视图

const storyData = computed(() => {
  const t = totals.value
  if (!t) return null
  const months = cfData.value.months || []
  const inflows = [
    { name: '实收回款', value: sumColl.value, color: '#2e7d32' },
    { name: '日常收款', value: sumDaily.value, color: '#4caf50' },
    { name: '预收款', value: sumAdvRecv.value, color: '#81c784' },
  ].filter(s => s.value > 0)
  const outflows = [
    { name: '实付付款', value: sumPaid.value, color: '#e65100' },
    { name: '预付款', value: sumAdvPaid.value, color: '#ffa726' },
  ].filter(s => s.value > 0)
  const rows = activeIdx.value.map(i => {
    const inflow = (t.collected?.[i] || 0) + (t.daily_receipts?.[i] || 0) + (t.advance_received?.[i] || 0)
    const outflow = (t.paid?.[i] || 0) + (t.advance_paid?.[i] || 0)
    return { ym: months[i], label: (months[i] || '').slice(5) + '月', inflow, outflow, net: inflow - outflow }
  })
  return {
    inflows, outflows, net: netTotal.value, cumulativeEnd: endCumulative.value,
    months: rows, totalMonths: months.length,
    budgetColl: sumBudgetColl.value, budgetPay: sumBudgetPaid.value,
    collAchieve: collAchieve.value, payAchieve: payAchieve.value,
  }
})

// ── Shared chart style tokens ─────────────────────────────────────────────────
const GRID  = { top: 16, right: 16, bottom: 48, left: 16, containLabel: true }
const GRIDL = { top: 16, right: 16, bottom: 28, left: 16, containLabel: true }
const AXLBL = { fontSize: 11, color: '#888' }
const SLINE = { color: 'rgba(0,0,0,0.06)' }
const OLINE = { show: false }
const TT_STYLE = { confine: true, backgroundColor: 'rgba(255,255,255,0.97)', borderColor: 'rgba(0,0,0,0.08)', textStyle: { fontSize: 12 } }

function ttFmt(params) {
  let html = `<div style="font-weight:700;margin-bottom:5px">${params[0].axisValueLabel}</div>`
  params.forEach(p => {
    const c = p.color?.colorStops ? p.color.colorStops[0].color : p.color
    html += `<div style="display:flex;gap:8px;align-items:center;margin:2px 0">
      <span style="color:${c};font-size:13px">●</span>
      <span style="flex:1;color:#555">${p.seriesName}</span>
      <b>${fmtWan(p.value)}</b></div>`
  })
  return html
}

function gradBar(c1, c2) {
  return { type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
    colorStops: [{ offset: 0, color: c1 }, { offset: 1, color: c2 }] }
}

const signWan = (v) => (v >= 0 ? '+' : '−') + fmtWan(Math.abs(v))
const mLabels = () => (cfData.value?.months || []).map(ym => ym.slice(5) + '月')

// ── 1) 现金流量桥（瀑布）：实收 + 预收 − 实付 − 预付 = 期末净现金 ────────────────
// 一眼看清整段期间「现金从哪来、到哪去、最后剩多少」——现金流分析的招牌图。
const bridgeOption = computed(() => {
  if (!cfData.value) return null
  const t = cfData.value.totals
  const inflowC = _sum(t.collected), inflowA = _sum(t.advance_received), inflowD = _sum(t.daily_receipts)
  const outflowP = _sum(t.paid), outflowA = _sum(t.advance_paid)
  // 零构成不占位：小事业部常只有实收+实付，滤掉 0 值步骤让「桥」保持阶梯感
  const steps = [
    { name: '实收回款', d: inflowC },
    { name: '日常收款', d: inflowD },
    { name: '预收款', d: inflowA },
    { name: '实付付款', d: -outflowP }, { name: '预付款', d: -outflowA },
  ].filter(s => s.d)
  if (!steps.length) return null
  const cats = steps.map(s => s.name).concat('期末净现金')
  const base = [], delta = []
  let run = 0
  for (const s of steps) {
    const start = run; run += s.d
    base.push(Math.min(start, run))
    const up = s.d >= 0
    delta.push({
      value: Math.abs(s.d), _signed: s.d,
      itemStyle: { color: up ? gradBar('#66bb6a', '#2e7d32') : gradBar('#ef5350', '#c62828'),
                   borderRadius: 4 },
    })
  }
  const total = run
  base.push(Math.min(0, total))
  delta.push({
    value: Math.abs(total), _signed: total, _anchor: true,
    itemStyle: { color: total >= 0 ? gradBar('#42a5f5', '#1565c0') : gradBar('#ef5350', '#b71c1c'),
                 borderRadius: 4 },
  })
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, ...TT_STYLE,
      formatter: ps => {
        const p = ps.find(x => x.seriesName === '净额') || ps[ps.length - 1]
        const dd = p?.data
        if (!dd) return ''
        const lbl = dd._anchor ? '期末净现金' : (dd._signed >= 0 ? '现金流入' : '现金流出')
        return `<b>${p.axisValueLabel}</b><br/>${lbl}：<b>${dd._anchor ? signWan(dd._signed) : signWan(dd._signed)}</b>`
      } },
    grid: { ...GRID, bottom: 28 },
    xAxis: { type: 'category', data: cats, axisLine: { lineStyle: SLINE }, axisTick: OLINE,
             axisLabel: { ...AXLBL, interval: 0 } },
    yAxis: { type: 'value', axisLabel: { formatter: v => fmtWan(v), ...AXLBL }, splitLine: { lineStyle: SLINE } },
    series: [
      { name: '_base', type: 'bar', stack: 'wf', barMaxWidth: 48, silent: true,
        itemStyle: { color: 'transparent' }, emphasis: { itemStyle: { color: 'transparent' } }, data: base },
      { name: '净额', type: 'bar', stack: 'wf', barMaxWidth: 48, data: delta,
        label: { show: true, position: 'top', fontSize: 11, fontWeight: 700, color: '#5f4d3d',
          formatter: p => (p.data._anchor ? '' : (p.data._signed >= 0 ? '+' : '−')) + fmtWan(Math.abs(p.data._signed)) },
        labelLayout: HIDE_OVERLAP },
    ],
  }
})

// ── 2) 现金呼吸图：流入↑ / 流出↓ 镜像 + 净额线 + 预算参考 + 缺口预警带 ───────────
// 把「收付对比 + 净现金流」合为一张会呼吸的图：上方吸入、下方呼出、蓝线即净额。
const breathOption = computed(() => {
  if (!cfData.value) return null
  const t = cfData.value.totals
  const lbls = mLabels()
  const neg = arr => (arr || []).map(v => -v)
  const alertSet = new Set(t.alert_months || [])
  const alertBands = (cfData.value.months || [])
    .map((ym, i) => (alertSet.has(ym) ? lbls[i] : null)).filter(Boolean)
    .map(l => [{ xAxis: l, itemStyle: { color: 'rgba(198,40,40,0.08)' } }, { xAxis: l }])
  // 系列按「有数据才进图」动态组装：小事业部常没有预收/预付/日常收款，
  // 全零系列不画柱也不占图例——图例只剩真实发生的构成
  const series = []
  if (_sum(t.collected)) series.push({ name: '实收', type: 'bar', stack: 'in', barMaxWidth: 26, data: t.collected,
    itemStyle: { color: gradBar('#81c784', '#2e7d32') } })
  if (_sum(t.daily_receipts)) series.push({ name: '日常收款', type: 'bar', stack: 'in', barMaxWidth: 26, data: t.daily_receipts,
    itemStyle: { color: gradBar('#a5d6a7', '#66bb6a') } })
  if (_sum(t.advance_received)) series.push({ name: '预收', type: 'bar', stack: 'in', barMaxWidth: 26, data: t.advance_received,
    itemStyle: { color: gradBar('#c8e6c9', '#81c784'), borderRadius: [4, 4, 0, 0] } })
  if (_sum(t.paid)) series.push({ name: '实付', type: 'bar', stack: 'out', barMaxWidth: 26, data: neg(t.paid),
    itemStyle: { color: gradBar('#e65100', '#ffa726') } })
  if (_sum(t.advance_paid)) series.push({ name: '预付', type: 'bar', stack: 'out', barMaxWidth: 26, data: neg(t.advance_paid),
    itemStyle: { color: gradBar('#ffa726', '#ffe0b2'), borderRadius: [0, 0, 4, 4] } })
  if (alertBands.length && series.length) series[0].markArea = { silent: true, data: alertBands }
  const netSeries = { name: '净现金流', type: 'line', smooth: true, z: 10, data: t.net,
    symbol: 'circle', symbolSize: 7, lineStyle: { color: '#1565c0', width: 3 },
    itemStyle: { color: '#fff', borderColor: '#1565c0', borderWidth: 2.5 },
    label: { show: true, position: 'top', fontSize: 10.5, fontWeight: 700, color: '#1565c0',
             textBorderColor: '#fff', textBorderWidth: 3, formatter: p => signWan(p.value) },
    labelLayout: HIDE_OVERLAP,
    markLine: { silent: true, symbol: 'none', lineStyle: { color: 'rgba(0,0,0,0.25)' }, data: [{ yAxis: 0 }] } }
  if (alertBands.length && !series.length) netSeries.markArea = { silent: true, data: alertBands }
  series.push(netSeries)
  if (_sum(t.budget_collection)) series.push({ name: '收款预算', type: 'line', smooth: true, data: t.budget_collection, symbol: 'none',
    lineStyle: { type: 'dashed', color: '#2e7d32', width: 1.5, opacity: 0.6 } })
  if (_sum(t.budget_payment)) series.push({ name: '付款预算', type: 'line', smooth: true, data: neg(t.budget_payment), symbol: 'none',
    lineStyle: { type: 'dashed', color: '#e65100', width: 1.5, opacity: 0.6 } })
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, ...TT_STYLE,
      formatter: ps => {
        let h = `<div style="font-weight:700;margin-bottom:5px">${ps[0].axisValueLabel}</div>`
        ps.forEach(p => {
          if (p.value == null || p.value === '-') return
          const isNet = p.seriesName === '净现金流'
          const c = p.color?.colorStops ? p.color.colorStops[0].color : p.color
          const val = isNet ? signWan(p.value) : fmtWan(Math.abs(p.value))
          h += `<div style="display:flex;gap:8px;align-items:center;margin:2px 0"><span style="color:${c}">●</span><span style="flex:1;color:#555">${p.seriesName}</span><b>${val}</b></div>`
        })
        return h
      } },
    legend: { bottom: 4, icon: 'roundRect', itemWidth: 14, itemHeight: 8, textStyle: { fontSize: 11, color: '#555' },
              data: series.map(s => s.name) },
    grid: GRID,
    xAxis: { type: 'category', data: lbls, axisLine: { lineStyle: SLINE }, axisTick: OLINE, axisLabel: AXLBL },
    yAxis: { type: 'value', axisLabel: { formatter: v => fmtWan(Math.abs(v)), ...AXLBL }, splitLine: { lineStyle: SLINE } },
    series,
  }
})

// ── 3) 现金跑道与谷底：累计资金池 + 危险区(<0 转红) + 谷底/峰值标注 + 生死线 ──────
const runwayOption = computed(() => {
  if (!cfData.value) return null
  const t = cfData.value.totals
  const lbls = mLabels()
  const data = t.cumulative_net || []
  const hasNeg = data.some(v => v < 0)
  // 水下段（<0）单独红线高亮：危险区一眼可见，且规避 visualMap 在类目轴上的兼容问题
  const danger = data.map(v => (v < 0 ? v : null))
  return {
    tooltip: { trigger: 'axis', ...TT_STYLE,
      formatter: p => `<b>${p[0].axisValueLabel}</b><br/>累计净现金流：<b>${signWan(p[0].value)}</b>` },
    grid: { ...GRIDL, top: 28 },
    xAxis: { type: 'category', boundaryGap: false, data: lbls,
             axisLine: { lineStyle: SLINE }, axisTick: OLINE, axisLabel: AXLBL },
    yAxis: { type: 'value', axisLabel: { formatter: v => fmtWan(v), ...AXLBL }, splitLine: { lineStyle: SLINE } },
    series: [
      { name: '累计净现金流', type: 'line', smooth: true, data, symbol: 'circle', symbolSize: 6,
        lineStyle: { width: 3, color: '#1565c0' }, itemStyle: { color: '#1565c0' },
        label: { show: true, position: 'top', fontSize: 10, fontWeight: 700, color: '#1565c0',
                 textBorderColor: '#fff', textBorderWidth: 3, formatter: p => fmtWan(p.value) },
        labelLayout: HIDE_OVERLAP,
        areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [
          { offset: 0, color: 'rgba(21,101,192,0.30)' },
          { offset: 0.72, color: 'rgba(21,101,192,0.03)' },
          { offset: 0.86, color: 'rgba(198,40,40,0.10)' },
          { offset: 1, color: 'rgba(198,40,40,0.30)' }] } },
        markLine: { silent: true, symbol: 'none',
          lineStyle: { color: 'rgba(120,30,30,0.5)', type: 'dashed', width: 1.5 },
          label: { formatter: '资金平衡线（0）', color: '#c62828', fontSize: 10, position: 'insideEndTop' },
          data: [{ yAxis: 0 }] },
        markPoint: {
          symbolSize: 52, symbol: 'pin',
          label: { fontSize: 10, fontWeight: 700, color: '#fff', formatter: p => fmtWan(p.value) },
          data: [
            { type: 'min', name: '现金谷底', itemStyle: { color: hasNeg ? '#c62828' : '#e65100' } },
            { type: 'max', name: '资金峰值', itemStyle: { color: '#2e7d32' } },
          ],
        } },
      { name: '水下(<0)', type: 'line', smooth: true, data: danger, symbol: 'none', z: 5,
        connectNulls: false, lineStyle: { width: 4, color: '#c62828' },
        areaStyle: { color: 'rgba(198,40,40,0.16)' } },
    ],
  }
})

// ── 4) 事业部现金收支平衡气泡：X=流入 Y=流出，45°平衡线上方=失血 下方=造血 ─────────
const deptBalanceOption = computed(() => {
  if (!showDeptComparison.value) return null
  const rows = cfData.value.by_dept.map(d => {
    const inflow = _sum(d.collected) + _sum(d.daily_receipts) + _sum(d.advance_received)
    const outflow = _sum(d.paid) + _sum(d.advance_paid)
    return { dept: d.dept, inflow, outflow, net: inflow - outflow }
  }).filter(r => r.inflow > 0 || r.outflow > 0)
  if (!rows.length) return null
  const maxNet = Math.max(...rows.map(r => Math.abs(r.net)), 1)
  const lim = Math.max(...rows.map(r => Math.max(r.inflow, r.outflow)), 1) * 1.08
  return {
    tooltip: { ...TT_STYLE, formatter: p => {
      const [inf, outf, , dept, net] = p.value
      return `<b>${dept}</b><br/>流入：${fmtWan(inf)}<br/>流出：${fmtWan(outf)}<br/>净现金：<b style="color:${net >= 0 ? '#2e7d32' : '#c62828'}">${signWan(net)}</b>`
    } },
    grid: { top: 24, right: 26, bottom: 44, left: 16, containLabel: true },
    xAxis: { type: 'value', name: '现金流入', nameLocation: 'middle', nameGap: 28, max: lim,
             nameTextStyle: { color: '#9b8070', fontSize: 11 },
             axisLabel: { formatter: v => fmtWan(v), ...AXLBL }, splitLine: { lineStyle: SLINE } },
    yAxis: { type: 'value', name: '现金流出', max: lim, nameTextStyle: { color: '#9b8070', fontSize: 11 },
             axisLabel: { formatter: v => fmtWan(v), ...AXLBL }, splitLine: { lineStyle: SLINE } },
    series: [
      { name: '平衡线', type: 'line', data: [[0, 0], [lim, lim]], symbol: 'none', silent: true,
        lineStyle: { color: 'rgba(120,90,70,.5)', type: 'dashed' },
        endLabel: { show: true, formatter: '收支平衡线', color: '#9b8070', fontSize: 10 } },
      { name: '事业部', type: 'scatter',
        symbolSize: r => 16 + (Math.abs(r[4]) / maxNet) * 40,
        data: rows.map(r => ({ value: [r.inflow, r.outflow, Math.abs(r.net), r.dept, r.net],
          itemStyle: { color: r.net >= 0 ? 'rgba(46,125,50,0.78)' : 'rgba(198,40,40,0.78)',
                       borderColor: '#fff', borderWidth: 1.5 } })),
        label: { show: true, formatter: p => p.value[3], position: 'right', fontSize: 11, color: '#5f4d3d' },
        labelLayout: HIDE_OVERLAP },
    ],
  }
})

// ── 5) 桑基资金流向：谁在供血 → 资金池 → 钱花去哪（实付/预付）───────────────────
// 多事业部：左侧按事业部供血；单事业部/指定部门：左侧按流入构成（实收/日常/预收）。
// 净流入时右侧多一条「净留存」蓝流；净流出时左侧多一条「消耗存量」红流补平。
const GREENS = ['#2e7d32', '#43a047', '#66bb6a', '#81c784', '#a5d6a7', '#8bc34a']
const sankeyOption = computed(() => {
  if (!cfData.value || density.value !== 'dense') return null
  const sources = showDeptComparison.value
    ? cfData.value.by_dept
        .map(d => ({ name: d.dept, value: _sum(d.collected) + _sum(d.daily_receipts) + _sum(d.advance_received) }))
        .filter(r => r.value > 0)
        .sort((a, b) => b.value - a.value)
    : [
        { name: '实收回款', value: sumColl.value },
        { name: '日常收款', value: sumDaily.value },
        { name: '预收款', value: sumAdvRecv.value },
      ].filter(r => r.value > 0)
  if (!sources.length) return null
  const nodes = [], links = []
  sources.forEach((r, i) => {
    nodes.push({ name: r.name, itemStyle: { color: GREENS[i % GREENS.length] } })
    links.push({ source: r.name, target: '资金池', value: r.value })
  })
  if (netTotal.value < 0) {
    nodes.push({ name: '消耗存量', itemStyle: { color: '#c62828' } })
    links.push({ source: '消耗存量', target: '资金池', value: -netTotal.value })
  }
  nodes.push({ name: '资金池', itemStyle: { color: '#8d6e63' } })
  if (sumPaid.value > 0) {
    nodes.push({ name: '实付付款', itemStyle: { color: '#e65100' } })
    links.push({ source: '资金池', target: '实付付款', value: sumPaid.value })
  }
  if (sumAdvPaid.value > 0) {
    nodes.push({ name: '预付款', itemStyle: { color: '#ffa726' } })
    links.push({ source: '资金池', target: '预付款', value: sumAdvPaid.value })
  }
  if (netTotal.value > 0) {
    nodes.push({ name: '净留存', itemStyle: { color: '#1565c0' } })
    links.push({ source: '资金池', target: '净留存', value: netTotal.value })
  }
  if (links.length <= 1) return null   // 只有一条流时桑基无意义
  return {
    tooltip: { ...TT_STYLE,
      formatter: p => p.dataType === 'edge'
        ? `${p.data.source} → ${p.data.target}<br/><b>${fmtWan(p.value)}</b>`
        : `${p.name}<br/><b>${fmtWan(p.value)}</b>` },
    series: [{
      type: 'sankey', left: 14, right: 96, top: 14, bottom: 14,
      nodeWidth: 14, nodeGap: 12, data: nodes, links,
      label: { fontSize: 11.5, color: '#5f4d3d', formatter: p => `${p.name}  ${fmtWan(p.value)}` },
      lineStyle: { color: 'gradient', opacity: 0.32, curveness: 0.5 },
      itemStyle: { borderRadius: 3 },
      emphasis: { focus: 'adjacency' },
    }],
  }
})
</script>

<template>
  <div>
    <div v-if="!embedded" class="topbar">
      <div>
        <h1>现金流分析<span v-if="hasAlert" class="cf-title-alert">⚠ 现金流预警：部分月份资金流出大于流入</span></h1>
        <div style="font-size:13px;color:var(--muted);margin-top:2px">财务驾驶舱 · 预算达成 · 净现金流 · 累计走势</div>
      </div>
    </div>
    <div v-else-if="hasAlert" class="cf-embed-alert">⚠ 现金流预警：部分月份资金流出大于流入</div>

    <!-- Polished filter bar: dept | date range on one line -->
    <div class="cf-filterbar">
      <!-- Dept group -->
      <div class="cfb-group">
        <svg class="cfb-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>
        <span class="cfb-lbl">事业部</span>
        <select v-model="filters.dept" class="cfb-sel cfb-dept" @change="load">
          <option value="">全部事业部</option>
          <option v-for="d in accessibleDepts" :key="d" :value="d">{{ d }}</option>
        </select>
      </div>
      <div class="cfb-div"></div>
      <!-- Date range group — 预设区间条 + 自定义(day precision) -->
      <div class="cfb-group cfb-group-grow">
        <DateRangeChips v-model:start="filters.start_date" v-model:end="filters.end_date"
                        label="区间" initial="thismonth"
                        :presets="['thismonth', 'lastmonth', 'thisquarter', 'lastquarter', 'halfyear', 'thisyear', 'lastyear', 'year1']"
                        @change="load" />
      </div>
      <div v-if="loading" class="cfb-loading">
        <span class="cfb-spin">↻</span> 加载中
      </div>
      <button class="btn btn-ghost btn-sm" :disabled="exporting || loading" @click="exportXlsx"
              title="导出当前区间与部门范围的月度现金流与分部门明细">
        {{ exporting ? '导出中…' : '导出' }}
      </button>
    </div>

    <!-- KPI cards: 三组（收款 / 付款 / 现金流），每组 预算 → 预收/预付 → 实收/实付 -->
    <div class="cf-kpi-groups">
      <!-- 收款组 -->
      <section class="kpi-group kg-coll">
        <div class="kpi-group-head kgh-coll">收款</div>
        <div class="kpi-group-cards">
          <div class="ck-card ck-coll-soft">
            <div class="ck-label">收款预算</div>
            <div class="ck-value"><Amt :v="sumBudgetColl" :fmt="fmtWan" /></div>
            <div class="ck-sub">收款目标</div>
          </div>
          <div class="ck-card ck-coll-soft">
            <div class="ck-label">预收</div>
            <div class="ck-value"><Amt :v="sumAdvRecv" :fmt="fmtWan" /></div>
            <div class="ck-sub">客户预付款</div>
          </div>
          <div v-if="sumDaily" class="ck-card ck-coll-soft">
            <div class="ck-label">日常收款</div>
            <div class="ck-value"><Amt :v="sumDaily" :fmt="fmtWan" /></div>
            <div class="ck-sub">项目收款/退款等</div>
          </div>
          <div class="ck-card ck-coll">
            <div class="ck-label">实收</div>
            <div class="ck-value"><Amt :v="sumColl" :fmt="fmtWan" /></div>
            <div class="ck-sub" v-if="collAchieve !== null">
              <span :class="collAchieve >= 100 ? 'ach-ok' : 'ach-off'">达成 {{ collAchieve.toFixed(1) }}%</span>
            </div>
            <div class="ck-sub ach-off" v-else>无预算基准</div>
          </div>
        </div>
      </section>
      <!-- 付款组 -->
      <section class="kpi-group kg-pay">
        <div class="kpi-group-head kgh-pay">付款</div>
        <div class="kpi-group-cards">
          <div class="ck-card ck-pay-soft">
            <div class="ck-label">付款预算</div>
            <div class="ck-value"><Amt :v="sumBudgetPaid" :fmt="fmtWan" /></div>
            <div class="ck-sub">付款目标</div>
          </div>
          <div class="ck-card ck-pay-soft">
            <div class="ck-label">预付</div>
            <div class="ck-value"><Amt :v="sumAdvPaid" :fmt="fmtWan" /></div>
            <div class="ck-sub">供应商预付款</div>
          </div>
          <div class="ck-card ck-pay">
            <div class="ck-label">实付</div>
            <div class="ck-value"><Amt :v="sumPaid" :fmt="fmtWan" /></div>
            <div class="ck-sub" v-if="payAchieve !== null">
              <span :class="payAchieve >= 100 ? 'ach-ok' : 'ach-off'">达成 {{ payAchieve.toFixed(1) }}%</span>
            </div>
            <div class="ck-sub ach-off" v-else>无预算基准</div>
          </div>
        </div>
      </section>
      <!-- 现金流组 -->
      <section class="kpi-group kg-cash">
        <div class="kpi-group-head kgh-cash">现金流</div>
        <div class="kpi-group-cards">
          <div class="ck-card" :class="netTotal >= 0 ? 'ck-net-pos' : 'ck-net-neg'">
            <div class="ck-label">净现金流</div>
            <div class="ck-value" :class="netTotal >= 0 ? 'v-pos' : 'v-neg'">
              {{ netTotal >= 0 ? '+' : '' }}<Amt :v="netTotal" :fmt="fmtWan" />
            </div>
            <div class="ck-sub">流入 − 流出</div>
          </div>
          <div class="ck-card" :class="endCumulative >= 0 ? 'ck-net-pos' : 'ck-net-neg'">
            <div class="ck-label">期末累计</div>
            <div class="ck-value" :class="endCumulative >= 0 ? 'v-pos' : 'v-neg'">
              {{ endCumulative >= 0 ? '+' : '' }}<Amt :v="endCumulative" :fmt="fmtWan" />
            </div>
            <div class="ck-sub">累计净现金流期末值</div>
          </div>
        </div>
      </section>
    </div>

    <!-- Chart grid (creative cash-flow viz suite) -->
    <div class="cockpit-grid">
      <!-- ── 稀疏模式：资金故事卡——数据少讲结论，数据多讲结构 ─────────────── -->
      <template v-if="density === 'sparse' && storyData && !forceCharts">
        <div class="card span2">
          <div class="section-title">资金故事
            <span class="section-sub">当前区间月份较少，先呈现结论摘要；月份增多后展示完整图表</span>
            <button class="cs-viewswitch" @click="forceCharts = true">仍看图表 ›</button>
          </div>
          <CashStory v-bind="storyData" @month-click="drillYm" />
        </div>
      </template>

      <template v-else>
      <!-- 招牌图：现金流量桥 -->
      <div class="card span2">
        <div class="section-title">现金流量桥
          <span class="section-sub">实收 + 预收 − 实付 − 预付 = 期末净现金</span>
          <button v-if="density === 'sparse'" class="cs-viewswitch" @click="forceCharts = false">‹ 返回故事视图</button>
        </div>
        <BaseChart v-if="bridgeOption" :option="bridgeOption" height="300px" @click="drillMonth" />
        <div v-else class="chart-empty">{{ loading ? '加载中…' : '暂无数据' }}</div>
      </div>

      <!-- 现金呼吸图（流入↑/流出↓ + 净额线）-->
      <div class="card span2">
        <div class="section-title">现金呼吸图
          <span class="section-sub">上方流入 · 下方流出 · 蓝线为月净额 · 红带=当月入不敷出</span>
        </div>
        <BaseChart v-if="breathOption" :option="breathOption" height="340px" @click="drillMonth" />
        <div v-else class="chart-empty">{{ loading ? '加载中…' : '暂无数据' }}</div>
      </div>

      <!-- 现金跑道与谷底 -->
      <div class="card span2">
        <div class="section-title">现金跑道与谷底
          <span class="section-sub">累计净现金流 · 跌破 0 转红 · 标注现金谷底与资金峰值</span>
        </div>
        <BaseChart v-if="runwayOption" :option="runwayOption" height="280px" />
        <div v-else class="chart-empty">{{ loading ? '加载中…' : '暂无数据' }}</div>
      </div>

      <!-- 桑基资金流向：谁在供血 → 资金池 → 钱花去哪（数据密集时） -->
      <div v-if="sankeyOption" class="card span2">
        <div class="section-title">资金流向
          <span class="section-sub">左＝资金来源（{{ showDeptComparison ? '各事业部流入' : '流入构成' }}）· 右＝资金去向 · 蓝＝净留存 / 红＝动用存量资金</span>
        </div>
        <BaseChart :option="sankeyOption" height="320px" />
      </div>
      </template>
    </div>

    <!-- 事业部现金收支平衡气泡 (multi-dept) -->
    <div v-if="showDeptComparison" class="card" style="margin-top:16px">
      <div class="section-title">事业部现金收支平衡
        <span class="section-sub">X=流入　Y=流出　气泡=净现金额　虚线上方=失血 / 下方=造血 · {{ filters.start_date }} 至 {{ filters.end_date }}</span>
      </div>
      <BaseChart v-if="deptBalanceOption" :option="deptBalanceOption" height="380px" />
      <div v-else class="chart-empty">{{ loading ? '加载中…' : '暂无数据' }}</div>
    </div>

    <!-- Monthly detail table -->
    <div v-if="cfData?.months?.length" class="card" style="margin-top:16px">
      <div class="section-title">月度明细</div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>月份</th>
              <th class="amt">实收</th>
              <th class="amt">实付</th>
              <th class="amt muted">收款预算</th>
              <th class="amt muted">付款预算</th>
              <th class="amt">净现金流</th>
              <th class="amt">累计净现金流</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(ym, i) in cfData.months" :key="ym" :data-ym="ym"
                :class="{ 'row-alert': cfData.totals.outflow[i] > cfData.totals.inflow[i] && cfData.totals.inflow[i] > 0, 'row-drill': hiYm === ym }"
                @contextmenu.prevent="ctx.open($event, { ym, collected: cfData.totals.collected[i], paid: cfData.totals.paid[i], budget_collection: cfData.totals.budget_collection[i], budget_payment: cfData.totals.budget_payment[i], net: cfData.totals.net[i], cumulative_net: cfData.totals.cumulative_net[i] })">
              <td class="fw">{{ ym }}</td>
              <td class="amt text-coll">{{ fmtWan(cfData.totals.collected[i]) }}</td>
              <td class="amt" :class="cfData.totals.outflow[i] > cfData.totals.inflow[i] ? 'text-danger' : 'text-pay'">
                {{ fmtWan(cfData.totals.paid[i]) }}
              </td>
              <td class="amt muted">{{ fmtWan(cfData.totals.budget_collection[i]) }}</td>
              <td class="amt muted">{{ fmtWan(cfData.totals.budget_payment[i]) }}</td>
              <td class="amt" :class="cfData.totals.net[i] >= 0 ? 'text-ok' : 'text-danger'">
                {{ cfData.totals.net[i] >= 0 ? '+' : '' }}{{ fmtWan(cfData.totals.net[i]) }}
              </td>
              <td class="amt" :class="cfData.totals.cumulative_net[i] >= 0 ? 'text-ok' : 'text-danger'">
                {{ cfData.totals.cumulative_net[i] >= 0 ? '+' : '' }}{{ fmtWan(cfData.totals.cumulative_net[i]) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
    <ContextMenu :ctx="ctx" :items="ctxItems" />
  </div>
</template>

<style scoped>
/* 故事视图 ↔ 图表视图 切换（稀疏数据时） */
.cs-viewswitch {
  float: right; border: 1px solid rgba(150,120,100,0.3); background: none;
  border-radius: 8px; padding: 3px 10px; font-size: 11.5px; color: var(--muted);
  cursor: pointer; transition: color .15s, border-color .15s;
}
.cs-viewswitch:hover { color: var(--primary); border-color: var(--primary); }

/* ── 筛选条（玻璃态，对齐系统设计令牌）── */
.cf-filterbar {
  display: flex; align-items: center;
  background: var(--surface-1); border: 1px solid var(--glass-border);
  border-radius: var(--radius); padding: 5px 12px;
  box-shadow: var(--shadow-sm);
  margin-bottom: 18px; backdrop-filter: var(--blur); -webkit-backdrop-filter: var(--blur);
  flex-wrap: nowrap; overflow-x: auto;
}
.cfb-group { display: flex; align-items: center; gap: 7px; padding: 5px 10px; }
.cfb-group-grow { flex: 1; min-width: 0; }
.cfb-icon  { color: var(--muted); flex-shrink: 0; }
.cfb-lbl   { font-size: 11.5px; font-weight: 600; color: var(--muted); white-space: nowrap; }
.cfb-div   { width: 1px; height: 24px; background: var(--border); margin: 0 4px; flex-shrink: 0; }
.cfb-sel, .cfb-date {
  height: 30px; padding: 0 10px; border: 1px solid transparent;
  background-color: var(--surface-tint); border-radius: var(--radius-xs);
  font-size: 12.5px; color: var(--text); cursor: pointer; outline: none;
  transition: background .15s, color .15s, border-color .15s, box-shadow .15s;
}
.cfb-sel { padding-right: 28px; }   /* 给全局自定义 caret 留位 */
.cfb-sel:hover, .cfb-sel:focus, .cfb-date:hover, .cfb-date:focus {
  background-color: color-mix(in srgb, var(--primary) 9%, transparent);
  color: var(--primary); border-color: var(--border-strong);
}
.cfb-sel:focus, .cfb-date:focus { box-shadow: 0 0 0 3px var(--primary-glow); }
.cfb-dept { min-width: 110px; }
.cfb-date { width: 138px; font-variant-numeric: tabular-nums; }
.cfb-to   { font-size: 12px; color: var(--muted); }
.cfb-loading { margin-left: auto; padding-left: 12px; font-size: 12px; color: var(--primary); display: flex; align-items: center; gap: 5px; white-space: nowrap; }
.cfb-spin { display: inline-block; animation: cfSpin 0.9s linear infinite; }
@keyframes cfSpin { to { transform: rotate(360deg); } }

/* ── 标题内联预警 ── */
.cf-title-alert { font-size: 13px; font-weight: 700; color: var(--c-danger); margin-left: 14px; vertical-align: middle; }
.cf-embed-alert {
  font-size: 13px; font-weight: 700; color: var(--c-danger);
  background: var(--c-danger-bg); border: 1px solid var(--c-danger-bdr);
  border-radius: var(--radius-sm); padding: 8px 14px; margin-bottom: 14px;
}

/* ── KPI 卡：三组一排（收款 / 付款 / 现金流）── */
.cf-kpi-groups { display: flex; gap: 16px; margin-bottom: 16px; align-items: stretch; }
.kpi-group { display: flex; flex-direction: column; gap: 8px; min-width: 0; }
.kg-coll, .kg-pay { flex: 3; }   /* 各 3 张卡 */
.kg-cash { flex: 2; }            /* 2 张卡 */
.kpi-group-head {
  font-size: 12px; font-weight: 800; letter-spacing: .1em;
  padding-left: 9px; border-left: 3px solid; line-height: 1.1;
}
.kgh-coll { color: var(--c-success); border-color: var(--c-success); }
.kgh-pay  { color: var(--c-warn);    border-color: var(--c-warn); }
.kgh-cash { color: var(--c-info);    border-color: var(--c-info); }
.kpi-group-cards { display: flex; gap: 10px; min-width: 0; }
.kpi-group-cards .ck-card { flex: 1; min-width: 0; }

.ck-card {
  position: relative; overflow: hidden;
  background: var(--surface-1); border: 1px solid var(--glass-border); border-radius: var(--radius);
  padding: 12px 14px; box-shadow: var(--shadow-sm); border-left: 3px solid var(--border);
  transition: box-shadow .18s, transform .18s;
}
.ck-card:hover { box-shadow: var(--shadow-md); transform: translateY(-1px); }
/* 主卡（实收 / 实付 / 净额）淡色铺底，与辅助卡拉开层级 */
.ck-coll      { border-left-color: var(--c-success); background: linear-gradient(180deg, var(--c-success-bg), var(--surface-1) 58%); }
.ck-coll-soft { border-left-color: color-mix(in srgb, var(--c-success) 40%, transparent); }
.ck-pay       { border-left-color: var(--c-warn); background: linear-gradient(180deg, var(--c-warn-bg), var(--surface-1) 58%); }
.ck-pay-soft  { border-left-color: color-mix(in srgb, var(--c-warn) 40%, transparent); }
.ck-net-pos   { border-left-color: var(--c-success); background: linear-gradient(180deg, var(--c-success-bg), var(--surface-1) 58%); }
.ck-net-neg   { border-left-color: var(--c-danger); background: linear-gradient(180deg, var(--c-danger-bg), var(--surface-1) 52%); }
.ck-label    { font-size: 10.5px; color: var(--muted); font-weight: 700; letter-spacing: .03em; white-space: nowrap; }
.ck-value    { font-size: 20px; font-weight: 800; color: var(--text); line-height: 1.2; margin: 5px 0 3px; white-space: nowrap; font-variant-numeric: tabular-nums; }
.v-pos       { color: var(--c-success) !important; }
.v-neg       { color: var(--c-danger) !important; }
.ck-sub      { font-size: 11px; white-space: nowrap; }
.ach-ok      { color: var(--c-success); font-weight: 600; }
.ach-off     { color: var(--muted); }

/* 窄屏：三组换行堆叠，组内卡片仍并排；超窄时卡片再换行 */
@media (max-width: 1100px) {
  .cf-kpi-groups { flex-wrap: wrap; }
  .kpi-group { flex: 1 1 100%; }
}
@media (max-width: 560px) {
  .kpi-group-cards { flex-wrap: wrap; }
  .kpi-group-cards .ck-card { flex: 1 1 calc(50% - 5px); }
}

/* ── 图表网格 ── */
.cockpit-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.cockpit-grid .span2 { grid-column: span 2; }
@media (max-width: 900px) { .cockpit-grid { grid-template-columns: 1fr; } .cockpit-grid .span2 { grid-column: 1; } }
.chart-empty { height: 120px; display: flex; align-items: center; justify-content: center; color: var(--muted); font-size: 13px; }

/* ── 区块小标题副标签 ── */
.section-sub { font-size: 11px; color: var(--muted); font-weight: 400; margin-left: 8px; }

/* ── 表格 ── */
.row-alert { background: var(--c-danger-bg); }
.fw { font-weight: 600; }
.amt { text-align: right; }
.muted { color: var(--muted); }
.text-coll   { color: var(--c-success); font-weight: 600; }
.text-pay    { color: var(--c-warn); }
.text-danger { color: var(--c-danger); font-weight: 600; }
.text-ok     { color: var(--c-success); font-weight: 600; }
.row-drill { background: rgba(201,99,66,.14) !important; transition: background .4s; }
</style>
