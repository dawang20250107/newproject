<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../../stores/auth.js'
import { DEPARTMENTS } from '../../constants.js'
import ar from '../../api/ar.js'
import BaseChart from '../../components/ar/BaseChart.vue'

const auth = useAuthStore()
const router = useRouter()

const selectedDept = ref('')
const selectedYear = ref(new Date().getFullYear())
const years = Array.from({ length: 5 }, (_, i) => new Date().getFullYear() - 2 + i)
const accessibleDepts = computed(() =>
  auth.isSuperAdmin ? DEPARTMENTS : (auth.user?.departments || []).filter(d => DEPARTMENTS.includes(d)))

// ── Chart data ────────────────────────────────────────────────────────────────
const agingData = ref(null)
const collRateData = ref(null)
const topData = ref(null)
const statusData = ref(null)

function fmtWan(v) {
  const n = Math.abs(parseFloat(v) || 0)
  if (n >= 1e8) return (v / 1e8).toFixed(1) + '亿'
  if (n >= 1e4) return (v / 1e4).toFixed(1) + '万'
  return String(Math.round(v))
}

async function loadAll() {
  const params = { dept: selectedDept.value }
  const [a, c, t, s] = await Promise.all([
    ar.aging(params),
    ar.collectionRate({ year: selectedYear.value, ...params }),
    ar.outstandingTop({ ...params, n: 10 }),
    ar.statusDist(params),
  ])
  agingData.value = a.data
  collRateData.value = c.data
  topData.value = t.data
  statusData.value = s.data
}

// ── ECharts options ───────────────────────────────────────────────────────────
const agingColors = ['#2e7d32', '#f57f17', '#e65100', '#c62828', '#6a1b9a']
const agingOption = computed(() => {
  if (!agingData.value) return null
  const labels = agingData.value.map(b => b.label)
  const amounts = agingData.value.map((b, i) => ({
    value: parseFloat(b.amount),
    itemStyle: { color: agingColors[i], borderRadius: [0, 4, 4, 0] },
  }))
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' },
      formatter: p => `${p[0].name}<br/>${fmtWan(p[0].value)} 元 (${p[0].data?.extra || ''}笔)` },
    grid: { top: 16, right: 80, bottom: 8, left: 16, containLabel: true },
    xAxis: { type: 'value', axisLabel: { formatter: v => fmtWan(v) } },
    yAxis: { type: 'category', data: labels, axisLabel: { width: 80, overflow: 'truncate' } },
    series: [{ name: '未收金额', type: 'bar', data: amounts,
      label: { show: true, position: 'right', formatter: p => fmtWan(p.value) } }],
  }
})

const collRateOption = computed(() => {
  if (!collRateData.value) return null
  const { months } = collRateData.value
  const mLabels = months.map(m => `${m.month}月`)
  return {
    tooltip: { trigger: 'axis' },
    legend: { bottom: 0, data: ['应收基础', '已收', '回款率'] },
    grid: { top: 20, right: 60, bottom: 40, left: 16, containLabel: true },
    xAxis: { type: 'category', data: mLabels },
    yAxis: [
      { type: 'value', axisLabel: { formatter: v => fmtWan(v) } },
      { type: 'value', name: '回款率%', min: 0, max: 100, axisLabel: { formatter: v => v + '%' } },
    ],
    series: [
      { name: '应收基础', type: 'bar', yAxisIndex: 0,
        data: months.map(m => m.receivable), itemStyle: { color: '#1565c0', borderRadius: [4, 4, 0, 0] }, barMaxWidth: 24 },
      { name: '已收', type: 'bar', yAxisIndex: 0,
        data: months.map(m => m.collected), itemStyle: { color: '#2e7d32', borderRadius: [4, 4, 0, 0] }, barMaxWidth: 24 },
      { name: '回款率', type: 'line', yAxisIndex: 1, smooth: true,
        data: months.map(m => m.rate),
        lineStyle: { color: '#c96342', width: 2.5 }, symbol: 'circle', symbolSize: 5, itemStyle: { color: '#c96342' } },
    ],
  }
})

const topOption = computed(() => {
  if (!topData.value?.length) return null
  const names = topData.value.map(p => p.short_name.length > 10 ? p.short_name.slice(0, 10) + '…' : p.short_name).reverse()
  const vals = topData.value.map(p => parseFloat(p.total_outstanding)).reverse()
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' },
      formatter: p => `${topData.value[topData.value.length - 1 - p[0].dataIndex].short_name}<br/>未收：${fmtWan(p[0].value)} 元` },
    grid: { top: 8, right: 80, bottom: 8, left: 16, containLabel: true },
    xAxis: { type: 'value', axisLabel: { formatter: v => fmtWan(v) } },
    yAxis: { type: 'category', data: names, axisLabel: { width: 100, overflow: 'truncate' } },
    series: [{ type: 'bar', data: vals, barMaxWidth: 22,
      itemStyle: { color: '#c96342', borderRadius: [0, 4, 4, 0] },
      label: { show: true, position: 'right', formatter: p => fmtWan(p.value) } }],
  }
})

const statusOption = computed(() => {
  if (!statusData.value) return null
  const s = statusData.value
  const pieData = [
    { name: '未到期', value: parseFloat(s.not_due?.amount || 0), itemStyle: { color: '#2e7d32' } },
    { name: '当期', value: parseFloat(s.current?.amount || 0), itemStyle: { color: '#1565c0' } },
    { name: '已逾期', value: parseFloat(s.overdue?.amount || 0), itemStyle: { color: '#c62828' } },
    { name: '已结清', value: parseFloat(s.settled?.amount || 0), itemStyle: { color: '#9e9e9e' } },
  ].filter(d => d.value > 0)
  return {
    tooltip: { trigger: 'item', formatter: p => `${p.name}<br/>${fmtWan(p.value)} 元 (${p.percent.toFixed(1)}%)` },
    legend: { bottom: 0, type: 'scroll' },
    series: [{
      type: 'pie', radius: ['40%', '66%'], center: ['50%', '44%'],
      data: pieData,
      label: { formatter: '{b}\n{d}%', fontSize: 11 },
      emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.3)' } },
    }],
  }
})

function onAgingClick(p) {
  const bucket = agingData.value?.[p.dataIndex]
  if (!bucket) return
  const statusMap = { 'current': '', '1_30': 'overdue', '31_60': 'overdue', '61_90': 'overdue', '90plus': 'overdue' }
  router.push({ path: '/ar/records', query: { dept: selectedDept.value, status: statusMap[bucket.key] || '' } })
}

function onTopClick(p) {
  const idx = topData.value.length - 1 - p.dataIndex
  const proj = topData.value[idx]
  router.push({ path: '/ar/records', query: { project_id: proj.project_id } })
}

watch([selectedDept, selectedYear], loadAll)
onMounted(loadAll)
</script>

<template>
  <div>
    <div class="topbar">
      <h1>应收分析</h1>
      <div class="ctrl-row">
        <select v-model="selectedDept" class="sel-bu" @change="loadAll">
          <option value="">全部事业部</option>
          <option v-for="d in accessibleDepts" :key="d" :value="d">{{ d }}</option>
        </select>
        <select v-model="selectedYear" class="sel-yr" @change="loadAll">
          <option v-for="y in years" :key="y" :value="y">{{ y }}年</option>
        </select>
      </div>
    </div>

    <!-- Stats summary -->
    <div v-if="statusData" class="kpi-grid kpi-4" style="margin-bottom:16px">
      <div class="kpi-card">
        <div class="label">逾期笔数</div>
        <div class="value" style="color:#c62828">{{ statusData.overdue?.count || 0 }}</div>
        <div class="sub">笔</div>
      </div>
      <div class="kpi-card">
        <div class="label">当期笔数</div>
        <div class="value" style="color:#1565c0">{{ statusData.current?.count || 0 }}</div>
        <div class="sub">笔</div>
      </div>
      <div class="kpi-card">
        <div class="label">未到期笔数</div>
        <div class="value" style="color:#2e7d32">{{ statusData.not_due?.count || 0 }}</div>
        <div class="sub">笔</div>
      </div>
      <div class="kpi-card">
        <div class="label">已结清笔数</div>
        <div class="value" style="color:var(--muted)">{{ statusData.settled?.count || 0 }}</div>
        <div class="sub">笔</div>
      </div>
    </div>

    <!-- Charts grid -->
    <div class="charts-grid">
      <div class="card">
        <div class="section-title">应收账龄分析 <span class="tip">点击下钻</span></div>
        <BaseChart v-if="agingOption" :option="agingOption" height="280px" @click="onAgingClick" />
        <div v-else class="empty"><div class="icon">📊</div>暂无数据</div>
      </div>
      <div class="card">
        <div class="section-title">应收状态分布</div>
        <BaseChart v-if="statusOption" :option="statusOption" height="280px" />
        <div v-else class="empty"><div class="icon">📊</div>暂无数据</div>
      </div>
      <div class="card" style="grid-column:span 2">
        <div class="section-title">月度回款率（{{ selectedYear }}年）</div>
        <BaseChart v-if="collRateOption" :option="collRateOption" height="300px" />
        <div v-else class="empty"><div class="icon">📈</div>暂无数据</div>
      </div>
      <div class="card" style="grid-column:span 2">
        <div class="section-title">未收 Top 10 项目 <span class="tip">点击跳转</span></div>
        <BaseChart v-if="topOption" :option="topOption" height="280px" @click="onTopClick" />
        <div v-else class="empty"><div class="icon">📊</div>暂无数据</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.charts-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
@media (max-width: 900px) { .charts-grid { grid-template-columns: 1fr; } .charts-grid .card[style*='span 2'] { grid-column: span 1; } }
.tip { font-size: 11px; color: var(--muted); font-weight: 400; margin-left: 8px; cursor: default; }
.kpi-4 { grid-template-columns: repeat(4,1fr) !important; }
@media (max-width: 700px) { .kpi-4 { grid-template-columns: repeat(2,1fr) !important; } }
</style>
