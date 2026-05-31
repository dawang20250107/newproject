<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../../stores/auth.js'
import { DEPARTMENTS, yearCST } from '../../constants.js'
import ar from '../../api/ar.js'
import { fmtCompact } from '../../utils/format.js'
import { valueAxis, catAxis, gridFor, bottomLegend } from '../../utils/chartTheme.js'
import EmptyState from '../../components/EmptyState.vue'
import BaseChart from '../../components/ar/BaseChart.vue'

const auth = useAuthStore()
const router = useRouter()

const selectedDept = ref('')
const selectedYear = ref(yearCST())
const years = Array.from({ length: 5 }, (_, i) => yearCST() - 2 + i)
const accessibleDepts = computed(() => auth.effectiveDepts.filter(d => DEPARTMENTS.includes(d)))

// ── Chart data ────────────────────────────────────────────────────────────────
const agingData = ref(null)
const collRateData = ref(null)
const topData = ref(null)
const statusData = ref(null)
const pmData = ref(null)

// 亿/万 两级单位（无空格，一位小数），万元以下取整；空值显示「0」
const fmtWan = (v) => fmtCompact(v, { decimals: 1, smallRound: true, dash: '0' })

async function loadAll() {
  const params = { dept: selectedDept.value }
  const [a, c, t, s, p] = await Promise.allSettled([
    ar.aging(params),
    ar.collectionRate({ year: selectedYear.value, ...params }),
    ar.outstandingTop({ ...params, n: 10 }),
    ar.statusDist(params),
    ar.analyticsByPm({ year: selectedYear.value, ...params }),
  ])
  if (a.status === 'fulfilled') agingData.value = a.value.data
  if (c.status === 'fulfilled') collRateData.value = c.value.data
  if (t.status === 'fulfilled') topData.value = t.value.data
  if (s.status === 'fulfilled') statusData.value = s.value.data
  if (p.status === 'fulfilled') pmData.value = p.value.data
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
    grid: { top: 16, right: 84, bottom: 8, left: 16, containLabel: true },
    xAxis: { type: 'value', axisLabel: { color: '#9b8070', formatter: v => fmtWan(v) } },
    yAxis: { type: 'category', data: labels, axisLabel: { color: '#9b8070', width: 96, overflow: 'truncate' } },
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
    legend: bottomLegend({ data: ['应收基础', '已收', '回款率'] }),
    grid: gridFor(mLabels, { nameTop: true, threshold: 12, right: 52 }),
    xAxis: catAxis(mLabels, { threshold: 12 }),
    yAxis: [
      valueAxis({ formatter: v => fmtWan(v) }),
      valueAxis({ name: '回款率%', position: 'right', min: 0, max: 100, formatter: v => v + '%' }),
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
    grid: { top: 8, right: 84, bottom: 8, left: 16, containLabel: true },
    xAxis: { type: 'value', axisLabel: { color: '#9b8070', formatter: v => fmtWan(v) } },
    yAxis: { type: 'category', data: names, axisLabel: { color: '#9b8070', width: 128, overflow: 'truncate' } },
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
  const statusMap = { 'current': 'current', '1_30': 'overdue', '31_60': 'overdue', '61_90': 'overdue', '90plus': 'overdue' }
  openDetail(statusMap[bucket.key] || '', `${bucket.label} 明细`)
}

function onTopClick(p) {
  const idx = topData.value.length - 1 - p.dataIndex
  const proj = topData.value[idx]
  router.push({ path: '/ar/records', query: { project_id: proj.project_id } })
}

// ── Drill-down detail modal ────────────────────────────────────────────────────
const detail = ref({ open: false, title: '', loading: false, items: [] })

async function openDetail(status, title) {
  detail.value = { open: true, title, loading: true, items: [] }
  try {
    const res = await ar.listRecords({ dept: selectedDept.value, status, size: 200 })
    detail.value.items = res.data.items
  } catch (e) {
    detail.value.items = []
  } finally {
    detail.value.loading = false
  }
}

// 重点催收 = 未收 Top 项目（取前 3）
const keyCollection = computed(() => (topData.value || []).slice(0, 3))

const pmOption = computed(() => {
  const data = pmData.value
  if (!data || !data.length) return null
  const sorted = [...data].sort((a, b) => b.outstanding - a.outstanding).slice(0, 15)
  const names = sorted.map(d => d.pm).reverse()
  return {
    tooltip: {
      trigger: 'axis', axisPointer: { type: 'shadow' },
      backgroundColor: 'rgba(255,255,255,0.97)', borderColor: 'rgba(0,0,0,0.08)', textStyle: { fontSize: 12 },
      formatter: params => {
        const idx = sorted.length - 1 - params[0].dataIndex
        const d = sorted[idx]
        return `<b>${d.pm}</b><br/>
          已收: <b>${fmtWan(d.collected)}</b><br/>
          未收: <b style="color:#e65100">${fmtWan(d.outstanding)}</b><br/>
          上账: ${fmtWan(d.estimated)}<br/>
          回款率: <b>${d.rate.toFixed(1)}%</b>  项目数: ${d.project_count}`
      },
    },
    grid: { top: 8, right: 104, bottom: 8, left: 16, containLabel: true },
    xAxis: { type: 'value', axisLabel: { formatter: v => fmtWan(v), fontSize: 11, color: '#9b8070' } },
    yAxis: { type: 'category', data: names, axisLabel: { fontSize: 11, color: '#6b5a4a', width: 120, overflow: 'truncate' } },
    series: [
      { name: '已收', type: 'bar', stack: 'total', barMaxWidth: 20,
        data: sorted.map(d => d.collected).reverse(),
        itemStyle: { color: { type: 'linear', x: 0, y: 0, x2: 1, y2: 0,
          colorStops: [{ offset: 0, color: '#2e7d32' }, { offset: 1, color: '#66bb6a' }] },
          borderRadius: [0, 0, 0, 0] } },
      { name: '未收', type: 'bar', stack: 'total', barMaxWidth: 20,
        data: sorted.map(d => d.outstanding).reverse(),
        itemStyle: { color: { type: 'linear', x: 0, y: 0, x2: 1, y2: 0,
          colorStops: [{ offset: 0, color: '#e65100' }, { offset: 1, color: '#ffa726' }] },
          borderRadius: [0, 4, 4, 0] },
        label: { show: true, position: 'right',
          formatter: p => { const d = sorted[sorted.length - 1 - p.dataIndex]; return `${d.rate.toFixed(0)}%` },
          fontSize: 11, color: '#555' } },
    ],
  }
})

watch([selectedDept, selectedYear], loadAll)
const onScopeChange = () => {
  if (selectedDept.value && !accessibleDepts.value.includes(selectedDept.value)) selectedDept.value = ''
  loadAll()
}
onMounted(() => { loadAll(); window.addEventListener('pk:depts-changed', onScopeChange) })
onBeforeUnmount(() => window.removeEventListener('pk:depts-changed', onScopeChange))
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

    <!-- 超期 / 重点催收 强提醒 -->
    <div v-if="statusData && statusData.overdue?.count" class="urge-banner">
      <div class="urge-left">
        <div class="urge-icon">⚠</div>
        <div>
          <div class="urge-title">超期强提醒 · {{ statusData.overdue.count }} 笔逾期待催收</div>
          <div class="urge-sub">逾期未收合计 <b>{{ fmtWan(statusData.overdue.amount) }} 元</b>，请尽快跟进催收</div>
        </div>
      </div>
      <div class="urge-right">
        <div v-if="keyCollection.length" class="urge-key">
          <span class="urge-key-label">重点催收</span>
          <span v-for="p in keyCollection" :key="p.project_id" class="urge-chip"
            @click="$router.push({ path: '/ar/records', query: { project_id: p.project_id } })">
            {{ p.short_name?.length > 8 ? p.short_name.slice(0,8) + '…' : p.short_name }}
            <b>{{ fmtWan(p.total_outstanding) }}</b>
          </span>
        </div>
        <button class="urge-btn" @click="openDetail('overdue', '逾期明细')">查看逾期明细</button>
      </div>
    </div>

    <!-- Stats summary (clickable → drill-down) -->
    <div v-if="statusData" class="kpi-grid kpi-4" style="margin-bottom:16px">
      <div class="kpi-card clickable" style="border-left:3px solid #c62828" @click="openDetail('overdue', '逾期明细')">
        <div class="label">逾期 <span class="drill-hint">点击查看</span></div>
        <div class="value" style="color:#c62828">{{ statusData.overdue?.count || 0 }}</div>
        <div class="sub">{{ statusData.overdue?.amount ? fmtWan(statusData.overdue.amount) + ' 未收' : '—' }}</div>
      </div>
      <div class="kpi-card clickable" style="border-left:3px solid #1565c0" @click="openDetail('current', '当期明细')">
        <div class="label">当期 <span class="drill-hint">点击查看</span></div>
        <div class="value" style="color:#1565c0">{{ statusData.current?.count || 0 }}</div>
        <div class="sub">{{ statusData.current?.amount ? fmtWan(statusData.current.amount) : '—' }}</div>
      </div>
      <div class="kpi-card clickable" style="border-left:3px solid #2e7d32" @click="openDetail('not_due', '未到期明细')">
        <div class="label">未到期 <span class="drill-hint">点击查看</span></div>
        <div class="value" style="color:#2e7d32">{{ statusData.not_due?.count || 0 }}</div>
        <div class="sub">{{ statusData.not_due?.amount ? fmtWan(statusData.not_due.amount) : '—' }}</div>
      </div>
      <div class="kpi-card clickable" style="border-left:3px solid var(--muted)" @click="openDetail('settled', '已结清明细')">
        <div class="label">已结清 <span class="drill-hint">点击查看</span></div>
        <div class="value" style="color:var(--muted)">{{ statusData.settled?.count || 0 }}</div>
        <div class="sub">笔</div>
      </div>
    </div>

    <!-- Charts grid -->
    <div class="charts-grid">
      <div class="card">
        <div class="section-title">应收账龄分析 <span class="tip">点击下钻</span></div>
        <BaseChart v-if="agingOption" :option="agingOption" height="280px" @click="onAgingClick" />
        <EmptyState v-else icon="📊" text="暂无数据" />
      </div>
      <div class="card">
        <div class="section-title">应收状态分布</div>
        <BaseChart v-if="statusOption" :option="statusOption" height="280px" />
        <EmptyState v-else icon="📊" text="暂无数据" />
      </div>
      <div class="card" style="grid-column:span 2">
        <div class="section-title">月度回款率（{{ selectedYear }}年）</div>
        <BaseChart v-if="collRateOption" :option="collRateOption" height="300px" />
        <EmptyState v-else icon="📈" text="暂无数据" />
      </div>
      <div class="card" style="grid-column:span 2">
        <div class="section-title">未收 Top 10 项目 <span class="tip">点击跳转</span></div>
        <BaseChart v-if="topOption" :option="topOption" height="280px" @click="onTopClick" />
        <EmptyState v-else icon="📊" text="暂无数据" />
      </div>
      <!-- PM Dimension -->
      <div class="card" style="grid-column:span 2">
        <div class="section-title">项目负责人维度分析（{{ selectedYear }}年）<span class="tip">已收/未收堆叠 · 右侧显示回款率</span></div>
        <BaseChart v-if="pmOption" :option="pmOption" height="320px" />
        <EmptyState v-else icon="📊" text="暂无数据" />
        <!-- PM table -->
        <div v-if="pmData && pmData.length" class="pm-table-wrap">
          <table class="pm-table">
            <thead>
              <tr>
                <th>项目负责人</th>
                <th class="ctr">项目数</th>
                <th class="amt">上账金额</th>
                <th class="amt">已收</th>
                <th class="amt warn">未收</th>
                <th class="ctr">回款率</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="d in pmData" :key="d.pm">
                <td class="fw">{{ d.pm }}</td>
                <td class="ctr text-muted">{{ d.project_count }}</td>
                <td class="amt">{{ fmtWan(d.estimated) }}</td>
                <td class="amt ok">{{ fmtWan(d.collected) }}</td>
                <td class="amt warn">{{ fmtWan(d.outstanding) }}</td>
                <td class="ctr">
                  <span class="rate-pill" :class="d.rate >= 80 ? 'rate-ok' : d.rate >= 50 ? 'rate-mid' : 'rate-low'">
                    {{ d.rate.toFixed(1) }}%
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- Drill-down detail modal -->
    <Teleport to="body">
      <div v-if="detail.open" class="modal-overlay" @click.self="detail.open = false">
        <div class="modal-box" style="max-width:760px">
          <div class="modal-header">
            <div>
              <h3>{{ detail.title }}</h3>
              <div style="font-size:12px;color:var(--muted);margin-top:2px">{{ selectedDept || '全部事业部' }} · 共 {{ detail.items.length }} 条</div>
            </div>
            <button class="modal-close" @click="detail.open = false">✕</button>
          </div>
          <div class="modal-body">
            <EmptyState v-if="detail.loading" loading />
            <EmptyState v-else-if="!detail.items.length" empty text="暂无明细" />
            <div v-else class="table-wrap">
              <table class="detail-table">
                <thead>
                  <tr><th>项目</th><th class="ctr">年月</th><th class="amt">未收金额</th><th class="ctr">应收到期</th><th class="ctr">状态</th></tr>
                </thead>
                <tbody>
                  <tr v-for="r in detail.items" :key="r.id">
                    <td><div class="dt-name">{{ r.short_name || r.contract_name }}</div><div class="dt-no">{{ r.project_no }}</div></td>
                    <td class="ctr">{{ r.operation_year }}/{{ String(r.operation_month).padStart(2,'0') }}</td>
                    <td class="amt" :class="parseFloat(r.outstanding_amount) > 0 ? 'dt-warn' : 'dt-zero'">{{ fmtWan(r.outstanding_amount) }}</td>
                    <td class="ctr dt-muted">{{ r.due_date || '—' }}</td>
                    <td class="ctr">
                      <span v-if="r.is_overdue" class="dt-pill dt-danger">逾期{{ r.overdue_days }}天</span>
                      <span v-else-if="r.is_current" class="dt-pill dt-blue">当期</span>
                      <span v-else-if="r.invoice_status === '已结清'" class="dt-pill dt-ok">已结清</span>
                      <span v-else class="dt-pill dt-mut">未到期</span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
          <div class="modal-footer">
            <button class="btn btn-ghost" @click="detail.open = false">关闭</button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.charts-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
@media (max-width: 900px) { .charts-grid { grid-template-columns: 1fr; } .charts-grid .card[style*='span 2'] { grid-column: span 1; } }
.tip { font-size: 11px; color: var(--muted); font-weight: 400; margin-left: 8px; cursor: default; }
.kpi-4 { grid-template-columns: repeat(4,1fr) !important; }
@media (max-width: 700px) { .kpi-4 { grid-template-columns: repeat(2,1fr) !important; } }

/* clickable KPI cards */
.kpi-card.clickable { cursor: pointer; }
.kpi-card.clickable:hover { transform: translateY(-3px); }
.drill-hint { font-size: 10px; color: var(--muted); font-weight: 400; margin-left: 6px; opacity: 0.7; }

/* 超期 / 重点催收 strong reminder banner (GPU-composited pulse) */
.urge-banner {
  display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap;
  padding: 14px 20px; margin-bottom: 16px; border-radius: 14px;
  background: rgba(198,40,40,.07); border: 1.5px solid rgba(198,40,40,.35);
  box-shadow: 0 2px 14px rgba(198,40,40,.12);
  animation: urgePulse 1.7s ease-in-out infinite; will-change: opacity;
}
@keyframes urgePulse { 0%,100% { opacity: 1; } 50% { opacity: .72; } }
.urge-left { display: flex; align-items: center; gap: 12px; }
.urge-icon { font-size: 24px; }
.urge-title { font-weight: 700; color: #c62828; font-size: 14px; }
.urge-sub { font-size: 12.5px; color: #c62828; opacity: .9; margin-top: 2px; }
.urge-right { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.urge-key { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.urge-key-label { font-size: 11px; color: #c62828; font-weight: 600; }
.urge-chip {
  display: inline-flex; align-items: center; gap: 5px; font-size: 11.5px;
  padding: 3px 10px; border-radius: 12px; background: rgba(255,255,255,.6);
  border: 1px solid rgba(198,40,40,.3); color: #c62828; cursor: pointer; transition: all .14s;
}
.urge-chip:hover { background: #c62828; color: #fff; }
.urge-chip b { font-weight: 700; }
.urge-btn {
  padding: 7px 16px; border-radius: 9px; border: none; background: #c62828; color: #fff;
  font-size: 13px; font-weight: 600; cursor: pointer; white-space: nowrap; transition: filter .14s;
}
.urge-btn:hover { filter: brightness(1.08); }

/* PM table */
.pm-table-wrap { margin-top: 16px; border-top: 1px solid rgba(0,0,0,0.06); padding-top: 12px; }
.pm-table { width: 100%; font-size: 12.5px; }
.pm-table th { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .04em; color: var(--muted); padding: 7px 10px; background: rgba(0,0,0,0.02); }
.pm-table td { padding: 8px 10px; border-bottom: 1px solid rgba(0,0,0,0.04); vertical-align: middle; }
.pm-table tr:last-child td { border-bottom: none; }
.pm-table .ctr { text-align: center; }
.pm-table .amt { text-align: right; font-variant-numeric: tabular-nums; }
.pm-table .fw { font-weight: 600; }
.pm-table .text-muted { color: var(--muted); }
.pm-table .ok { color: #2e7d32; font-weight: 600; }
.pm-table .warn { color: #e65100; font-weight: 600; }
.rate-pill { display: inline-block; padding: 2px 9px; border-radius: 10px; font-size: 11.5px; font-weight: 700; }
.rate-ok  { background: rgba(46,125,50,0.1); color: #2e7d32; }
.rate-mid { background: rgba(245,127,23,0.1); color: #e65100; }
.rate-low { background: rgba(198,40,40,0.1); color: #c62828; }

/* detail modal table */
.detail-table { width: 100%; }
.detail-table th { font-size: 11px; font-weight: 700; text-transform: uppercase; color: var(--muted); padding: 8px 10px; background: rgba(0,0,0,0.02); }
.detail-table td { padding: 9px 10px; border-bottom: 1px solid rgba(0,0,0,0.04); }
.detail-table .ctr { text-align: center; }
.detail-table .amt { text-align: right; }
.dt-name { font-weight: 600; font-size: 13px; }
.dt-no { font-family: monospace; font-size: 11px; color: var(--muted); }
.dt-warn { color: #e65100; font-weight: 700; }
.dt-zero { color: var(--muted); }
.dt-muted { color: var(--muted); font-size: 12px; }
.dt-pill { font-size: 11px; padding: 2px 8px; border-radius: 12px; font-weight: 600; }
.dt-danger { background: rgba(198,40,40,.1); color: #c62828; }
.dt-blue { background: rgba(21,101,192,.1); color: #1565c0; }
.dt-ok { background: rgba(46,125,50,.1); color: #2e7d32; }
.dt-mut { background: rgba(0,0,0,.06); color: var(--muted); }
</style>
