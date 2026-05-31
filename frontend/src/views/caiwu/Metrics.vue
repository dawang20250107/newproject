<script setup>
import { ref, computed, reactive, onMounted } from 'vue'
import { useCaiwuAuth } from '../../composables/useCaiwuAuth.js'
import { BUSINESS_UNITS, yearCST, monthCST } from '../../constants.js'
import BaseChart from '../../components/caiwu/charts/BaseChart.vue'
import api from '../../api/caiwu.js'
import { fmtCompact, fmtPct } from '../../utils/format.js'
import EmptyState from '../../components/EmptyState.vue'

const auth = useCaiwuAuth()

const year = ref(yearCST())
const month = ref(monthCST())
const selectedBu = ref('')

const loading = ref(false)
const loadErr = ref('')
const saving = ref(false)
const saveMsg = ref('')

const metricsData = ref(null)         // /metrics response
const editModel = reactive({})        // bu -> { m_rev, m_prof, a_rev, a_prof } in 万元

const years = Array.from({ length: 5 }, (_, i) => yearCST() - 2 + i)
const months = Array.from({ length: 12 }, (_, i) => i + 1)

const accessibleBus = computed(() => {
  if (auth.isAdmin) return BUSINESS_UNITS
  return (auth.user?.departments || []).filter(d => BUSINESS_UNITS.includes(d))
})
const editBus = computed(() =>
  selectedBu.value ? [selectedBu.value] : accessibleBus.value)

const canEdit = computed(() => auth.isAdmin || auth.canUpload)

// ── 万元 <-> 元 conversion (targets are entered/shown in 万元, stored in 元) ──
const toWan = (yuan) => (yuan == null ? '' : +(yuan / 10000).toFixed(2))
const fromWan = (wan) => Math.round((parseFloat(wan) || 0) * 10000 * 100) / 100
const fmtWan = (v) => fmtCompact(v, { space: true })

function blankRow() {
  return { m_rev: '', m_prof: '', a_rev: '', a_prof: '' }
}

async function load() {
  loading.value = true
  loadErr.value = ''
  saveMsg.value = ''
  try {
    const params = { year: year.value, month: month.value }
    if (selectedBu.value) params.bu = selectedBu.value
    const [mRes, tRes] = await Promise.all([
      api.get('/metrics', { params }),
      api.get('/targets', { params: { year: year.value, bu: selectedBu.value || undefined } }),
    ])
    metricsData.value = mRes.data

    // index targets by (bu, month)
    const idx = {}
    for (const t of (tRes.data?.targets || [])) idx[`${t.business_unit}:${t.month}`] = t
    for (const bu of editBus.value) {
      const m = idx[`${bu}:${month.value}`]
      const a = idx[`${bu}:0`]
      editModel[bu] = {
        m_rev: m ? toWan(m.target_revenue) : '',
        m_prof: m ? toWan(m.target_profit) : '',
        a_rev: a ? toWan(a.target_revenue) : '',
        a_prof: a ? toWan(a.target_profit) : '',
      }
    }
  } catch (e) {
    loadErr.value = e?.error || '加载失败'
  } finally {
    loading.value = false
  }
}

async function save() {
  if (!canEdit.value) return
  saving.value = true
  saveMsg.value = ''
  try {
    const items = []
    for (const bu of editBus.value) {
      const r = editModel[bu] || blankRow()
      items.push({ business_unit: bu, month: month.value,
        target_revenue: fromWan(r.m_rev), target_profit: fromWan(r.m_prof) })
      items.push({ business_unit: bu, month: 0,
        target_revenue: fromWan(r.a_rev), target_profit: fromWan(r.a_prof) })
    }
    await api.post('/targets', { year: year.value, items })
    saveMsg.value = '已保存'
    await load()
  } catch (e) {
    saveMsg.value = e?.msg || e?.error || '保存失败'
  } finally {
    saving.value = false
  }
}

// ── display rows (BUs + group total) ─────────────────────────────────────────
const rows = computed(() => {
  if (!metricsData.value) return []
  const list = [...(metricsData.value.bus || [])]
  if (metricsData.value.total && (metricsData.value.bus || []).length > 1) {
    list.push({ ...metricsData.value.total, _isTotal: true })
  }
  return list
})

function rateClass(rate) {
  if (rate == null) return 'rate-na'
  if (rate >= 100) return 'rate-good'
  if (rate >= 80) return 'rate-warn'
  return 'rate-bad'
}
const fmtRate = (r) => (r == null ? '—' : r.toFixed(1) + '%')
function chgClass(v) {
  if (v == null) return 'chg-na'
  return v >= 0 ? 'chg-up' : 'chg-down'
}

// ── achievement bar chart (per BU, current month) ────────────────────────────
const chartOption = computed(() => {
  const bus = (metricsData.value?.bus || [])
  const names = bus.map(b => b.business_unit)
  const revRates = bus.map(b => b.month.revenue_rate)
  const profRates = bus.map(b => b.month.profit_rate)
  return {
    tooltip: {
      trigger: 'axis', axisPointer: { type: 'shadow' },
      formatter(params) {
        let s = `<b>${params[0]?.axisValue}</b><br/>`
        params.forEach(p => {
          s += `${p.marker}${p.seriesName}：${p.value == null ? '—' : p.value.toFixed(1) + '%'}<br/>`
        })
        return s
      },
    },
    legend: { bottom: 0, itemGap: 18 },
    grid: { top: 24, right: 20, bottom: 40, left: 20, containLabel: true },
    xAxis: {
      type: 'category', data: names,
      axisLine: { lineStyle: { color: '#d4c4b4' } },
      axisLabel: { color: '#9b8070', fontSize: 11, interval: 0, rotate: names.length > 4 ? 20 : 0 },
    },
    yAxis: {
      type: 'value', name: '达成率%',
      axisLabel: { color: '#9b8070', fontSize: 10, formatter: '{value}%' },
      splitLine: { lineStyle: { color: 'rgba(180,140,110,.15)' } },
    },
    series: [
      { name: '收入达成率', type: 'bar', data: revRates, itemStyle: { color: '#2e7d32', borderRadius: [4, 4, 0, 0] }, barMaxWidth: 26,
        markLine: { silent: true, symbol: 'none', lineStyle: { color: '#c96342', type: 'dashed' }, data: [{ yAxis: 100, label: { formatter: '目标100%', color: '#c96342', fontSize: 10 } }] } },
      { name: '利润达成率', type: 'bar', data: profRates, itemStyle: { color: '#1565c0', borderRadius: [4, 4, 0, 0] }, barMaxWidth: 26 },
    ],
  }
})

onMounted(load)
</script>

<template>
  <div>
    <div class="topbar" style="align-items:flex-start">
      <h1>指标管理</h1>
      <div class="ctrl-row" style="justify-content:flex-end">
        <select v-model="year" class="sel-yr" @change="load">
          <option v-for="y in years" :key="y" :value="y">{{ y }} 年</option>
        </select>
        <select v-model="month" class="sel-mo" @change="load">
          <option v-for="m in months" :key="m" :value="m">{{ m }} 月</option>
        </select>
        <select v-if="accessibleBus.length > 1" v-model="selectedBu" class="sel-bu" @change="load">
          <option value="">全部事业部</option>
          <option v-for="bu in accessibleBus" :key="bu" :value="bu">{{ bu }}</option>
        </select>
      </div>
    </div>

    <EmptyState v-if="loading && !metricsData" loading />
    <EmptyState v-else-if="loadErr" :error="loadErr" />
    <template v-else-if="metricsData">
      <div :class="{ 'data-reloading': loading }">

      <!-- ── 目标录入 ──────────────────────────────────────────────────────── -->
      <div class="card">
        <div class="section-title" style="margin-bottom:14px">
          目标录入 · {{ year }}年
          <span class="badge badge-primary" style="margin-left:8px">单位：万元</span>
          <span v-if="!canEdit" class="badge badge-viewer" style="margin-left:6px">只读</span>
        </div>
        <div class="table-scroll">
          <table class="metric-table">
            <thead>
              <tr>
                <th rowspan="2" class="col-bu">事业部</th>
                <th colspan="2">{{ month }}月目标</th>
                <th colspan="2">{{ year }}年度目标</th>
              </tr>
              <tr>
                <th>收入</th><th>利润</th><th>收入</th><th>利润</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="bu in editBus" :key="bu">
                <td class="col-bu">{{ bu }}</td>
                <td><input v-model="editModel[bu].m_rev" :disabled="!canEdit" type="number" step="0.01" class="t-input" /></td>
                <td><input v-model="editModel[bu].m_prof" :disabled="!canEdit" type="number" step="0.01" class="t-input" /></td>
                <td><input v-model="editModel[bu].a_rev" :disabled="!canEdit" type="number" step="0.01" class="t-input" /></td>
                <td><input v-model="editModel[bu].a_prof" :disabled="!canEdit" type="number" step="0.01" class="t-input" /></td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-if="canEdit" class="save-row">
          <span v-if="saveMsg" class="save-msg">{{ saveMsg }}</span>
          <button class="btn btn-primary btn-sm" :disabled="saving" @click="save">
            {{ saving ? '保存中…' : '保存目标' }}
          </button>
        </div>
      </div>

      <!-- ── 完成情况 · 收入 ───────────────────────────────────────────────── -->
      <div class="card">
        <div class="section-title" style="margin-bottom:14px">收入完成情况 · {{ year }}年{{ month }}月</div>
        <div class="table-scroll">
          <table class="metric-table">
            <thead>
              <tr>
                <th rowspan="2" class="col-bu">事业部</th>
                <th colspan="3">当月</th>
                <th colspan="2">同比 / 环比</th>
                <th colspan="3">年度累计 (YTD)</th>
              </tr>
              <tr>
                <th>目标</th><th>实际</th><th>达成率</th>
                <th>环比</th><th>同比</th>
                <th>年目标</th><th>累计实际</th><th>达成率</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in rows" :key="'rev'+r.business_unit" :class="{ 'total-row': r._isTotal }">
                <td class="col-bu">{{ r.business_unit }}</td>
                <td>{{ fmtWan(r.month.target_revenue) }}</td>
                <td class="num-strong">{{ fmtWan(r.month.actual_revenue) }}</td>
                <td><span class="rate-pill" :class="rateClass(r.month.revenue_rate)">{{ fmtRate(r.month.revenue_rate) }}</span></td>
                <td :class="chgClass(r.month.revenue_mom)">{{ r.month.revenue_mom == null ? '—' : fmtPct(r.month.revenue_mom) }}</td>
                <td :class="chgClass(r.month.revenue_yoy)">{{ r.month.revenue_yoy == null ? '—' : fmtPct(r.month.revenue_yoy) }}</td>
                <td>{{ fmtWan(r.ytd.target_revenue) }}</td>
                <td class="num-strong">{{ fmtWan(r.ytd.actual_revenue) }}</td>
                <td><span class="rate-pill" :class="rateClass(r.ytd.revenue_rate)">{{ fmtRate(r.ytd.revenue_rate) }}</span></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- ── 完成情况 · 利润 ───────────────────────────────────────────────── -->
      <div class="card">
        <div class="section-title" style="margin-bottom:14px">利润完成情况 · {{ year }}年{{ month }}月</div>
        <div class="table-scroll">
          <table class="metric-table">
            <thead>
              <tr>
                <th rowspan="2" class="col-bu">事业部</th>
                <th colspan="3">当月</th>
                <th colspan="2">同比 / 环比</th>
                <th colspan="3">年度累计 (YTD)</th>
              </tr>
              <tr>
                <th>目标</th><th>实际</th><th>达成率</th>
                <th>环比</th><th>同比</th>
                <th>年目标</th><th>累计实际</th><th>达成率</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in rows" :key="'prof'+r.business_unit" :class="{ 'total-row': r._isTotal }">
                <td class="col-bu">{{ r.business_unit }}</td>
                <td>{{ fmtWan(r.month.target_profit) }}</td>
                <td class="num-strong">{{ fmtWan(r.month.actual_profit) }}</td>
                <td><span class="rate-pill" :class="rateClass(r.month.profit_rate)">{{ fmtRate(r.month.profit_rate) }}</span></td>
                <td :class="chgClass(r.month.profit_mom)">{{ r.month.profit_mom == null ? '—' : fmtPct(r.month.profit_mom) }}</td>
                <td :class="chgClass(r.month.profit_yoy)">{{ r.month.profit_yoy == null ? '—' : fmtPct(r.month.profit_yoy) }}</td>
                <td>{{ fmtWan(r.ytd.target_profit) }}</td>
                <td class="num-strong">{{ fmtWan(r.ytd.actual_profit) }}</td>
                <td><span class="rate-pill" :class="rateClass(r.ytd.profit_rate)">{{ fmtRate(r.ytd.profit_rate) }}</span></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- ── 达成率图 ──────────────────────────────────────────────────────── -->
      <div v-if="(metricsData.bus || []).length" class="card">
        <div class="section-title" style="margin-bottom:8px">各事业部当月达成率</div>
        <BaseChart :option="chartOption" height="320px" />
      </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.table-scroll { overflow-x: auto; }
.metric-table { width: 100%; border-collapse: collapse; font-size: 13px; min-width: 720px; }
.metric-table th, .metric-table td {
  padding: 8px 10px; text-align: right; border-bottom: 1px solid var(--border);
  white-space: nowrap;
}
.metric-table thead th {
  color: var(--muted); font-weight: 700; font-size: 12px;
  background: rgba(180,140,110,.06); text-align: center;
}
.metric-table .col-bu { text-align: left; font-weight: 600; color: var(--text); }
.metric-table tbody tr:hover { background: rgba(180,140,110,.05); }
.total-row { background: rgba(201,99,66,.06); font-weight: 700; }
.total-row .col-bu { color: var(--primary); }
.num-strong { font-weight: 700; color: var(--text); }

.t-input {
  width: 92px; padding: 5px 8px; text-align: right; font-size: 13px;
  border: 1px solid var(--border); border-radius: 7px; background: rgba(255,255,255,.6);
  color: var(--text);
}
.t-input:focus { outline: none; border-color: var(--primary); }
.t-input:disabled { background: transparent; border-color: transparent; color: var(--muted); }

.save-row { display: flex; align-items: center; justify-content: flex-end; gap: 12px; margin-top: 14px; }
.save-msg { font-size: 12px; color: #2e7d32; font-weight: 600; }

.rate-pill { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 12px; font-weight: 700; }
.rate-good { background: rgba(46,125,50,.12); color: #2e7d32; }
.rate-warn { background: rgba(245,127,23,.14); color: #e65100; }
.rate-bad  { background: rgba(198,40,40,.12); color: #c62828; }
.rate-na   { background: rgba(120,120,120,.08); color: var(--muted); font-weight: 500; }

.chg-up   { color: #2e7d32; font-weight: 600; }
.chg-down { color: #c62828; font-weight: 600; }
.chg-na   { color: var(--muted); }
</style>
