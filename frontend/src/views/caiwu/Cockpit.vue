<script setup>
import { ref, computed, onMounted } from 'vue'
import { useCaiwuAuth } from '../../composables/useCaiwuAuth.js'
import { BUSINESS_UNITS, yearCST, monthCST } from '../../constants.js'
import BaseChart from '../../components/caiwu/charts/BaseChart.vue'
import api from '../../api/caiwu.js'
import { fmtCompact } from '../../utils/format.js'
import EmptyState from '../../components/EmptyState.vue'

const auth = useCaiwuAuth()

const year = ref(yearCST())
const month = ref(monthCST())
const selectedBu = ref('')

const loading = ref(false)
const loadErr = ref('')
const data = ref(null)

const years = Array.from({ length: 5 }, (_, i) => yearCST() - 2 + i)
const months = Array.from({ length: 12 }, (_, i) => i + 1)

const accessibleBus = computed(() => {
  if (auth.isAdmin) return BUSINESS_UNITS
  return (auth.user?.departments || []).filter(d => BUSINESS_UNITS.includes(d))
})

const fmtMoney = (v) => fmtCompact(v, { space: true })
const wan = (v) => (v == null ? '—' : (v / 10000).toFixed(0) + '万')

async function load() {
  loading.value = true
  loadErr.value = ''
  try {
    const params = { year: year.value, month: month.value }
    if (selectedBu.value) params.bu = selectedBu.value
    const res = await api.get('/cockpit', { params })
    data.value = res.data
  } catch (e) {
    loadErr.value = e?.error || '加载失败'
  } finally {
    loading.value = false
  }
}

// ── headline KPI cards ───────────────────────────────────────────────────────
const cards = computed(() => {
  const o = data.value?.overview
  if (!o) return []
  const m = o.month, y = o.ytd
  return [
    { label: '本月收入', value: fmtMoney(m.actual_revenue), color: '#2e7d32',
      mom: m.revenue_mom, yoy: m.revenue_yoy },
    { label: '本月利润', value: fmtMoney(m.actual_profit), color: '#e65100',
      mom: m.profit_mom, yoy: m.profit_yoy, neg: (m.actual_profit ?? 0) < 0 },
    { label: '本月收入达成', value: fmtRate(m.revenue_rate), rate: m.revenue_rate, isRate: true },
    { label: '本月利润达成', value: fmtRate(m.profit_rate), rate: m.profit_rate, isRate: true },
    { label: 'YTD收入达成', value: fmtRate(y.revenue_rate), rate: y.revenue_rate, isRate: true },
    { label: 'YTD利润达成', value: fmtRate(y.profit_rate), rate: y.profit_rate, isRate: true },
  ]
})

function fmtRate(r) { return r == null ? '—' : r.toFixed(1) + '%' }
function rateColor(r) {
  if (r == null) return 'var(--muted)'
  if (r >= 100) return '#2e7d32'
  if (r >= 80) return '#e65100'
  return '#c62828'
}
function chgLabel(v) {
  if (v == null) return '— '
  return (v >= 0 ? '▲ ' : '▼ ') + Math.abs(v).toFixed(1) + '%'
}
function chgClass(v) { return v == null ? 'mom-neutral' : (v >= 0 ? 'mom-up' : 'mom-down') }

// ── 12-month trend (actual bar + target line) ────────────────────────────────
function trendOption(actualKey, targetKey, label, color) {
  const t = data.value?.trend || []
  const x = t.map(m => `${m.month}月`)
  return {
    tooltip: {
      trigger: 'axis',
      formatter(params) {
        let s = `<b>${params[0]?.axisValue}</b><br/>`
        params.forEach(p => {
          const v = p.value == null ? '—' : (Math.abs(p.value) >= 10000 ? (p.value / 10000).toFixed(1) + '万' : p.value.toFixed(0))
          s += `${p.marker}${p.seriesName}：${v}<br/>`
        })
        return s
      },
    },
    legend: { bottom: 0, itemGap: 18 },
    grid: { top: 24, right: 20, bottom: 40, left: 20, containLabel: true },
    xAxis: { type: 'category', data: x, axisLine: { lineStyle: { color: '#d4c4b4' } }, axisLabel: { color: '#9b8070', fontSize: 11 } },
    yAxis: {
      type: 'value',
      axisLabel: { color: '#9b8070', fontSize: 10, formatter: v => Math.abs(v) >= 10000 ? (v / 10000).toFixed(0) + '万' : v },
      splitLine: { lineStyle: { color: 'rgba(180,140,110,.15)' } },
    },
    series: [
      { name: '实际' + label, type: 'bar', data: t.map(m => m[actualKey]), itemStyle: { color, borderRadius: [4, 4, 0, 0] }, barMaxWidth: 30 },
      { name: '目标' + label, type: 'line', data: t.map(m => m[targetKey]), smooth: true, symbol: 'circle', symbolSize: 6, color: '#c96342', lineStyle: { type: 'dashed', width: 2 } },
    ],
  }
}
const revenueTrend = computed(() => trendOption('actual_revenue', 'target_revenue', '收入', '#2e7d32'))
const profitTrend = computed(() => trendOption('actual_profit', 'target_profit', '利润', '#1565c0'))

// ── per-BU current-month actual (revenue & profit) ───────────────────────────
const buActualOption = computed(() => {
  const bus = data.value?.bus || []
  const names = bus.map(b => b.business_unit)
  return {
    tooltip: {
      trigger: 'axis', axisPointer: { type: 'shadow' },
      formatter(params) {
        let s = `<b>${params[0]?.axisValue}</b><br/>`
        params.forEach(p => {
          const v = p.value == null ? '—' : (Math.abs(p.value) >= 10000 ? (p.value / 10000).toFixed(1) + '万' : p.value.toFixed(0))
          s += `${p.marker}${p.seriesName}：${v}<br/>`
        })
        return s
      },
    },
    legend: { bottom: 0, itemGap: 18 },
    grid: { top: 24, right: 20, bottom: 48, left: 20, containLabel: true },
    xAxis: { type: 'category', data: names, axisLine: { lineStyle: { color: '#d4c4b4' } }, axisLabel: { color: '#9b8070', fontSize: 11, interval: 0, rotate: names.length > 4 ? 20 : 0 } },
    yAxis: { type: 'value', axisLabel: { color: '#9b8070', fontSize: 10, formatter: v => Math.abs(v) >= 10000 ? (v / 10000).toFixed(0) + '万' : v }, splitLine: { lineStyle: { color: 'rgba(180,140,110,.15)' } } },
    series: [
      { name: '收入', type: 'bar', data: bus.map(b => b.month.actual_revenue), itemStyle: { color: '#2e7d32', borderRadius: [4, 4, 0, 0] }, barMaxWidth: 26 },
      { name: '利润', type: 'bar', data: bus.map(b => b.month.actual_profit), itemStyle: { color: '#1565c0', borderRadius: [4, 4, 0, 0] }, barMaxWidth: 26 },
    ],
  }
})

// ── per-BU YTD achievement rate (revenue & profit) ───────────────────────────
const buRateOption = computed(() => {
  const bus = data.value?.bus || []
  const names = bus.map(b => b.business_unit)
  return {
    tooltip: {
      trigger: 'axis', axisPointer: { type: 'shadow' },
      formatter(params) {
        let s = `<b>${params[0]?.axisValue}</b><br/>`
        params.forEach(p => { s += `${p.marker}${p.seriesName}：${p.value == null ? '—' : p.value.toFixed(1) + '%'}<br/>` })
        return s
      },
    },
    legend: { bottom: 0, itemGap: 18 },
    grid: { top: 24, right: 20, bottom: 48, left: 20, containLabel: true },
    xAxis: { type: 'category', data: names, axisLine: { lineStyle: { color: '#d4c4b4' } }, axisLabel: { color: '#9b8070', fontSize: 11, interval: 0, rotate: names.length > 4 ? 20 : 0 } },
    yAxis: { type: 'value', name: '达成率%', axisLabel: { color: '#9b8070', fontSize: 10, formatter: '{value}%' }, splitLine: { lineStyle: { color: 'rgba(180,140,110,.15)' } } },
    series: [
      { name: 'YTD收入达成', type: 'bar', data: bus.map(b => b.ytd.revenue_rate), itemStyle: { color: '#66bb6a', borderRadius: [4, 4, 0, 0] }, barMaxWidth: 26,
        markLine: { silent: true, symbol: 'none', lineStyle: { color: '#c96342', type: 'dashed' }, data: [{ yAxis: 100, label: { formatter: '100%', color: '#c96342', fontSize: 10 } }] } },
      { name: 'YTD利润达成', type: 'bar', data: bus.map(b => b.ytd.profit_rate), itemStyle: { color: '#42a5f5', borderRadius: [4, 4, 0, 0] }, barMaxWidth: 26 },
    ],
  }
})

const hasData = computed(() => (data.value?.bus || []).some(b => b.month.actual_revenue != null || b.month.actual_profit != null))

onMounted(load)
</script>

<template>
  <div>
    <div class="topbar" style="align-items:flex-start">
      <h1>财务驾驶舱</h1>
      <div class="ctrl-row" style="justify-content:flex-end">
        <select v-model="year" class="sel-yr" @change="load">
          <option v-for="y in years" :key="y" :value="y">{{ y }} 年</option>
        </select>
        <select v-model="month" class="sel-mo" @change="load">
          <option v-for="m in months" :key="m" :value="m">{{ m }} 月</option>
        </select>
        <select v-if="accessibleBus.length > 1" v-model="selectedBu" class="sel-bu" @change="load">
          <option value="">全集团</option>
          <option v-for="bu in accessibleBus" :key="bu" :value="bu">{{ bu }}</option>
        </select>
      </div>
    </div>

    <EmptyState v-if="loading && !data" loading />
    <EmptyState v-else-if="loadErr" :error="loadErr" />
    <template v-else-if="data">
      <div :class="{ 'data-reloading': loading }">

      <div v-if="!hasData" class="nodata-banner">
        📭 {{ data.year }}年{{ data.month }}月 · {{ selectedBu || '全集团' }} 暂无已发布数据
      </div>

      <!-- ── headline KPI cards ─────────────────────────────────────────────── -->
      <div class="kpi-grid kpi-6">
        <div v-for="c in cards" :key="c.label" class="kpi-card">
          <div class="label">{{ c.label }}</div>
          <div class="value" :style="`color:${c.isRate ? rateColor(c.rate) : (c.neg ? '#c62828' : c.color)}`">{{ c.value }}</div>
          <div v-if="!c.isRate" class="mom-line">
            <span class="mom-badge" :class="chgClass(c.mom)">{{ chgLabel(c.mom) }} 环比</span>
            <span class="mom-badge" :class="chgClass(c.yoy)">{{ chgLabel(c.yoy) }} 同比</span>
          </div>
          <div v-else class="sub">{{ data.year }}年{{ data.month }}月</div>
        </div>
      </div>

      <!-- ── trend charts ───────────────────────────────────────────────────── -->
      <div class="chart-grid">
        <div class="card">
          <div class="section-title" style="margin-bottom:8px">收入 · 目标 vs 实际（{{ data.year }}年）</div>
          <BaseChart :option="revenueTrend" height="300px" />
        </div>
        <div class="card">
          <div class="section-title" style="margin-bottom:8px">利润 · 目标 vs 实际（{{ data.year }}年）</div>
          <BaseChart :option="profitTrend" height="300px" />
        </div>
      </div>

      <!-- ── per-BU charts ──────────────────────────────────────────────────── -->
      <div class="chart-grid">
        <div class="card">
          <div class="section-title" style="margin-bottom:8px">各事业部当月收入 / 利润</div>
          <BaseChart :option="buActualOption" height="320px" />
        </div>
        <div class="card">
          <div class="section-title" style="margin-bottom:8px">各事业部 YTD 达成率</div>
          <BaseChart :option="buRateOption" height="320px" />
        </div>
      </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.kpi-6 { grid-template-columns: repeat(6, 1fr) !important; }
@media (max-width: 1100px) { .kpi-6 { grid-template-columns: repeat(3, 1fr) !important; } }
@media (max-width: 560px) { .kpi-6 { grid-template-columns: repeat(2, 1fr) !important; } }

.nodata-banner {
  display: flex; align-items: center; gap: 8px;
  padding: 12px 16px; margin-bottom: 16px;
  background: rgba(180,140,110,.08); border: 1px dashed var(--border);
  border-radius: 12px; font-size: 13px; color: var(--muted);
}

.mom-line { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 6px; }
.mom-badge {
  display: inline-block; font-size: 11px; font-weight: 600;
  padding: 2px 7px; border-radius: 10px;
}
.mom-up { background: rgba(46,125,50,.10); color: #2e7d32; }
.mom-down { background: rgba(198,40,40,.10); color: #c62828; }
.mom-neutral { background: rgba(120,120,120,.08); color: var(--muted); font-weight: 400; }

.chart-grid {
  display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-top: 16px;
}
@media (max-width: 900px) { .chart-grid { grid-template-columns: 1fr; } }
</style>
