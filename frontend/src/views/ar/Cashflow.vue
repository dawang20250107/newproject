<script setup>
import { ref, computed, reactive, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../../stores/auth.js'
import { DEPARTMENTS, yearCST, monthCST } from '../../constants.js'
import ar from '../../api/ar.js'
import { fmtCompact } from '../../utils/format.js'
import BaseChart from '../../components/ar/BaseChart.vue'

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
    console.error(e)
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
const sumColl = computed(() => (totals.value?.collected || []).reduce((a, b) => a + b, 0))
const sumPaid = computed(() => (totals.value?.paid || []).reduce((a, b) => a + b, 0))
const netTotal = computed(() => sumColl.value - sumPaid.value)
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

// 1. 收付与预算达成对比
const budgetOption = computed(() => {
  if (!cfData.value) return null
  const t = cfData.value.totals
  const lbls = cfData.value.months.map(ym => ym.slice(5) + '月')
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, ...TT_STYLE, formatter: ttFmt },
    legend: { bottom: 4, icon: 'roundRect', itemWidth: 14, itemHeight: 8,
              textStyle: { fontSize: 11, color: '#555' },
              data: ['实收', '实付', '收款预算', '付款预算'] },
    grid: GRID,
    xAxis: { type: 'category', data: lbls, axisLine: { lineStyle: SLINE }, axisTick: OLINE, axisLabel: AXLBL },
    yAxis: { type: 'value', axisLabel: { formatter: v => fmtWan(v), ...AXLBL }, splitLine: { lineStyle: SLINE } },
    series: [
      { name: '实收', type: 'bar', barGap: '10%', barMaxWidth: 24, data: t.collected,
        itemStyle: { color: gradBar('#66bb6a', '#2e7d32'), borderRadius: [4, 4, 0, 0] } },
      { name: '实付', type: 'bar', barMaxWidth: 24,
        data: t.paid.map((v, i) => ({ value: v,
          itemStyle: { borderRadius: [4, 4, 0, 0],
            color: v > 0 && v > t.collected[i]
              ? gradBar('#ef5350', '#c62828')
              : gradBar('#ffa726', '#e65100') } })) },
      { name: '收款预算', type: 'line', data: t.budget_collection, smooth: true,
        symbol: 'circle', symbolSize: 4,
        lineStyle: { type: 'dashed', color: '#2e7d32', width: 1.5, opacity: 0.65 },
        itemStyle: { color: '#2e7d32' } },
      { name: '付款预算', type: 'line', data: t.budget_payment, smooth: true,
        symbol: 'circle', symbolSize: 4,
        lineStyle: { type: 'dashed', color: '#e65100', width: 1.5, opacity: 0.65 },
        itemStyle: { color: '#e65100' } },
    ],
  }
})

// 2. 净现金流趋势
const netOption = computed(() => {
  if (!cfData.value) return null
  const t = cfData.value.totals
  const lbls = cfData.value.months.map(ym => ym.slice(5) + '月')
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, ...TT_STYLE,
      formatter: p => `<b>${p[0].axisValueLabel}</b><br/>净现金流：<b>${fmtWan(p[0].value)}</b>` },
    grid: GRIDL,
    xAxis: { type: 'category', data: lbls, axisLine: { lineStyle: SLINE }, axisTick: OLINE, axisLabel: AXLBL },
    yAxis: { type: 'value', axisLabel: { formatter: v => fmtWan(v), ...AXLBL }, splitLine: { lineStyle: SLINE } },
    series: [{
      type: 'bar', barMaxWidth: 32,
      data: (t.net || []).map(v => ({ value: v,
        itemStyle: {
          borderRadius: v >= 0 ? [4, 4, 0, 0] : [0, 0, 4, 4],
          color: v >= 0 ? gradBar('#66bb6a', '#2e7d32') : gradBar('#ef5350', '#c62828'),
        }
      })),
      markLine: { silent: true, symbol: 'none',
        lineStyle: { color: 'rgba(0,0,0,0.2)', type: 'dashed' }, data: [{ yAxis: 0 }] },
    }],
  }
})

// 3. 累计现金流曲线
const cumulativeOption = computed(() => {
  if (!cfData.value) return null
  const t = cfData.value.totals
  const lbls = cfData.value.months.map(ym => ym.slice(5) + '月')
  return {
    tooltip: { trigger: 'axis', ...TT_STYLE,
      formatter: p => `<b>${p[0].axisValueLabel}</b><br/>累计净现金流：<b>${fmtWan(p[0].value)}</b>` },
    grid: GRIDL,
    xAxis: { type: 'category', boundaryGap: false, data: lbls,
             axisLine: { lineStyle: SLINE }, axisTick: OLINE, axisLabel: AXLBL },
    yAxis: { type: 'value', axisLabel: { formatter: v => fmtWan(v), ...AXLBL }, splitLine: { lineStyle: SLINE } },
    series: [{
      type: 'line', smooth: true, data: t.cumulative_net || [],
      symbol: 'circle', symbolSize: 7,
      lineStyle: { color: '#1565c0', width: 2.5 },
      itemStyle: { color: '#fff', borderColor: '#1565c0', borderWidth: 2.5 },
      areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
        colorStops: [{ offset: 0, color: 'rgba(21,101,192,0.28)' }, { offset: 1, color: 'rgba(21,101,192,0.02)' }] } },
      markLine: { silent: true, symbol: 'none',
        lineStyle: { color: 'rgba(0,0,0,0.2)', type: 'dashed' }, data: [{ yAxis: 0 }] },
    }],
  }
})

// 4. 各事业部对比 (shown only when dept='' AND multiple depts exist)
const deptCompareOption = computed(() => {
  if (!showDeptComparison.value) return null
  const byDept = cfData.value.by_dept
  const sums = byDept.map(d => ({
    dept: d.dept,
    coll:  d.collected.reduce((a, b) => a + b, 0),
    paid:  d.paid.reduce((a, b) => a + b, 0),
    bcoll: d.budget_collection.reduce((a, b) => a + b, 0),
    bpaid: d.budget_payment.reduce((a, b) => a + b, 0),
  }))
  const deptNames = sums.map(d => d.dept)
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, ...TT_STYLE, formatter: ttFmt },
    legend: { bottom: 4, icon: 'roundRect', itemWidth: 14, itemHeight: 8,
              textStyle: { fontSize: 11, color: '#555' },
              data: ['实收', '实付', '收款预算', '付款预算'] },
    grid: { ...GRID, bottom: deptNames.length > 5 ? 64 : 48 },
    xAxis: { type: 'category', data: deptNames,
             axisLine: { lineStyle: SLINE }, axisTick: OLINE,
             axisLabel: { ...AXLBL, interval: 0, rotate: deptNames.length > 5 ? 22 : 0 } },
    yAxis: { type: 'value', axisLabel: { formatter: v => fmtWan(v), ...AXLBL }, splitLine: { lineStyle: SLINE } },
    series: [
      { name: '实收', type: 'bar', barGap: '12%', barMaxWidth: 26,
        data: sums.map(d => d.coll),
        itemStyle: { color: gradBar('#66bb6a', '#2e7d32'), borderRadius: [4, 4, 0, 0] } },
      { name: '实付', type: 'bar', barMaxWidth: 26,
        data: sums.map(d => ({ value: d.paid,
          itemStyle: { borderRadius: [4, 4, 0, 0],
            color: d.paid > d.coll ? gradBar('#ef5350', '#c62828') : gradBar('#ffa726', '#e65100') } })) },
      { name: '收款预算', type: 'bar', barGap: '40%', barMaxWidth: 14,
        data: sums.map(d => d.bcoll),
        itemStyle: { color: 'rgba(46,125,50,0.25)', borderColor: '#2e7d32', borderWidth: 1.5, borderRadius: [4, 4, 0, 0] } },
      { name: '付款预算', type: 'bar', barMaxWidth: 14,
        data: sums.map(d => d.bpaid),
        itemStyle: { color: 'rgba(230,81,0,0.25)', borderColor: '#e65100', borderWidth: 1.5, borderRadius: [4, 4, 0, 0] } },
    ],
  }
})
</script>

<template>
  <div>
    <div class="topbar">
      <div>
        <h1>现金流分析<span v-if="hasAlert" class="cf-title-alert">⚠ 造血功能不足！请立即采取措施！</span></h1>
        <div style="font-size:13px;color:var(--muted);margin-top:2px">财务驾驶舱 · 预算达成 · 净现金流 · 累计走势</div>
      </div>
    </div>

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

    <!-- KPI cards: 收款预算 → 实收 → 付款预算 → 实付 → 净现金流(highlight) → 累计净现金流(highlight) -->
    <div class="cockpit-kpis">
      <div class="ck-card ck-neutral">
        <div class="ck-label">区间收款预算</div>
        <div class="ck-value">{{ fmtWan(sumBudgetColl) }}</div>
        <div class="ck-sub">收款目标</div>
      </div>
      <div class="ck-card ck-neutral">
        <div class="ck-label">区间实收</div>
        <div class="ck-value">{{ fmtWan(sumColl) }}</div>
        <div class="ck-sub" v-if="collAchieve !== null">
          <span :class="collAchieve >= 100 ? 'ach-ok' : 'ach-off'">预算达成 {{ collAchieve.toFixed(1) }}%</span>
        </div>
        <div class="ck-sub ach-off" v-else>无预算基准</div>
      </div>
      <div class="ck-card ck-neutral">
        <div class="ck-label">区间付款预算</div>
        <div class="ck-value">{{ fmtWan(sumBudgetPaid) }}</div>
        <div class="ck-sub">付款目标</div>
      </div>
      <div class="ck-card ck-neutral">
        <div class="ck-label">区间实付</div>
        <div class="ck-value">{{ fmtWan(sumPaid) }}</div>
        <div class="ck-sub" v-if="payAchieve !== null">
          <span :class="payAchieve >= 100 ? 'ach-ok' : 'ach-off'">预算达成 {{ payAchieve.toFixed(1) }}%</span>
        </div>
        <div class="ck-sub ach-off" v-else>无预算基准</div>
      </div>
      <div class="ck-card" :class="netTotal >= 0 ? 'ck-net-pos' : 'ck-net-neg'">
        <div class="ck-label">区间净现金流</div>
        <div class="ck-value" :class="netTotal >= 0 ? 'v-pos' : 'v-neg'">
          {{ netTotal >= 0 ? '+' : '' }}{{ fmtWan(netTotal) }}
        </div>
        <div class="ck-sub">实收 − 实付</div>
      </div>
      <div class="ck-card" :class="endCumulative >= 0 ? 'ck-net-pos' : 'ck-net-neg'">
        <div class="ck-label">期末累计净现金流</div>
        <div class="ck-value" :class="endCumulative >= 0 ? 'v-pos' : 'v-neg'">
          {{ endCumulative >= 0 ? '+' : '' }}{{ fmtWan(endCumulative) }}
        </div>
        <div class="ck-sub">资金池走势终值</div>
      </div>
    </div>

    <!-- Chart grid (2-col layout) -->
    <div class="cockpit-grid">
      <div class="card span2">
        <div class="section-title">收付与预算达成对比</div>
        <BaseChart v-if="budgetOption" :option="budgetOption" height="320px" />
        <div v-else-if="!loading" class="chart-empty">暂无数据</div>
        <div v-else class="chart-empty">加载中…</div>
      </div>
      <div class="card">
        <div class="section-title">净现金流趋势</div>
        <BaseChart v-if="netOption" :option="netOption" height="260px" />
        <div v-else class="chart-empty">暂无数据</div>
      </div>
      <div class="card">
        <div class="section-title">累计现金流曲线</div>
        <BaseChart v-if="cumulativeOption" :option="cumulativeOption" height="260px" />
        <div v-else class="chart-empty">暂无数据</div>
      </div>
    </div>

    <!-- Per-dept comparison (multi-dept users, shown only when "全部" selected) -->
    <div v-if="showDeptComparison" class="card" style="margin-top:16px">
      <div class="section-title">各事业部对比
        <span class="section-sub">{{ filters.start_date }} 至 {{ filters.end_date }}</span>
      </div>
      <BaseChart v-if="deptCompareOption" :option="deptCompareOption" height="280px" />
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
                :class="{ 'row-alert': cfData.totals.paid[i] > cfData.totals.collected[i] && cfData.totals.collected[i] > 0 }">
              <td class="fw">{{ ym }}</td>
              <td class="amt text-coll">{{ fmtWan(cfData.totals.collected[i]) }}</td>
              <td class="amt" :class="cfData.totals.paid[i] > cfData.totals.collected[i] ? 'text-danger' : 'text-pay'">
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
  animation: urgePulse 1.8s ease-in-out infinite; will-change: opacity;
}
@keyframes urgePulse { 0%,100% { opacity: 1; } 50% { opacity: .72; } }
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
  animation: urgePulse 1.8s ease-in-out infinite; will-change: opacity;
}
.alert-icon  { font-size: 20px; flex-shrink: 0; }
.alert-title { font-weight: 700; color: #e65100; font-size: 13.5px; }
.alert-months { font-size: 12px; color: #e65100; margin-top: 3px; opacity: .9; }

/* ── Title inline alert ── */
.cf-title-alert {
  font-size: 13px; font-weight: 700; color: #c62828;
  margin-left: 14px; vertical-align: middle;
  animation: cfAlertPulse 1.8s ease-in-out infinite; will-change: opacity;
}
@keyframes cfAlertPulse { 0%,100% { opacity: 1; } 50% { opacity: 0.55; } }

/* ── KPI cards ── */
.cockpit-kpis { display: grid; grid-template-columns: repeat(6, 1fr); gap: 14px; margin-bottom: 16px; }
@media (max-width: 1100px) { .cockpit-kpis { grid-template-columns: repeat(3, 1fr); } }
@media (max-width: 700px)  { .cockpit-kpis { grid-template-columns: repeat(2, 1fr); } }
.ck-card {
  background: rgba(255,255,255,0.78); border: 1px solid rgba(255,255,255,0.9); border-radius: 16px;
  padding: 18px 20px; box-shadow: 0 2px 18px rgba(0,0,0,0.06); border-left: 3px solid var(--border);
}
.ck-neutral  { border-left-color: var(--muted); }
.ck-net-pos  { border-left-color: #2e7d32; }
.ck-net-neg  { border-left-color: #c62828; }
.ck-label    { font-size: 11px; color: var(--muted); font-weight: 700; letter-spacing: .05em; text-transform: uppercase; }
.ck-value    { font-size: 24px; font-weight: 800; color: var(--text); line-height: 1.15; margin: 6px 0 4px; }
.v-pos       { color: #2e7d32 !important; }
.v-neg       { color: #c62828 !important; }
.ck-sub      { font-size: 11.5px; }
.ach-ok      { color: #2e7d32; font-weight: 600; }
.ach-off     { color: var(--muted); }

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
