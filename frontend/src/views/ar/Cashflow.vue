<script setup>
import { ref, computed, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../../stores/auth.js'
import { DEPARTMENTS } from '../../constants.js'
import ar from '../../api/ar.js'
import BaseChart from '../../components/ar/BaseChart.vue'

const auth = useAuthStore()
const router = useRouter()

const now = new Date()
const filters = reactive({
  start_year: now.getFullYear(),
  start_month: 1,
  end_year: now.getFullYear(),
  end_month: now.getMonth() + 1,
  depts: [],
})

const accessibleDepts = computed(() =>
  auth.isSuperAdmin ? DEPARTMENTS : (auth.user?.departments || []).filter(d => DEPARTMENTS.includes(d)))

const years = Array.from({ length: 5 }, (_, i) => now.getFullYear() - 2 + i)
const months = Array.from({ length: 12 }, (_, i) => i + 1)
const cfData = ref(null)
const loading = ref(false)

// 超期/催收 reminder (portfolio-wide, independent of date range)
const overdue = ref(null)
const keyCollection = ref([])

function fmtWan(v) {
  const n = Math.abs(parseFloat(v) || 0)
  if (n >= 1e8) return (v / 1e8).toFixed(2) + '亿'
  if (n >= 1e4) return (v / 1e4).toFixed(2) + '万'
  return String(Math.round(v))
}

function toggleDept(d) {
  const idx = filters.depts.indexOf(d)
  if (idx === -1) filters.depts.push(d)
  else filters.depts.splice(idx, 1)
  load()
}

function selectAllDepts() { filters.depts = [...accessibleDepts.value]; load() }
function clearDepts() { filters.depts = []; load() }

async function load() {
  loading.value = true
  try {
    const res = await ar.cashflow({
      start_year: filters.start_year,
      start_month: filters.start_month,
      end_year: filters.end_year,
      end_month: filters.end_month,
      depts: filters.depts.length ? filters.depts.join(',') : undefined,
    })
    cfData.value = res.data
  } catch (e) {
    console.error(e)
  } finally { loading.value = false }
}

async function loadReminder() {
  try {
    const [sd, top] = await Promise.all([ar.statusDist({}), ar.outstandingTop({ n: 5 })])
    overdue.value = sd.data.overdue
    keyCollection.value = top.data
  } catch (e) {
    overdue.value = null; keyCollection.value = []
  }
}

onMounted(() => {
  filters.depts = [...accessibleDepts.value]
  load()
  loadReminder()
})

// ── KPI roll-ups ────────────────────────────────────────────────────────────────
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

// ── Chart options ────────────────────────────────────────────────────────────────
// 1. 收付与预算达成对比
const budgetOption = computed(() => {
  if (!cfData.value) return null
  const t = cfData.value.totals
  return {
    tooltip: {
      trigger: 'axis', axisPointer: { type: 'shadow' },
      formatter(params) {
        let html = `<b>${params[0].axisValueLabel}</b><br/>`
        params.forEach(p => {
          const color = p.color?.colorStops ? p.color.colorStops[0].color : p.color
          html += `<span style="color:${color}">●</span> ${p.seriesName}：${fmtWan(p.value)}<br/>`
        })
        return html
      }
    },
    legend: { bottom: 0, data: ['实收', '实付', '收款预算', '付款预算'] },
    grid: { top: 16, right: 16, bottom: 48, left: 16, containLabel: true },
    xAxis: { type: 'category', data: cfData.value.months },
    yAxis: { type: 'value', axisLabel: { formatter: v => fmtWan(v) } },
    series: [
      { name: '实收', type: 'bar', barGap: '10%', barMaxWidth: 26, data: t.collected,
        itemStyle: { color: '#2e7d32', borderRadius: [4, 4, 0, 0] } },
      { name: '实付', type: 'bar', barMaxWidth: 26,
        data: t.paid.map((v, i) => ({ value: v,
          itemStyle: { color: v > 0 && v > t.collected[i] ? '#c62828' : '#f57f17', borderRadius: [4, 4, 0, 0] } })) },
      { name: '收款预算', type: 'line', data: t.budget_collection, smooth: true,
        lineStyle: { type: 'dashed', color: '#2e7d32', width: 1.5 }, symbol: 'none' },
      { name: '付款预算', type: 'line', data: t.budget_payment, smooth: true,
        lineStyle: { type: 'dashed', color: '#f57f17', width: 1.5 }, symbol: 'none' },
    ],
  }
})

// 2. 净现金流趋势
const netOption = computed(() => {
  if (!cfData.value) return null
  const t = cfData.value.totals
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' },
      formatter: p => `${p[0].axisValueLabel}<br/>净现金流：${fmtWan(p[0].value)}` },
    grid: { top: 16, right: 16, bottom: 24, left: 16, containLabel: true },
    xAxis: { type: 'category', data: cfData.value.months },
    yAxis: { type: 'value', axisLabel: { formatter: v => fmtWan(v) } },
    series: [{
      type: 'bar', barMaxWidth: 30,
      data: (t.net || []).map(v => ({ value: v,
        itemStyle: { color: v >= 0 ? '#2e7d32' : '#c62828', borderRadius: v >= 0 ? [4, 4, 0, 0] : [0, 0, 4, 4] } })),
      markLine: { silent: true, symbol: 'none', lineStyle: { color: 'rgba(0,0,0,0.25)' }, data: [{ yAxis: 0 }] },
    }],
  }
})

// 3. 累计现金流曲线
const cumulativeOption = computed(() => {
  if (!cfData.value) return null
  const t = cfData.value.totals
  return {
    tooltip: { trigger: 'axis',
      formatter: p => `${p[0].axisValueLabel}<br/>累计净现金流：${fmtWan(p[0].value)}` },
    grid: { top: 16, right: 16, bottom: 24, left: 16, containLabel: true },
    xAxis: { type: 'category', boundaryGap: false, data: cfData.value.months },
    yAxis: { type: 'value', axisLabel: { formatter: v => fmtWan(v) } },
    series: [{
      type: 'line', smooth: true, data: t.cumulative_net || [],
      symbol: 'circle', symbolSize: 6,
      lineStyle: { color: '#1565c0', width: 2.5 }, itemStyle: { color: '#1565c0' },
      areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
        colorStops: [{ offset: 0, color: 'rgba(21,101,192,0.28)' }, { offset: 1, color: 'rgba(21,101,192,0.02)' }] } },
      markLine: { silent: true, symbol: 'none', lineStyle: { color: 'rgba(0,0,0,0.25)' }, data: [{ yAxis: 0 }] },
    }],
  }
})
</script>

<template>
  <div>
    <div class="topbar">
      <div>
        <h1>现金流分析</h1>
        <div style="font-size:13px;color:var(--muted);margin-top:2px">财务驾驶舱 · 预算达成 · 净现金流 · 累计走势</div>
      </div>
    </div>

    <!-- Filter strip (single source of truth: date range + dept multi-select) -->
    <div class="filter-strip">
      <span class="fs-label">区间</span>
      <select v-model="filters.start_year" class="sel-yr" @change="load"><option v-for="y in years" :key="y" :value="y">{{ y }}</option></select>
      <select v-model="filters.start_month" class="sel-mo" @change="load"><option v-for="m in months" :key="m" :value="m">{{ m }}月</option></select>
      <span class="fs-sep">至</span>
      <select v-model="filters.end_year" class="sel-yr" @change="load"><option v-for="y in years" :key="y" :value="y">{{ y }}</option></select>
      <select v-model="filters.end_month" class="sel-mo" @change="load"><option v-for="m in months" :key="m" :value="m">{{ m }}月</option></select>
      <div class="ctrl-sep"></div>
      <span class="fs-label">事业部</span>
      <button class="chip-mini" @click="selectAllDepts">全选</button>
      <button class="chip-mini" @click="clearDepts">清空</button>
      <button v-for="d in accessibleDepts" :key="d"
        :class="['dept-chip', filters.depts.includes(d) ? 'on' : '']" @click="toggleDept(d)">{{ d }}</button>
      <span v-if="loading" class="fs-loading">加载中…</span>
    </div>

    <!-- 超期 / 重点催收 强提醒 -->
    <div v-if="overdue && overdue.count" class="urge-banner">
      <div class="urge-left">
        <div class="urge-icon">⚠</div>
        <div>
          <div class="urge-title">超期强提醒 · {{ overdue.count }} 笔逾期待催收</div>
          <div class="urge-sub">逾期未收合计 <b>{{ fmtWan(overdue.amount) }} 元</b></div>
        </div>
      </div>
      <div class="urge-right">
        <div v-if="keyCollection.length" class="urge-key">
          <span class="urge-key-label">重点催收</span>
          <span v-for="p in keyCollection" :key="p.project_id" class="urge-chip"
            @click="router.push({ path: '/ar/records', query: { project_id: p.project_id } })">
            {{ p.short_name?.length > 8 ? p.short_name.slice(0,8) + '…' : p.short_name }} <b>{{ fmtWan(p.total_outstanding) }}</b>
          </span>
        </div>
        <button class="urge-btn" @click="router.push({ path: '/ar/records', query: { status: 'overdue' } })">查看逾期明细</button>
      </div>
    </div>

    <!-- 付款超收款 alert -->
    <div v-if="hasAlert" class="cashflow-alert">
      <span class="alert-icon">⚠</span>
      <div>
        <div class="alert-title">付款超出收款告警</div>
        <div class="alert-months">以下期间付款金额超出实际收款：{{ alertMonths.join('、') }}</div>
      </div>
    </div>

    <!-- KPI cards -->
    <div class="cockpit-kpis">
      <div class="ck-card ck-coll">
        <div class="ck-label">区间实收</div>
        <div class="ck-value">{{ fmtWan(sumColl) }}</div>
        <div class="ck-sub" v-if="collAchieve !== null">预算达成 {{ collAchieve.toFixed(1) }}%</div>
        <div class="ck-sub" v-else>无预算基准</div>
      </div>
      <div class="ck-card ck-pay">
        <div class="ck-label">区间实付</div>
        <div class="ck-value">{{ fmtWan(sumPaid) }}</div>
        <div class="ck-sub" v-if="payAchieve !== null">预算达成 {{ payAchieve.toFixed(1) }}%</div>
        <div class="ck-sub" v-else>无预算基准</div>
      </div>
      <div class="ck-card" :class="netTotal >= 0 ? 'ck-net-pos' : 'ck-net-neg'">
        <div class="ck-label">区间净现金流</div>
        <div class="ck-value" :class="netTotal >= 0 ? 'v-pos' : 'v-neg'">{{ netTotal >= 0 ? '+' : '-' }}{{ fmtWan(netTotal) }}</div>
        <div class="ck-sub">实收 − 实付</div>
      </div>
      <div class="ck-card" :class="endCumulative >= 0 ? 'ck-net-pos' : 'ck-net-neg'">
        <div class="ck-label">期末累计净现金流</div>
        <div class="ck-value" :class="endCumulative >= 0 ? 'v-pos' : 'v-neg'">{{ endCumulative >= 0 ? '+' : '-' }}{{ fmtWan(endCumulative) }}</div>
        <div class="ck-sub">资金池走势终值</div>
      </div>
    </div>

    <!-- Chart grid -->
    <div class="cockpit-grid">
      <div class="card span2">
        <div class="section-title">收付与预算达成对比</div>
        <BaseChart v-if="budgetOption" :option="budgetOption" height="320px" />
        <div v-else-if="!loading" class="empty"><div class="icon">📊</div>暂无数据</div>
        <div v-else class="empty"><div class="icon">⏳</div>加载中…</div>
      </div>
      <div class="card">
        <div class="section-title">净现金流趋势</div>
        <BaseChart v-if="netOption" :option="netOption" height="280px" />
        <div v-else class="empty"><div class="icon">📊</div>暂无数据</div>
      </div>
      <div class="card">
        <div class="section-title">累计现金流曲线</div>
        <BaseChart v-if="cumulativeOption" :option="cumulativeOption" height="280px" />
        <div v-else class="empty"><div class="icon">📈</div>暂无数据</div>
      </div>
    </div>

    <!-- Monthly detail table -->
    <div v-if="cfData?.months?.length" class="card" style="margin-top:16px">
      <div class="section-title">月度明细</div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>月份</th><th class="amt">实收</th><th class="amt">实付</th>
              <th class="amt">收款预算</th><th class="amt">付款预算</th>
              <th class="amt">净现金流</th><th class="amt">累计净现金流</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(ym, i) in cfData.months" :key="ym"
                :class="{ 'row-alert': cfData.totals.paid[i] > cfData.totals.collected[i] && cfData.totals.collected[i] > 0 }">
              <td>{{ ym }}</td>
              <td class="amt">{{ fmtWan(cfData.totals.collected[i]) }}</td>
              <td class="amt" :class="cfData.totals.paid[i] > cfData.totals.collected[i] ? 'text-danger' : ''">{{ fmtWan(cfData.totals.paid[i]) }}</td>
              <td class="amt muted">{{ fmtWan(cfData.totals.budget_collection[i]) }}</td>
              <td class="amt muted">{{ fmtWan(cfData.totals.budget_payment[i]) }}</td>
              <td class="amt" :class="cfData.totals.net[i] >= 0 ? 'text-ok' : 'text-danger'">{{ fmtWan(cfData.totals.net[i]) }}</td>
              <td class="amt" :class="cfData.totals.cumulative_net[i] >= 0 ? 'text-ok' : 'text-danger'">{{ fmtWan(cfData.totals.cumulative_net[i]) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<style scoped>
.filter-strip { gap: 8px; }
.fs-label { font-size: 12px; color: var(--muted); font-weight: 600; }
.fs-sep { font-size: 12px; color: var(--muted); }
.fs-loading { font-size: 12px; color: var(--primary); margin-left: auto; }
.chip-mini { font-size: 11px; padding: 3px 9px; border-radius: 8px; border: 1px solid var(--border); background: var(--bg2); color: var(--muted); cursor: pointer; }
.chip-mini:hover { border-color: var(--primary); color: var(--primary); }
.dept-chip {
  padding: 4px 12px; border-radius: 12px; font-size: 12px; cursor: pointer;
  border: 1.5px solid var(--border); background: rgba(255,253,250,.7); color: var(--muted); transition: all .16s;
}
.dept-chip.on { border-color: var(--primary); background: rgba(201,99,66,.1); color: var(--primary); font-weight: 600; }
.dept-chip:hover { border-color: var(--primary); color: var(--primary); }

/* 超期 / 催收 strong reminder (GPU-composited pulse) */
.urge-banner {
  display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap;
  padding: 14px 20px; margin-bottom: 16px; border-radius: 14px;
  background: rgba(198,40,40,.07); border: 1.5px solid rgba(198,40,40,.35);
  box-shadow: 0 2px 14px rgba(198,40,40,.12); animation: urgePulse 1.7s ease-in-out infinite; will-change: opacity;
}
@keyframes urgePulse { 0%,100% { opacity: 1; } 50% { opacity: .72; } }
.urge-left { display: flex; align-items: center; gap: 12px; }
.urge-icon { font-size: 24px; }
.urge-title { font-weight: 700; color: #c62828; font-size: 14px; }
.urge-sub { font-size: 12.5px; color: #c62828; opacity: .9; margin-top: 2px; }
.urge-right { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.urge-key { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.urge-key-label { font-size: 11px; color: #c62828; font-weight: 600; }
.urge-chip { display: inline-flex; align-items: center; gap: 5px; font-size: 11.5px; padding: 3px 10px; border-radius: 12px; background: rgba(255,255,255,.6); border: 1px solid rgba(198,40,40,.3); color: #c62828; cursor: pointer; transition: all .14s; }
.urge-chip:hover { background: #c62828; color: #fff; }
.urge-btn { padding: 7px 16px; border-radius: 9px; border: none; background: #c62828; color: #fff; font-size: 13px; font-weight: 600; cursor: pointer; white-space: nowrap; transition: filter .14s; }
.urge-btn:hover { filter: brightness(1.08); }

/* 付款超收款 alert (opacity-only animation, no repaint) */
.cashflow-alert {
  display: flex; align-items: flex-start; gap: 14px; padding: 14px 20px; margin: 0 0 16px;
  background: rgba(245,127,23,.08); border: 1.5px solid rgba(245,127,23,.35); border-radius: 12px;
}
.alert-icon { font-size: 20px; flex-shrink: 0; }
.alert-title { font-weight: 700; color: #e65100; font-size: 13.5px; }
.alert-months { font-size: 12px; color: #e65100; margin-top: 3px; opacity: .9; }

/* KPI cards */
.cockpit-kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 16px; }
@media (max-width: 820px) { .cockpit-kpis { grid-template-columns: repeat(2, 1fr); } }
.ck-card { background: rgba(255,255,255,0.72); border: 1px solid rgba(255,255,255,0.8); border-radius: 14px; padding: 16px 18px; box-shadow: 0 2px 14px rgba(0,0,0,0.06); backdrop-filter: blur(10px); border-left: 3px solid var(--muted); }
.ck-coll { border-left-color: #2e7d32; }
.ck-pay { border-left-color: #f57f17; }
.ck-net-pos { border-left-color: #2e7d32; }
.ck-net-neg { border-left-color: #c62828; }
.ck-label { font-size: 11px; color: var(--muted); font-weight: 600; letter-spacing: .04em; }
.ck-value { font-size: 24px; font-weight: 800; color: var(--text); line-height: 1.1; margin-top: 6px; }
.ck-coll .ck-value { color: #2e7d32; }
.ck-pay .ck-value { color: #e65100; }
.v-pos { color: #2e7d32 !important; }
.v-neg { color: #c62828 !important; }
.ck-sub { font-size: 11.5px; color: var(--muted); margin-top: 5px; }

/* Chart grid */
.cockpit-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.cockpit-grid .span2 { grid-column: span 2; }
@media (max-width: 900px) { .cockpit-grid { grid-template-columns: 1fr; } .cockpit-grid .span2 { grid-column: span 1; } }

.row-alert { background: rgba(198,40,40,.04); }
.text-danger { color: #c62828; font-weight: 600; }
.text-ok { color: #2e7d32; }
.muted { color: var(--muted); }
.amt { text-align: right; }
</style>
