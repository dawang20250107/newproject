<script setup>
import { ref, computed, reactive, onMounted, watch } from 'vue'
import { useAuthStore } from '../../stores/auth.js'
import { DEPARTMENTS } from '../../constants.js'
import ar from '../../api/ar.js'
import BaseChart from '../../components/ar/BaseChart.vue'

const auth = useAuthStore()

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
const viewMode = ref('total')  // total | by_dept
const cfData = ref(null)
const loading = ref(false)

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
}

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

// Initialize depts to all accessible
onMounted(() => {
  filters.depts = [...accessibleDepts.value]
  load()
})

const hasAlert = computed(() => cfData.value?.has_alert)
const alertMonths = computed(() => {
  if (!cfData.value) return []
  const months = []
  if (viewMode.value === 'total') {
    months.push(...(cfData.value.totals?.alert_months || []))
  } else {
    cfData.value.by_dept?.forEach(d => d.alert_months?.forEach(m => {
      if (!months.includes(`${d.dept}·${m}`)) months.push(`${d.dept}·${m}`)
    }))
  }
  return months
})

function makeCashflowOption(months, collected, paid, budgetColl, budgetPaid) {
  return {
    tooltip: {
      trigger: 'axis', axisPointer: { type: 'shadow' },
      formatter(params) {
        let html = `<b>${params[0].axisValueLabel}</b><br/>`
        params.forEach(p => {
          const color = p.color?.colorStops ? p.color.colorStops[0].color : p.color
          html += `<span style="color:${color}">●</span> ${p.seriesName}：${fmtWan(p.value)}<br/>`
        })
        const cIdx = params.findIndex(p => p.seriesName === '实收')
        const pIdx = params.findIndex(p => p.seriesName === '实付')
        if (cIdx !== -1 && pIdx !== -1 && params[pIdx].value > params[cIdx].value) {
          html += `<span style="color:#c62828;font-weight:700">⚠ 付款超收款</span>`
        }
        return html
      }
    },
    legend: { bottom: 0, data: ['实收', '实付', '收款预算', '付款预算'] },
    grid: { top: 16, right: 16, bottom: 48, left: 16, containLabel: true },
    xAxis: { type: 'category', data: months },
    yAxis: { type: 'value', axisLabel: { formatter: v => fmtWan(v) } },
    series: [
      { name: '实收', type: 'bar', barGap: '10%', barMaxWidth: 28,
        data: collected,
        itemStyle: { color: '#2e7d32', borderRadius: [4, 4, 0, 0] } },
      { name: '实付', type: 'bar', barMaxWidth: 28,
        data: paid.map((v, i) => ({
          value: v,
          itemStyle: {
            color: v > 0 && v > collected[i] ? '#c62828' : '#f57f17',
            borderRadius: [4, 4, 0, 0],
          }
        })) },
      { name: '收款预算', type: 'line', data: budgetColl, smooth: true,
        lineStyle: { type: 'dashed', color: '#2e7d32', width: 1.5 }, symbol: 'none' },
      { name: '付款预算', type: 'line', data: budgetPaid, smooth: true,
        lineStyle: { type: 'dashed', color: '#f57f17', width: 1.5 }, symbol: 'none' },
    ],
  }
}

const totalOption = computed(() => {
  if (!cfData.value) return null
  const t = cfData.value.totals
  return makeCashflowOption(cfData.value.months, t.collected, t.paid, t.budget_collection, t.budget_payment)
})

function deptOption(deptRow) {
  return makeCashflowOption(cfData.value.months, deptRow.collected, deptRow.paid,
    deptRow.budget_collection, deptRow.budget_payment)
}
</script>

<template>
  <div>
    <div class="topbar">
      <h1>收付对比</h1>
      <div class="ctrl-row" style="flex-wrap:wrap">
        <span style="font-size:13px;color:var(--muted)">从</span>
        <select v-model="filters.start_year" class="sel-yr">
          <option v-for="y in years" :key="y" :value="y">{{ y }}</option>
        </select>
        <select v-model="filters.start_month" class="sel-mo">
          <option v-for="m in months" :key="m" :value="m">{{ m }}月</option>
        </select>
        <span style="font-size:13px;color:var(--muted)">至</span>
        <select v-model="filters.end_year" class="sel-yr">
          <option v-for="y in years" :key="y" :value="y">{{ y }}</option>
        </select>
        <select v-model="filters.end_month" class="sel-mo">
          <option v-for="m in months" :key="m" :value="m">{{ m }}月</option>
        </select>
        <button class="btn btn-primary btn-sm" :disabled="loading" @click="load">{{ loading ? '加载中…' : '查询' }}</button>
        <div class="ctrl-sep"></div>
        <button :class="['tab-btn', viewMode === 'total' ? 'active' : '']" @click="viewMode = 'total'">汇总视图</button>
        <button :class="['tab-btn', viewMode === 'by_dept' ? 'active' : '']" @click="viewMode = 'by_dept'">分事业部</button>
      </div>
    </div>

    <!-- Dept chips -->
    <div class="card" style="padding:12px 16px">
      <div style="font-size:12px;color:var(--muted);margin-bottom:8px">事业部筛选（可多选）</div>
      <div style="display:flex;flex-wrap:wrap;gap:6px">
        <button
          v-for="d in accessibleDepts" :key="d"
          :class="['dept-chip', filters.depts.includes(d) ? 'on' : '']"
          @click="toggleDept(d)"
        >{{ d }}</button>
      </div>
    </div>

    <!-- Alert banner -->
    <div v-if="hasAlert && cfData" class="cashflow-alert">
      <span class="alert-icon">⚠</span>
      <div>
        <div class="alert-title">付款超出收款告警</div>
        <div class="alert-months">以下期间付款金额超出实际收款：{{ alertMonths.join('、') }}</div>
      </div>
    </div>

    <!-- Total view -->
    <div v-if="viewMode === 'total'" class="card">
      <div class="section-title">收付汇总（全选事业部）</div>
      <BaseChart v-if="totalOption" :option="totalOption" height="360px" />
      <div v-else-if="!loading" class="empty"><div class="icon">📊</div>暂无数据，请选择查询范围</div>
      <div v-else class="empty"><div class="icon">⏳</div>加载中…</div>

      <!-- Summary table -->
      <div v-if="cfData?.months?.length" style="margin-top:16px">
        <div class="section-title">月度明细</div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>月份</th>
                <th class="amt">实收</th>
                <th class="amt">实付</th>
                <th class="amt">收款预算</th>
                <th class="amt">付款预算</th>
                <th class="amt">净现金流</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(ym, i) in cfData.months" :key="ym"
                  :class="{ 'row-alert': cfData.totals.paid[i] > cfData.totals.collected[i] && cfData.totals.collected[i] > 0 }">
                <td>{{ ym }}</td>
                <td class="amt">{{ fmtWan(cfData.totals.collected[i]) }}</td>
                <td class="amt" :class="cfData.totals.paid[i] > cfData.totals.collected[i] ? 'text-danger' : ''">
                  {{ fmtWan(cfData.totals.paid[i]) }}
                </td>
                <td class="amt muted">{{ fmtWan(cfData.totals.budget_collection[i]) }}</td>
                <td class="amt muted">{{ fmtWan(cfData.totals.budget_payment[i]) }}</td>
                <td class="amt" :class="cfData.totals.collected[i] - cfData.totals.paid[i] >= 0 ? 'text-ok' : 'text-danger'">
                  {{ fmtWan(cfData.totals.collected[i] - cfData.totals.paid[i]) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- By dept view -->
    <template v-else-if="cfData">
      <div v-for="dRow in cfData.by_dept" :key="dRow.dept" class="card">
        <div class="section-title">
          {{ dRow.dept }}
          <span v-if="dRow.alert_months?.length" class="dept-alert-badge">⚠ {{ dRow.alert_months.join('、') }} 付款超收款</span>
        </div>
        <BaseChart :option="deptOption(dRow)" height="300px" />
      </div>
    </template>
  </div>
</template>

<style scoped>
.dept-chip {
  padding: 4px 14px; border-radius: 14px; font-size: 12px; cursor: pointer;
  border: 1.5px solid var(--border); background: rgba(255,253,250,.7); color: var(--muted);
  transition: all .16s;
}
.dept-chip.on { border-color: var(--primary); background: rgba(201,99,66,.1); color: var(--primary); font-weight: 600; }
.dept-chip:hover { border-color: var(--primary); color: var(--primary); }
.cashflow-alert {
  display: flex; align-items: flex-start; gap: 14px;
  padding: 16px 20px; margin: 0 0 16px;
  background: rgba(198,40,40,.06); border: 1.5px solid rgba(198,40,40,.25);
  border-radius: 12px; animation: alertGlow 1.4s ease-in-out infinite;
}
@keyframes alertGlow {
  0%,100% { box-shadow: 0 2px 12px rgba(198,40,40,.1); border-color: rgba(198,40,40,.25); }
  50% { box-shadow: 0 4px 24px rgba(198,40,40,.28); border-color: rgba(198,40,40,.5); background: rgba(198,40,40,.1); }
}
.alert-icon { font-size: 22px; flex-shrink: 0; margin-top: 2px; }
.alert-title { font-weight: 700; color: #c62828; font-size: 14px; }
.alert-months { font-size: 12px; color: #c62828; margin-top: 4px; opacity: .85; }
.row-alert { background: rgba(198,40,40,.04); }
.tab-btn { padding: 6px 14px; border-radius: 8px; font-size: 13px; border: 1.5px solid var(--border); background: rgba(255,253,250,.6); color: var(--muted); cursor: pointer; }
.tab-btn.active { border-color: var(--primary); background: rgba(201,99,66,.1); color: var(--primary); font-weight: 600; }
.text-danger { color: #c62828; font-weight: 600; }
.text-ok { color: #2e7d32; }
.muted { color: var(--muted); }
.dept-alert-badge { font-size: 11px; color: #c62828; font-weight: 600; margin-left: 10px; padding: 2px 8px; background: rgba(198,40,40,.08); border-radius: 8px; }
</style>
