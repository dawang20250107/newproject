<script setup>
import { ref, reactive, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { useAuthStore } from '../../stores/auth.js'
import { DEPARTMENTS, yearCST } from '../../constants.js'
import ar from '../../api/ar.js'
import { fmtCompact } from '../../utils/format.js'
import { TOOLTIP } from '../../utils/chartTheme.js'
import EmptyState from '../../components/EmptyState.vue'
import BaseChart from '../../components/caiwu/charts/BaseChart.vue'

defineProps({ embedded: { type: Boolean, default: false } })
const auth = useAuthStore()

const selectedDept = ref('')
const selectedYear = ref(yearCST())
const horizon = ref(6)
const years = Array.from({ length: 5 }, (_, i) => yearCST() - 2 + i)
const accessibleDepts = computed(() => auth.effectiveDepts.filter(d => DEPARTMENTS.includes(d)))

const loading = ref(true)
const err = ref('')
const fc = ref(null)

const fmtWan = (v) => fmtCompact(v, { decimals: 1, smallRound: true, dash: '0' })
const fmtPct = (v) => (v == null ? '—' : `${v.toFixed(1)}%`)
const fmtMonth = (s) => { const [y, m] = (s || '').split('-'); return `${+m}月` }

// What-if 沙盘假设
const wf = reactive({ revPct: 0, gmPt: 0 })

async function load() {
  loading.value = true; err.value = ''
  try {
    const params = { year: selectedYear.value, horizon: horizon.value }
    if (selectedDept.value) params.dept = selectedDept.value
    const r = await ar.forecast(params)
    fc.value = r.data
    wf.revPct = 0; wf.gmPt = 0
  } catch (e) {
    err.value = e?.msg || '加载失败'
  } finally {
    loading.value = false
  }
}

const cash = computed(() => fc.value?.cash || null)
const landing = computed(() => fc.value?.landing || null)
const baseline = computed(() => fc.value?.baseline || null)
const summary = computed(() => fc.value?.summary || null)

// ── 现金流入预测：月预计回款柱 + 累计回款线 + 期初未收基准 ────────────────────
const cashOption = computed(() => {
  const c = cash.value
  if (!c?.months?.length) return null
  const x = c.months.map(r => fmtMonth(r.month))
  const opening = c.opening_outstanding || 0
  const w = (v) => (Math.abs(v) >= 10000 ? (v / 10000).toFixed(0) + '万' : Math.round(v))
  return {
    tooltip: {
      trigger: 'axis', ...TOOLTIP,
      formatter: (ps) => {
        let s = `<b>${ps[0]?.axisValue}</b><br/>`
        ps.forEach(p => { s += `${p.marker}${p.seriesName}：<b>${fmtWan(p.value)}</b><br/>` })
        return s
      },
    },
    legend: { bottom: 0, textStyle: { fontSize: 11, color: '#6b5a4a' }, data: ['月预计回款', '累计回款'] },
    grid: { top: 18, right: 16, bottom: 34, left: 56 },
    xAxis: { type: 'category', data: x, axisLabel: { color: '#9b8070' } },
    yAxis: { type: 'value', axisLabel: { color: '#9b8070', formatter: w }, splitLine: { lineStyle: { color: 'rgba(180,140,110,.12)' } } },
    series: [
      { name: '月预计回款', type: 'bar', data: c.months.map(r => r.expected), barMaxWidth: 30,
        itemStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: '#42a5f5' }, { offset: 1, color: '#1565c0' }] }, borderRadius: [4, 4, 0, 0] } },
      { name: '累计回款', type: 'line', data: c.months.map(r => r.cumulative), smooth: true, symbol: 'circle', symbolSize: 5,
        lineStyle: { color: '#00897b', width: 2.5 }, itemStyle: { color: '#00897b' },
        markLine: { silent: true, symbol: 'none', data: [{ yAxis: opening, lineStyle: { type: 'dashed', color: '#c96342' }, label: { formatter: `期初未收 ${fmtWan(opening)}`, color: '#c96342', fontSize: 10, position: 'insideEndTop' } }] } },
    ],
  }
})

// ── 全年落地预测：三指标 YTD→全年预测 vs 目标 ────────────────────────────────
const landingRows = computed(() => {
  const l = landing.value
  if (!l) return []
  return [
    { key: 'revenue', label: '收入', color: '#2e7d32', ...l.revenue },
    { key: 'gross', label: '经营毛利', color: '#00897b', ...l.gross },
    { key: 'profit', label: '经营净利', color: '#1565c0', ...l.profit },
  ]
})
// 条形相对刻度（按 max(预测,目标) 归一）
const landingScale = (r) => {
  const m = Math.max(Math.abs(r.projected || 0), Math.abs(r.target || 0), 1)
  return { proj: Math.min(100, Math.abs(r.projected || 0) / m * 100), tgt: Math.min(100, Math.abs(r.target || 0) / m * 100) }
}

// ── What-if 沙盘：收入Δ% + 毛利率Δpt → 全年净利 ───────────────────────────────
const wfResult = computed(() => {
  const b = baseline.value, s = summary.value
  if (!b || !s) return null
  const newRev = (b.proj_revenue || 0) * (1 + wf.revPct / 100)
  const newNetMargin = (b.net_margin ?? 0) + wf.gmPt
  const newProfit = newRev * newNetMargin / 100
  const target = s.profit_target || 0
  return {
    rev: newRev, netMargin: newNetMargin, profit: newProfit, target,
    gap: newProfit - target, rate: target ? newProfit / target * 100 : null,
    baseProfit: s.proj_profit || 0, deltaVsBase: newProfit - (s.proj_profit || 0),
  }
})
// 扭亏 / 达标 所需毛利率提升（在当前收入假设下）
const breakeven = computed(() => {
  const b = baseline.value, s = summary.value
  if (!b || !s) return null
  const nm = b.net_margin ?? 0
  const newRev = (b.proj_revenue || 0) * (1 + wf.revPct / 100)
  const tgtMargin = newRev ? (s.profit_target || 0) / newRev * 100 : null
  return { toZero: +(-nm).toFixed(1), toTarget: tgtMargin != null ? +(tgtMargin - nm).toFixed(1) : null }
})

watch([selectedDept, selectedYear, horizon], load)
const onScopeChange = () => {
  if (selectedDept.value && !accessibleDepts.value.includes(selectedDept.value)) selectedDept.value = ''
  load()
}
onMounted(() => { load(); window.addEventListener('pk:depts-changed', onScopeChange) })
onBeforeUnmount(() => window.removeEventListener('pk:depts-changed', onScopeChange))
</script>

<template>
  <div class="fc-panel">
    <div class="fc-filters">
      <select v-model="selectedDept">
        <option value="">全部事业部</option>
        <option v-for="d in accessibleDepts" :key="d" :value="d">{{ d }}</option>
      </select>
      <select v-model.number="selectedYear">
        <option v-for="y in years" :key="y" :value="y">{{ y }}年</option>
      </select>
      <select v-model.number="horizon">
        <option :value="3">未来3月</option>
        <option :value="6">未来6月</option>
        <option :value="12">未来12月</option>
      </select>
      <span class="fc-hint">基于应收账龄+历史回款滞后预测现金，YTD 年化研判全年落地</span>
    </div>

    <EmptyState v-if="loading && !fc" loading />
    <EmptyState v-else-if="err" :error="err" />
    <template v-else-if="summary">
      <div :class="{ 'data-reloading': loading }">
        <!-- KPI 摘要 -->
        <div class="fc-kpis">
          <div class="fc-kpi">
            <div class="t">期初未收</div>
            <div class="v">{{ fmtWan(cash.opening_outstanding) }}</div>
            <div class="s">回款滞后中位 {{ fc.avg_lag_days }} 天</div>
          </div>
          <div class="fc-kpi cash">
            <div class="t">未来3月预计回款</div>
            <div class="v">{{ fmtWan(summary.cash_next3) }}</div>
            <div class="s">{{ horizon }}月内合计 {{ fmtWan(cash.expected_window_total) }}</div>
          </div>
          <div class="fc-kpi risk">
            <div class="t">坏账风险（逾期90天+）</div>
            <div class="v" :style="{ color: cash.baddebt_risk > 0 ? '#c62828' : '#2e7d32' }">{{ fmtWan(cash.baddebt_risk) }}</div>
            <div class="s">需重点催收</div>
          </div>
          <div class="fc-kpi" :class="summary.profit_gap < 0 ? 'risk' : 'good'">
            <div class="t">全年净利预测</div>
            <div class="v" :style="{ color: summary.proj_profit < 0 ? '#c62828' : '#2e7d32' }">{{ fmtWan(summary.proj_profit) }}</div>
            <div class="s">目标 {{ fmtWan(summary.profit_target) }} · 缺口 {{ fmtWan(summary.profit_gap) }}</div>
          </div>
        </div>

        <div class="fc-grid">
          <!-- 现金流入预测 -->
          <div class="fc-card">
            <div class="fc-card-title">现金流入预测<span class="tip">未收按"应收日+滞后"归集到预计回款月</span></div>
            <BaseChart v-if="cashOption" :option="cashOption" height="300px" />
            <EmptyState v-else empty text="暂无未收记录可预测" />
          </div>

          <!-- 全年落地预测 -->
          <div class="fc-card">
            <div class="fc-card-title">全年落地预测<span class="tip">已发布 {{ landing.elapsed }} 月 · YTD 年化 vs 目标</span></div>
            <div class="land-list">
              <div v-for="r in landingRows" :key="r.key" class="land-row">
                <div class="land-head">
                  <span class="land-label">{{ r.label }}</span>
                  <span class="land-rate" :style="{ color: (r.rate ?? 0) >= 100 ? '#2e7d32' : '#c62828' }">
                    预测达成 {{ fmtPct(r.rate) }}
                  </span>
                </div>
                <div class="land-bars">
                  <div class="land-bar">
                    <span class="bl">全年预测</span>
                    <div class="track"><div class="fill proj" :class="{ neg: r.projected < 0 }" :style="{ width: landingScale(r).proj + '%', background: r.projected < 0 ? '#e53935' : r.color }"></div></div>
                    <span class="bv">{{ fmtWan(r.projected) }}</span>
                  </div>
                  <div class="land-bar">
                    <span class="bl">年度目标</span>
                    <div class="track"><div class="fill tgt" :style="{ width: landingScale(r).tgt + '%' }"></div></div>
                    <span class="bv">{{ fmtWan(r.target) }}</span>
                  </div>
                </div>
                <div class="land-gap" :style="{ color: r.gap < 0 ? '#c62828' : '#2e7d32' }">
                  缺口 {{ fmtWan(r.gap) }}（YTD {{ fmtWan(r.ytd) }}）
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- What-if 沙盘 -->
        <div class="fc-card whatif">
          <div class="fc-card-title">🎚 What-if 沙盘<span class="tip">拖动假设，实时推演全年净利</span></div>
          <div class="wf-grid">
            <div class="wf-controls">
              <div class="wf-slider">
                <div class="wf-slabel">收入增长 <b :style="{ color: wf.revPct >= 0 ? '#2e7d32' : '#c62828' }">{{ wf.revPct > 0 ? '+' : '' }}{{ wf.revPct }}%</b></div>
                <input type="range" min="-20" max="20" step="1" v-model.number="wf.revPct" />
              </div>
              <div class="wf-slider">
                <div class="wf-slabel">毛利率提升 <b :style="{ color: wf.gmPt >= 0 ? '#2e7d32' : '#c62828' }">{{ wf.gmPt > 0 ? '+' : '' }}{{ wf.gmPt }}pt</b></div>
                <input type="range" min="-5" max="15" step="0.5" v-model.number="wf.gmPt" />
              </div>
              <button class="wf-reset" @click="wf.revPct = 0; wf.gmPt = 0">复位</button>
            </div>
            <div v-if="wfResult" class="wf-out">
              <div class="wf-out-main">
                <div class="wf-out-t">推演全年净利</div>
                <div class="wf-out-v" :style="{ color: wfResult.profit < 0 ? '#c62828' : '#2e7d32' }">{{ fmtWan(wfResult.profit) }}</div>
                <div class="wf-out-s">
                  净利率 {{ fmtPct(wfResult.netMargin) }} · 较基线
                  <b :style="{ color: wfResult.deltaVsBase >= 0 ? '#2e7d32' : '#c62828' }">{{ wfResult.deltaVsBase >= 0 ? '+' : '' }}{{ fmtWan(wfResult.deltaVsBase) }}</b>
                </div>
                <div class="wf-out-s">目标达成 {{ fmtPct(wfResult.rate) }} · 缺口 {{ fmtWan(wfResult.gap) }}</div>
              </div>
              <div v-if="breakeven" class="wf-hint">
                <div>💡 当前收入假设下：</div>
                <div>· 毛利率再提升 <b style="color:#e65100">{{ breakeven.toZero > 0 ? '+' + breakeven.toZero : breakeven.toZero }}pt</b> 可扭亏为零</div>
                <div v-if="breakeven.toTarget != null">· 提升 <b style="color:#1565c0">{{ breakeven.toTarget > 0 ? '+' + breakeven.toTarget : breakeven.toTarget }}pt</b> 可达年度目标</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </template>
    <EmptyState v-else empty text="暂无预测数据" />
  </div>
</template>

<style scoped>
.fc-panel { padding: 4px 0; }
.fc-filters { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 14px; }
.fc-filters select { padding: 6px 10px; border: 1px solid rgba(180,140,110,.28); border-radius: 8px; background: #fff; color: #5f4d3d; font-size: 13px; }
.fc-hint { font-size: 11.5px; color: #9b8070; }

.fc-kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 14px; }
@media (max-width: 820px) { .fc-kpis { grid-template-columns: repeat(2, 1fr); } }
.fc-kpi { padding: 12px 14px; border-radius: 12px; background: rgba(255,255,255,.7); border: 1px solid rgba(180,140,110,.16); border-left: 3px solid #9b8070; }
.fc-kpi.cash { border-left-color: #1565c0; }
.fc-kpi.risk { border-left-color: #e53935; }
.fc-kpi.good { border-left-color: #2e7d32; }
.fc-kpi .t { font-size: 12px; color: #9b8070; }
.fc-kpi .v { font-size: 21px; font-weight: 800; color: #5f4d3d; margin: 2px 0; }
.fc-kpi .s { font-size: 11px; color: #8a7665; }

.fc-grid { display: grid; grid-template-columns: 1.1fr 1fr; gap: 14px; margin-bottom: 14px; }
@media (max-width: 980px) { .fc-grid { grid-template-columns: 1fr; } }
.fc-card { background: rgba(255,255,255,.55); border: 1px solid rgba(180,140,110,.16); border-radius: 14px; padding: 12px 14px; }
.fc-card-title { font-size: 14px; font-weight: 700; color: #5f4d3d; margin-bottom: 8px; }
.fc-card-title .tip { font-size: 11px; font-weight: 400; color: #9b8070; margin-left: 8px; }

.land-list { display: flex; flex-direction: column; gap: 14px; padding-top: 4px; }
.land-row { border-bottom: 1px dashed rgba(180,140,110,.18); padding-bottom: 12px; }
.land-row:last-child { border-bottom: none; }
.land-head { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 6px; }
.land-label { font-size: 13.5px; font-weight: 700; color: #5f4d3d; }
.land-rate { font-size: 12px; font-weight: 700; }
.land-bars { display: flex; flex-direction: column; gap: 5px; }
.land-bar { display: flex; align-items: center; gap: 8px; }
.land-bar .bl { font-size: 11px; color: #9b8070; width: 56px; flex-shrink: 0; }
.land-bar .track { flex: 1; height: 14px; background: rgba(180,140,110,.1); border-radius: 7px; overflow: hidden; }
.land-bar .fill { height: 100%; border-radius: 7px; transition: width .3s; }
.land-bar .fill.tgt { background: repeating-linear-gradient(45deg, #c9a98e, #c9a98e 5px, #d8bda5 5px, #d8bda5 10px); }
.land-bar .bv { font-size: 11.5px; color: #5f4d3d; width: 72px; text-align: right; flex-shrink: 0; font-variant-numeric: tabular-nums; }
.land-gap { font-size: 11.5px; margin-top: 5px; font-weight: 600; }

.whatif { background: linear-gradient(120deg, rgba(122,159,212,.06), rgba(46,125,50,.05)); }
.wf-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
@media (max-width: 720px) { .wf-grid { grid-template-columns: 1fr; } }
.wf-controls { display: flex; flex-direction: column; gap: 16px; justify-content: center; }
.wf-slider .wf-slabel { font-size: 12.5px; color: #6b5a4a; margin-bottom: 6px; }
.wf-slider input[type=range] { width: 100%; accent-color: #c96342; }
.wf-reset { align-self: flex-start; border: 1px solid rgba(180,140,110,.3); background: #fff; color: #8a7665; font-size: 12px; padding: 4px 14px; border-radius: 8px; cursor: pointer; }
.wf-out { display: flex; flex-direction: column; gap: 10px; }
.wf-out-main { background: rgba(255,255,255,.7); border: 1px solid rgba(180,140,110,.16); border-radius: 12px; padding: 12px 14px; }
.wf-out-t { font-size: 12px; color: #9b8070; }
.wf-out-v { font-size: 26px; font-weight: 800; margin: 2px 0; }
.wf-out-s { font-size: 12px; color: #8a7665; }
.wf-hint { font-size: 12px; color: #6b5a4a; background: rgba(255,255,255,.5); border-radius: 10px; padding: 10px 12px; line-height: 1.7; }
.data-reloading { opacity: .55; transition: opacity .2s; }
</style>
