<script setup>
import { ref, computed, reactive, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../../stores/auth.js'
import { DEPARTMENTS, yearCST, monthCST } from '../../constants.js'
import ar from '../../api/ar.js'
import ContextMenu from '../../components/ContextMenu.vue'
import { useContextMenu } from '../../composables/useContextMenu.js'
import { useToast } from '../../composables/useToast.js'
import { copyText, copyRowTSV } from '../../utils/clipboard.js'
import { fmtCompact } from '../../utils/format.js'
import { HIDE_OVERLAP } from '../../utils/chartTheme.js'
import BaseChart from '../../components/ar/BaseChart.vue'

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
  if (filters.end_date < filters.start_date) { alert('结束日期不能早于起始日期'); return }
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
onMounted(() => { load(); window.addEventListener('pk:depts-changed', onScopeChange) })
onBeforeUnmount(() => window.removeEventListener('pk:depts-changed', onScopeChange))

// ── KPI roll-ups (reactive — recompute whenever cfData changes after load()) ────
const totals = computed(() => cfData.value?.totals)
const _sum = arr => (arr || []).reduce((a, b) => a + b, 0)
const sumColl = computed(() => _sum(totals.value?.collected))
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

// ── Shared chart style tokens ─────────────────────────────────────────────────
const GRID  = { top: 16, right: 16, bottom: 48, left: 16, containLabel: true }
const GRIDL = { top: 16, right: 16, bottom: 28, left: 16, containLabel: true }
const AXLBL = { fontSize: 11, color: '#888' }
const SLINE = { color: 'rgba(0,0,0,0.06)' }
const OLINE = { show: false }
const TT_STYLE = { backgroundColor: 'rgba(255,255,255,0.97)', borderColor: 'rgba(0,0,0,0.08)', textStyle: { fontSize: 12 } }

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
  const inflowC = _sum(t.collected), inflowA = _sum(t.advance_received)
  const outflowP = _sum(t.paid), outflowA = _sum(t.advance_paid)
  const steps = [
    { name: '实收回款', d: inflowC }, { name: '预收款', d: inflowA },
    { name: '实付付款', d: -outflowP }, { name: '预付款', d: -outflowA },
  ]
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
              data: ['实收', '预收', '实付', '预付', '净现金流', '收款预算', '付款预算'] },
    grid: GRID,
    xAxis: { type: 'category', data: lbls, axisLine: { lineStyle: SLINE }, axisTick: OLINE, axisLabel: AXLBL },
    yAxis: { type: 'value', axisLabel: { formatter: v => fmtWan(Math.abs(v)), ...AXLBL }, splitLine: { lineStyle: SLINE } },
    series: [
      { name: '实收', type: 'bar', stack: 'in', barMaxWidth: 26, data: t.collected,
        itemStyle: { color: gradBar('#81c784', '#2e7d32') },
        markArea: alertBands.length ? { silent: true, data: alertBands } : undefined },
      { name: '预收', type: 'bar', stack: 'in', barMaxWidth: 26, data: t.advance_received || [],
        itemStyle: { color: gradBar('#c8e6c9', '#81c784'), borderRadius: [4, 4, 0, 0] } },
      { name: '实付', type: 'bar', stack: 'out', barMaxWidth: 26, data: neg(t.paid),
        itemStyle: { color: gradBar('#e65100', '#ffa726') } },
      { name: '预付', type: 'bar', stack: 'out', barMaxWidth: 26, data: neg(t.advance_paid),
        itemStyle: { color: gradBar('#ffa726', '#ffe0b2'), borderRadius: [0, 0, 4, 4] } },
      { name: '净现金流', type: 'line', smooth: true, z: 10, data: t.net,
        symbol: 'circle', symbolSize: 7, lineStyle: { color: '#1565c0', width: 3 },
        itemStyle: { color: '#fff', borderColor: '#1565c0', borderWidth: 2.5 },
        label: { show: true, position: 'top', fontSize: 10.5, fontWeight: 700, color: '#1565c0',
                 textBorderColor: '#fff', textBorderWidth: 3, formatter: p => signWan(p.value) },
        labelLayout: HIDE_OVERLAP,
        markLine: { silent: true, symbol: 'none', lineStyle: { color: 'rgba(0,0,0,0.25)' }, data: [{ yAxis: 0 }] } },
      { name: '收款预算', type: 'line', smooth: true, data: t.budget_collection, symbol: 'none',
        lineStyle: { type: 'dashed', color: '#2e7d32', width: 1.5, opacity: 0.6 } },
      { name: '付款预算', type: 'line', smooth: true, data: neg(t.budget_payment), symbol: 'none',
        lineStyle: { type: 'dashed', color: '#e65100', width: 1.5, opacity: 0.6 } },
    ],
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
      formatter: p => `<b>${p[0].axisValueLabel}</b><br/>累计资金池：<b>${signWan(p[0].value)}</b>` },
    grid: { ...GRIDL, top: 28 },
    xAxis: { type: 'category', boundaryGap: false, data: lbls,
             axisLine: { lineStyle: SLINE }, axisTick: OLINE, axisLabel: AXLBL },
    yAxis: { type: 'value', axisLabel: { formatter: v => fmtWan(v), ...AXLBL }, splitLine: { lineStyle: SLINE } },
    series: [
      { name: '累计资金池', type: 'line', smooth: true, data, symbol: 'circle', symbolSize: 6,
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
          label: { formatter: '资金生死线', color: '#c62828', fontSize: 10, position: 'insideEndTop' },
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
    const inflow = _sum(d.collected) + _sum(d.advance_received)
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
</script>

<template>
  <div>
    <div v-if="!embedded" class="topbar">
      <div>
        <h1>现金流分析<span v-if="hasAlert" class="cf-title-alert">⚠ 造血功能不足！请立即采取措施！</span></h1>
        <div style="font-size:13px;color:var(--muted);margin-top:2px">财务驾驶舱 · 预算达成 · 净现金流 · 累计走势</div>
      </div>
    </div>
    <div v-else-if="hasAlert" class="cf-embed-alert">⚠ 造血功能不足！请立即采取措施！</div>

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
      <!-- Date range group — day precision -->
      <div class="cfb-group">
        <svg class="cfb-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
        <span class="cfb-lbl">区间</span>
        <input v-model="filters.start_date" type="date" class="cfb-date" @change="load" />
        <span class="cfb-to">至</span>
        <input v-model="filters.end_date" type="date" class="cfb-date" @change="load" />
      </div>
      <div v-if="loading" class="cfb-loading">
        <span class="cfb-spin">↻</span> 加载中
      </div>
    </div>

    <!-- KPI cards: 三组（收款 / 付款 / 现金流），每组 预算 → 预收/预付 → 实收/实付 -->
    <div class="cf-kpi-groups">
      <!-- 收款组 -->
      <section class="kpi-group kg-coll">
        <div class="kpi-group-head kgh-coll">收款</div>
        <div class="kpi-group-cards">
          <div class="ck-card ck-coll-soft">
            <div class="ck-label">收款预算</div>
            <div class="ck-value">{{ fmtWan(sumBudgetColl) }}</div>
            <div class="ck-sub">收款目标</div>
          </div>
          <div class="ck-card ck-coll-soft">
            <div class="ck-label">预收</div>
            <div class="ck-value">{{ fmtWan(sumAdvRecv) }}</div>
            <div class="ck-sub">客户预付款</div>
          </div>
          <div class="ck-card ck-coll">
            <div class="ck-label">实收</div>
            <div class="ck-value">{{ fmtWan(sumColl) }}</div>
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
            <div class="ck-value">{{ fmtWan(sumBudgetPaid) }}</div>
            <div class="ck-sub">付款目标</div>
          </div>
          <div class="ck-card ck-pay-soft">
            <div class="ck-label">预付</div>
            <div class="ck-value">{{ fmtWan(sumAdvPaid) }}</div>
            <div class="ck-sub">付供应商</div>
          </div>
          <div class="ck-card ck-pay">
            <div class="ck-label">实付</div>
            <div class="ck-value">{{ fmtWan(sumPaid) }}</div>
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
              {{ netTotal >= 0 ? '+' : '' }}{{ fmtWan(netTotal) }}
            </div>
            <div class="ck-sub">流入 − 流出</div>
          </div>
          <div class="ck-card" :class="endCumulative >= 0 ? 'ck-net-pos' : 'ck-net-neg'">
            <div class="ck-label">期末累计</div>
            <div class="ck-value" :class="endCumulative >= 0 ? 'v-pos' : 'v-neg'">
              {{ endCumulative >= 0 ? '+' : '' }}{{ fmtWan(endCumulative) }}
            </div>
            <div class="ck-sub">资金池终值</div>
          </div>
        </div>
      </section>
    </div>

    <!-- Chart grid (creative cash-flow viz suite) -->
    <div class="cockpit-grid">
      <!-- 招牌图：现金流量桥 -->
      <div class="card span2">
        <div class="section-title">现金流量桥
          <span class="section-sub">实收 + 预收 − 实付 − 预付 = 期末净现金</span>
        </div>
        <BaseChart v-if="bridgeOption" :option="bridgeOption" height="300px" />
        <div v-else class="chart-empty">{{ loading ? '加载中…' : '暂无数据' }}</div>
      </div>

      <!-- 现金呼吸图（流入↑/流出↓ + 净额线）-->
      <div class="card span2">
        <div class="section-title">现金呼吸图
          <span class="section-sub">上方流入 · 下方流出 · 蓝线为月净额 · 红带=当月入不敷出</span>
        </div>
        <BaseChart v-if="breathOption" :option="breathOption" height="340px" />
        <div v-else class="chart-empty">{{ loading ? '加载中…' : '暂无数据' }}</div>
      </div>

      <!-- 现金跑道与谷底 -->
      <div class="card span2">
        <div class="section-title">现金跑道与谷底
          <span class="section-sub">累计资金池 · 跌破 0 转红 · 标注现金谷底与资金峰值</span>
        </div>
        <BaseChart v-if="runwayOption" :option="runwayOption" height="280px" />
        <div v-else class="chart-empty">{{ loading ? '加载中…' : '暂无数据' }}</div>
      </div>
    </div>

    <!-- 事业部现金收支平衡气泡 (multi-dept) -->
    <div v-if="showDeptComparison" class="card" style="margin-top:16px">
      <div class="section-title">事业部现金收支平衡
        <span class="section-sub">X=流入　Y=流出　气泡=净现金额　虚线上方=失血 / 下方=造血 · {{ filters.start_date }} 至 {{ filters.end_date }}</span>
      </div>
      <BaseChart v-if="deptBalanceOption" :option="deptBalanceOption" height="380px" />
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
            <tr v-for="(ym, i) in cfData.months" :key="ym"
                :class="{ 'row-alert': cfData.totals.outflow[i] > cfData.totals.inflow[i] && cfData.totals.inflow[i] > 0 }"
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
/* ── Polished filter bar ── */
.cf-filterbar {
  display: flex; align-items: center;
  background: rgba(255,255,255,0.88); border: 1px solid rgba(255,255,255,0.92);
  border-radius: 14px; padding: 4px 10px;
  box-shadow: 0 2px 14px rgba(0,0,0,0.06);
  margin-bottom: 20px; backdrop-filter: blur(10px);
  flex-wrap: nowrap; overflow-x: auto;
}
.cfb-group { display: flex; align-items: center; gap: 7px; padding: 5px 10px; }
.cfb-icon  { color: var(--muted); flex-shrink: 0; }
.cfb-lbl   { font-size: 11.5px; font-weight: 600; color: var(--muted); white-space: nowrap; }
.cfb-div   { width: 1px; height: 24px; background: rgba(0,0,0,0.09); margin: 0 4px; flex-shrink: 0; }
.cfb-sel {
  height: 30px; padding: 0 10px; border: none;
  background: rgba(0,0,0,0.04); border-radius: 8px;
  font-size: 12.5px; color: var(--text); cursor: pointer; outline: none;
  transition: background .15s, color .15s;
}
.cfb-sel:hover, .cfb-sel:focus { background: rgba(201,99,66,0.09); color: var(--primary); }
.cfb-dept { min-width: 110px; }
.cfb-date {
  height: 30px; padding: 0 8px; border: none;
  background: rgba(0,0,0,0.04); border-radius: 8px;
  font-size: 12.5px; color: var(--text); cursor: pointer; outline: none;
  width: 138px; font-variant-numeric: tabular-nums;
  transition: background .15s, color .15s;
}
.cfb-date:hover, .cfb-date:focus { background: rgba(201,99,66,0.09); color: var(--primary); }
.cfb-to   { font-size: 12px; color: var(--muted); }
.cfb-loading { margin-left: auto; padding-left: 12px; font-size: 12px; color: var(--primary); display: flex; align-items: center; gap: 5px; white-space: nowrap; }
.cfb-spin { display: inline-block; animation: cfSpin 0.9s linear infinite; }
@keyframes cfSpin { to { transform: rotate(360deg); } }

/* ── Reminder banners (GPU-composited: opacity-only pulse) ── */
.urge-banner {
  display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap;
  padding: 14px 20px; margin-bottom: 16px; border-radius: 14px;
  background: rgba(198,40,40,.06); border: 1.5px solid rgba(198,40,40,.3);
  box-shadow: 0 2px 14px rgba(198,40,40,.10);
}
.urge-left  { display: flex; align-items: center; gap: 12px; }
.urge-icon  { font-size: 24px; }
.urge-title { font-weight: 700; color: #c62828; font-size: 14px; }
.urge-sub   { font-size: 12.5px; color: #c62828; opacity: .9; margin-top: 2px; }
.urge-right { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.urge-key   { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.urge-key-label { font-size: 11px; color: #c62828; font-weight: 600; }
.urge-chip  { display: inline-flex; align-items: center; gap: 5px; font-size: 11.5px; padding: 3px 10px; border-radius: 12px; background: rgba(255,255,255,.6); border: 1px solid rgba(198,40,40,.3); color: #c62828; cursor: pointer; transition: all .14s; }
.urge-chip:hover { background: #c62828; color: #fff; }
.urge-btn   { padding: 7px 16px; border-radius: 9px; border: none; background: #c62828; color: #fff; font-size: 13px; font-weight: 600; cursor: pointer; transition: filter .14s; }
.urge-btn:hover { filter: brightness(1.08); }

.cashflow-alert {
  display: flex; align-items: flex-start; gap: 14px; padding: 14px 20px; margin: 0 0 16px;
  background: rgba(245,127,23,.08); border: 1.5px solid rgba(245,127,23,.3); border-radius: 12px;
}
.alert-icon  { font-size: 20px; flex-shrink: 0; }
.alert-title { font-weight: 700; color: #e65100; font-size: 13.5px; }
.alert-months { font-size: 12px; color: #e65100; margin-top: 3px; opacity: .9; }

/* ── Title inline alert ── */
.cf-title-alert {
  font-size: 13px; font-weight: 700; color: #c62828;
  margin-left: 14px; vertical-align: middle;
}
.cf-embed-alert {
  font-size: 13px; font-weight: 700; color: #c62828;
  background: rgba(198,40,40,.07); border: 1px solid rgba(198,40,40,.2);
  border-radius: 10px; padding: 8px 14px; margin-bottom: 14px;
}

/* ── KPI cards: 三组一排（收款 / 付款 / 现金流） ── */
.cf-kpi-groups { display: flex; gap: 16px; margin-bottom: 16px; align-items: stretch; }
.kpi-group { display: flex; flex-direction: column; gap: 8px; min-width: 0; }
.kg-coll, .kg-pay { flex: 3; }   /* 各 3 张卡 */
.kg-cash { flex: 2; }            /* 2 张卡 */
.kpi-group-head {
  font-size: 12px; font-weight: 800; letter-spacing: .1em;
  padding-left: 9px; border-left: 3px solid; line-height: 1.1;
}
.kgh-coll { color: #2e7d32; border-color: #2e7d32; }
.kgh-pay  { color: #e65100; border-color: #e65100; }
.kgh-cash { color: #1565c0; border-color: #1565c0; }
.kpi-group-cards { display: flex; gap: 10px; min-width: 0; }
.kpi-group-cards .ck-card { flex: 1; min-width: 0; }

.ck-card {
  background: rgba(255,255,255,0.78); border: 1px solid rgba(255,255,255,0.9); border-radius: 14px;
  padding: 12px 14px; box-shadow: 0 2px 14px rgba(0,0,0,0.05); border-left: 3px solid var(--border);
}
.ck-coll       { border-left-color: #2e7d32; }
.ck-coll-soft  { border-left-color: rgba(46,125,50,0.38); }
.ck-pay        { border-left-color: #e65100; }
.ck-pay-soft   { border-left-color: rgba(230,81,0,0.38); }
.ck-net-pos    { border-left-color: #2e7d32; }
.ck-net-neg    { border-left-color: #c62828; }
.ck-label    { font-size: 10.5px; color: var(--muted); font-weight: 700; letter-spacing: .03em; white-space: nowrap; }
.ck-value    { font-size: 19px; font-weight: 800; color: var(--text); line-height: 1.2; margin: 5px 0 3px; white-space: nowrap; }
.v-pos       { color: #2e7d32 !important; }
.v-neg       { color: #c62828 !important; }
.ck-sub      { font-size: 11px; white-space: nowrap; }
.ach-ok      { color: #2e7d32; font-weight: 600; }
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

/* ── Chart grid ── */
.cockpit-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.cockpit-grid .span2 { grid-column: span 2; }
@media (max-width: 900px) { .cockpit-grid { grid-template-columns: 1fr; } .cockpit-grid .span2 { grid-column: 1; } }
.chart-empty { height: 120px; display: flex; align-items: center; justify-content: center; color: var(--muted); font-size: 13px; }

/* ── Section title with sub-label ── */
.section-sub { font-size: 11px; color: var(--muted); font-weight: 400; margin-left: 8px; }

/* ── Table ── */
.row-alert { background: rgba(198,40,40,.04); }
.fw { font-weight: 600; }
.amt { text-align: right; }
.muted { color: var(--muted); }
.text-coll   { color: #2e7d32; font-weight: 600; }
.text-pay    { color: #e65100; }
.text-danger { color: #c62828; font-weight: 600; }
.text-ok     { color: #2e7d32; font-weight: 600; }
</style>
