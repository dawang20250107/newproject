<script setup>
import { ref, computed, reactive, onMounted, watch } from 'vue'
import { useCaiwuAuth } from '../../composables/useCaiwuAuth.js'
import { BUSINESS_UNITS, yearCST, monthCST } from '../../constants.js'
import BaseChart from '../../components/caiwu/charts/BaseChart.vue'
import api from '../../api/caiwu.js'
import { fmtCompact, fmtPct } from '../../utils/format.js'
import EmptyState from '../../components/EmptyState.vue'

const auth = useCaiwuAuth()

const targetYear = ref(yearCST())          // 指标录入年份
const reportYear = ref(yearCST())          // 完成情况年份
const reportMonth = ref(monthCST())        // 完成情况月份
const selectedBu = ref('')

const loadingTargets = ref(false)
const loadingMetrics = ref(false)
const loadErr = ref('')
const saving = ref(false)
const saveMsg = ref('')
const saveMsgOk = ref(true)

const metricsData = ref(null)

// editGrid[bu] = { rev: [v1..v12, annualV], prof: [v1..v12, annualV] }
// index 0-11 = Jan-Dec (万元), index 12 = annual target (万元)
const editGrid = reactive({})

const years = Array.from({ length: 5 }, (_, i) => yearCST() - 2 + i)
const months = Array.from({ length: 12 }, (_, i) => i + 1)
const MONTH_LABELS = ['1月','2月','3月','4月','5月','6月','7月','8月','9月','10月','11月','12月']

const accessibleBus = computed(() => {
  if (auth.isAdmin) return BUSINESS_UNITS
  return (auth.user?.departments || []).filter(d => BUSINESS_UNITS.includes(d))
})
const editBus = computed(() =>
  selectedBu.value ? [selectedBu.value] : accessibleBus.value)

const canEdit = computed(() => auth.isAdmin || auth.canUpload)

// ── 万元 <-> 元 ──────────────────────────────────────────────────────────────
const toWan = (yuan) => (yuan == null ? '' : +(yuan / 10000).toFixed(2))
const fromWan = (wan) => Math.round((parseFloat(wan) || 0) * 10000 * 100) / 100
const fmtWan = (v) => fmtCompact(v, { space: true })

function initBuGrid(bu) {
  if (!editGrid[bu]) editGrid[bu] = { rev: Array(13).fill(''), prof: Array(13).fill('') }
}

// ── sum of months 0-11 (index), compare to index 12 (annual) ────────────────
function monthSum(bu, key) {
  const arr = editGrid[bu]?.[key]
  if (!arr) return 0
  return arr.slice(0, 12).reduce((s, v) => s + (parseFloat(v) || 0), 0)
}
function annualVal(bu, key) {
  return parseFloat(editGrid[bu]?.[key]?.[12]) || 0
}
function delta(bu, key) {
  return monthSum(bu, key) - annualVal(bu, key)
}
function deltaOk(bu, key) {
  return Math.abs(delta(bu, key)) < 0.01   // 0.01万 = 100元 tolerance
}

// allDeltaOk: true only when every BU with non-zero annual has matching sum
const allDeltaOk = computed(() =>
  editBus.value.every(bu => deltaOk(bu, 'rev') && deltaOk(bu, 'prof'))
)

// ── load targets (all months for targetYear) ─────────────────────────────────
async function loadTargets() {
  loadingTargets.value = true
  loadErr.value = ''
  try {
    const res = await api.get('/targets', { params: { year: targetYear.value } })
    // reset grid
    for (const bu of editBus.value) initBuGrid(bu)
    for (const t of (res.data?.targets || [])) {
      const bu = t.business_unit
      if (!editGrid[bu]) initBuGrid(bu)
      if (t.month === 0) {
        editGrid[bu].rev[12] = toWan(t.target_revenue) === '' ? '' : toWan(t.target_revenue)
        editGrid[bu].prof[12] = toWan(t.target_profit) === '' ? '' : toWan(t.target_profit)
      } else if (t.month >= 1 && t.month <= 12) {
        editGrid[bu].rev[t.month - 1] = toWan(t.target_revenue) === '' ? '' : toWan(t.target_revenue)
        editGrid[bu].prof[t.month - 1] = toWan(t.target_profit) === '' ? '' : toWan(t.target_profit)
      }
    }
  } catch (e) {
    loadErr.value = e?.error || '指标加载失败'
  } finally {
    loadingTargets.value = false
  }
}

// ── load actuals (metrics endpoint) ─────────────────────────────────────────
async function loadMetrics() {
  loadingMetrics.value = true
  try {
    const params = { year: reportYear.value, month: reportMonth.value }
    if (selectedBu.value) params.bu = selectedBu.value
    const res = await api.get('/metrics', { params })
    metricsData.value = res.data
  } catch (e) {
    metricsData.value = null
  } finally {
    loadingMetrics.value = false
  }
}

async function load() {
  await Promise.all([loadTargets(), loadMetrics()])
}

// ── save ─────────────────────────────────────────────────────────────────────
async function save() {
  if (!canEdit.value || !allDeltaOk.value) return
  saving.value = true
  saveMsg.value = ''
  try {
    const items = []
    for (const bu of editBus.value) {
      // months 1-12
      for (let m = 1; m <= 12; m++) {
        items.push({ business_unit: bu, month: m,
          target_revenue: fromWan(editGrid[bu]?.rev[m - 1]),
          target_profit:  fromWan(editGrid[bu]?.prof[m - 1]) })
      }
      // annual (month=0)
      items.push({ business_unit: bu, month: 0,
        target_revenue: fromWan(editGrid[bu]?.rev[12]),
        target_profit:  fromWan(editGrid[bu]?.prof[12]) })
    }
    await api.post('/targets', { year: targetYear.value, items })
    saveMsgOk.value = true
    saveMsg.value = '已保存'
    await loadMetrics()
  } catch (e) {
    saveMsgOk.value = false
    saveMsg.value = e?.msg || e?.error || '保存失败'
  } finally {
    saving.value = false
  }
}

// ── auto-fill annual = sum of 12 months ──────────────────────────────────────
function autoFillAnnual(bu, key) {
  const sum = monthSum(bu, key)
  if (sum > 0) editGrid[bu][key][12] = +sum.toFixed(2)
}

// reload targets when year changes; reload metrics when year/month changes
watch(targetYear, loadTargets)
watch([reportYear, reportMonth, selectedBu], loadMetrics)

// ── display rows ─────────────────────────────────────────────────────────────
const rows = computed(() => {
  if (!metricsData.value) return []
  const list = [...(metricsData.value.bus || [])]
  if (metricsData.value.total && (metricsData.value.bus || []).length > 1)
    list.push({ ...metricsData.value.total, _isTotal: true })
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

// ── achievement bar chart ────────────────────────────────────────────────────
const chartOption = computed(() => {
  const bus = (metricsData.value?.bus || [])
  const names = bus.map(b => b.business_unit)
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
      { name: '收入达成率', type: 'bar', data: bus.map(b => b.month.revenue_rate),
        itemStyle: { color: '#2e7d32', borderRadius: [4, 4, 0, 0] }, barMaxWidth: 26,
        markLine: { silent: true, symbol: 'none', lineStyle: { color: '#c96342', type: 'dashed' },
          data: [{ yAxis: 100, label: { formatter: '100%', color: '#c96342', fontSize: 10 } }] } },
      { name: '利润达成率', type: 'bar', data: bus.map(b => b.month.profit_rate),
        itemStyle: { color: '#1565c0', borderRadius: [4, 4, 0, 0] }, barMaxWidth: 26 },
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
        <select v-if="accessibleBus.length > 1" v-model="selectedBu" class="sel-bu" @change="loadMetrics">
          <option value="">全部事业部</option>
          <option v-for="bu in accessibleBus" :key="bu" :value="bu">{{ bu }}</option>
        </select>
      </div>
    </div>

    <EmptyState v-if="loadErr" :error="loadErr" />
    <template v-else>

      <!-- ── 目标录入（12月网格）────────────────────────────────────────────── -->
      <div class="card">
        <div class="card-header-row">
          <div>
            <div class="section-title" style="margin-bottom:4px">
              目标录入 · 年度 / 月度
              <span class="badge badge-primary" style="margin-left:8px">单位：万元</span>
              <span v-if="!canEdit" class="badge badge-viewer" style="margin-left:6px">只读</span>
            </div>
            <div class="grid-hint">月度合计必须等于年度目标，否则无法保存</div>
          </div>
          <div class="card-header-right">
            <select v-model="targetYear" class="sel-yr">
              <option v-for="y in years" :key="y" :value="y">{{ y }} 年</option>
            </select>
            <span v-if="saveMsg" class="save-msg" :class="saveMsgOk ? 'save-ok' : 'save-err'">{{ saveMsg }}</span>
            <button v-if="canEdit" class="btn btn-primary btn-sm"
                    :disabled="saving || !allDeltaOk"
                    :title="allDeltaOk ? '' : '有事业部月度合计与年度目标不符'"
                    @click="save">
              {{ saving ? '保存中…' : '保存目标' }}
            </button>
          </div>
        </div>

        <!-- 收入目标网格 -->
        <div class="grid-sub-title">收入目标（万元）</div>
        <div class="grid-scroll">
          <table class="tgt-grid">
            <thead>
              <tr>
                <th class="col-bu">事业部</th>
                <th v-for="l in MONTH_LABELS" :key="l" class="col-mo">{{ l }}</th>
                <th class="col-sum">月合计</th>
                <th class="col-annual">年度目标</th>
                <th class="col-diff">差额</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="bu in editBus" :key="bu" :class="{ 'row-err': !deltaOk(bu,'rev') }">
                <td class="col-bu">{{ bu }}</td>
                <td v-for="(_, mi) in MONTH_LABELS" :key="mi">
                  <input v-model="editGrid[bu].rev[mi]" :disabled="!canEdit"
                         type="number" step="0.01" class="t-input" />
                </td>
                <td class="col-sum-val">{{ monthSum(bu,'rev') ? (+monthSum(bu,'rev').toFixed(2)).toLocaleString() : '—' }}</td>
                <td>
                  <input v-model="editGrid[bu].rev[12]" :disabled="!canEdit"
                         type="number" step="0.01" class="t-input t-annual" />
                </td>
                <td class="col-diff-val" :class="deltaOk(bu,'rev') ? 'diff-ok' : 'diff-err'">
                  <span v-if="deltaOk(bu,'rev')">✓</span>
                  <span v-else>{{ delta(bu,'rev') >= 0 ? '+' : '' }}{{ delta(bu,'rev').toFixed(2) }}</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- 利润目标网格 -->
        <div class="grid-sub-title" style="margin-top:16px">利润目标（万元）</div>
        <div class="grid-scroll">
          <table class="tgt-grid">
            <thead>
              <tr>
                <th class="col-bu">事业部</th>
                <th v-for="l in MONTH_LABELS" :key="l" class="col-mo">{{ l }}</th>
                <th class="col-sum">月合计</th>
                <th class="col-annual">年度目标</th>
                <th class="col-diff">差额</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="bu in editBus" :key="bu" :class="{ 'row-err': !deltaOk(bu,'prof') }">
                <td class="col-bu">{{ bu }}</td>
                <td v-for="(_, mi) in MONTH_LABELS" :key="mi">
                  <input v-model="editGrid[bu].prof[mi]" :disabled="!canEdit"
                         type="number" step="0.01" class="t-input" />
                </td>
                <td class="col-sum-val">{{ monthSum(bu,'prof') ? (+monthSum(bu,'prof').toFixed(2)).toLocaleString() : '—' }}</td>
                <td>
                  <input v-model="editGrid[bu].prof[12]" :disabled="!canEdit"
                         type="number" step="0.01" class="t-input t-annual" />
                </td>
                <td class="col-diff-val" :class="deltaOk(bu,'prof') ? 'diff-ok' : 'diff-err'">
                  <span v-if="deltaOk(bu,'prof')">✓</span>
                  <span v-else>{{ delta(bu,'prof') >= 0 ? '+' : '' }}{{ delta(bu,'prof').toFixed(2) }}</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div v-if="canEdit" class="auto-fill-row">
          <span class="grid-hint">提示：先填写12个月，再按「自动填充年度目标」</span>
          <div class="auto-fill-btns">
            <button v-for="bu in editBus" :key="bu" class="btn btn-ghost btn-sm" @click="autoFillAnnual(bu,'rev'); autoFillAnnual(bu,'prof')">
              {{ bu }} 自动填年度
            </button>
          </div>
        </div>
      </div>

      <!-- ── 完成情况 ──────────────────────────────────────────────────────── -->
      <div class="ctrl-row" style="margin-bottom:4px">
        <span class="section-title" style="margin:0">完成情况</span>
        <select v-model="reportYear" class="sel-yr">
          <option v-for="y in years" :key="y" :value="y">{{ y }} 年</option>
        </select>
        <select v-model="reportMonth" class="sel-mo">
          <option v-for="m in months" :key="m" :value="m">{{ m }} 月</option>
        </select>
      </div>

      <EmptyState v-if="loadingMetrics && !metricsData" loading />
      <template v-else-if="metricsData">
        <div :class="{ 'data-reloading': loadingMetrics }">

        <div class="card">
          <div class="section-title" style="margin-bottom:14px">收入完成情况 · {{ reportYear }}年{{ reportMonth }}月</div>
          <div class="table-scroll">
            <table class="metric-table">
              <thead>
                <tr>
                  <th rowspan="2" class="col-bu">事业部</th>
                  <th colspan="3">当月</th><th colspan="2">同比 / 环比</th><th colspan="3">YTD</th>
                </tr>
                <tr>
                  <th>目标</th><th>实际</th><th>达成率</th>
                  <th>环比</th><th>同比</th>
                  <th>年目标</th><th>累计</th><th>达成率</th>
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

        <div class="card">
          <div class="section-title" style="margin-bottom:14px">利润完成情况 · {{ reportYear }}年{{ reportMonth }}月</div>
          <div class="table-scroll">
            <table class="metric-table">
              <thead>
                <tr>
                  <th rowspan="2" class="col-bu">事业部</th>
                  <th colspan="3">当月</th><th colspan="2">同比 / 环比</th><th colspan="3">YTD</th>
                </tr>
                <tr>
                  <th>目标</th><th>实际</th><th>达成率</th>
                  <th>环比</th><th>同比</th>
                  <th>年目标</th><th>累计</th><th>达成率</th>
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

        <div v-if="(metricsData.bus || []).length" class="card">
          <div class="section-title" style="margin-bottom:8px">各事业部当月达成率</div>
          <BaseChart :option="chartOption" height="320px" />
        </div>
        </div>
      </template>
    </template>
  </div>
</template>

<style scoped>
/* ── card header ─────────────────────────────────────────────────────────── */
.card-header-row {
  display: flex; align-items: flex-start; justify-content: space-between;
  flex-wrap: wrap; gap: 12px; margin-bottom: 14px;
}
.card-header-right { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.grid-hint { font-size: 12px; color: var(--muted); margin-top: 2px; }
.grid-sub-title { font-size: 13px; font-weight: 700; color: var(--primary); margin: 8px 0 6px; }

/* ── 12-month target grid ────────────────────────────────────────────────── */
.grid-scroll { overflow-x: auto; }
.tgt-grid { width: 100%; border-collapse: collapse; font-size: 12px; min-width: 1100px; }
.tgt-grid th, .tgt-grid td {
  padding: 5px 4px; text-align: center; border-bottom: 1px solid var(--border);
  white-space: nowrap;
}
.tgt-grid thead th {
  color: var(--muted); font-weight: 700; font-size: 11px;
  background: rgba(180,140,110,.06); position: sticky; top: 0; z-index: 1;
}
.tgt-grid .col-bu { text-align: left; font-weight: 600; width: 90px; min-width: 90px; position: sticky; left: 0; background: var(--card); z-index: 2; }
.tgt-grid .col-mo { min-width: 68px; }
.tgt-grid .col-sum, .tgt-grid .col-annual { min-width: 72px; }
.tgt-grid .col-diff { min-width: 60px; }
.tgt-grid tbody tr:hover { background: rgba(180,140,110,.04); }

.row-err { background: rgba(198,40,40,.04) !important; }
.row-err .col-bu { color: #c62828; }

.t-input {
  width: 62px; padding: 4px 5px; text-align: right; font-size: 12px;
  border: 1px solid var(--border); border-radius: 5px; background: rgba(255,255,255,.6);
  color: var(--text);
}
.t-input:focus { outline: none; border-color: var(--primary); }
.t-input:disabled { background: transparent; border-color: transparent; color: var(--text); }
.t-annual { border-color: rgba(201,99,66,.4); background: rgba(201,99,66,.04); width: 70px; }

.col-sum-val { font-weight: 700; color: var(--text); font-size: 12px; }
.col-diff-val { font-size: 12px; font-weight: 700; }
.diff-ok { color: #2e7d32; }
.diff-err { color: #c62828; animation: errPulse 1.5s ease-in-out infinite; }
@keyframes errPulse {
  0%, 100% { opacity: 1; }
  50% { opacity: .5; }
}

.auto-fill-row {
  display: flex; align-items: center; justify-content: space-between;
  flex-wrap: wrap; gap: 8px; margin-top: 14px;
  padding-top: 10px; border-top: 1px dashed var(--border);
}
.auto-fill-btns { display: flex; gap: 6px; flex-wrap: wrap; }
.save-msg { font-size: 12px; font-weight: 700; }
.save-ok { color: #2e7d32; }
.save-err { color: #c62828; }

/* ── completion tables ───────────────────────────────────────────────────── */
.table-scroll { overflow-x: auto; }
.metric-table { width: 100%; border-collapse: collapse; font-size: 13px; min-width: 700px; }
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

.rate-pill { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 12px; font-weight: 700; }
.rate-good { background: rgba(46,125,50,.12); color: #2e7d32; }
.rate-warn { background: rgba(245,127,23,.14); color: #e65100; }
.rate-bad  { background: rgba(198,40,40,.12); color: #c62828; }
.rate-na   { background: rgba(120,120,120,.08); color: var(--muted); font-weight: 500; }

.chg-up   { color: #2e7d32; font-weight: 600; }
.chg-down { color: #c62828; font-weight: 600; }
.chg-na   { color: var(--muted); }
</style>
