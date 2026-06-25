<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import ar from '../../api/ar.js'
import BaseChart from '../../components/caiwu/charts/BaseChart.vue'
import { yearCST } from '../../constants.js'
import { fmtCompact } from '../../utils/format.js'
import { valueAxis, catAxis, gridFor, TOOLTIP } from '../../utils/chartTheme.js'
import ContextMenu from '../../components/ContextMenu.vue'
import { useContextMenu } from '../../composables/useContextMenu.js'
import { copyText } from '../../utils/clipboard.js'
import { useToast } from '../../composables/useToast.js'

const props = defineProps({ embedded: Boolean, selectedBu: { type: String, default: '' } })

const year = ref(yearCST())
const data = ref(null)
const loading = ref(false)
const err = ref('')
const expandedBu = ref('')

const years = Array.from({ length: 5 }, (_, i) => yearCST() - 2 + i)

const wan = v => v == null ? '—' : (v / 10000).toFixed(0) + '万'
const fmtRate = r => r == null ? '—' : r.toFixed(1) + '%'
function rateColor(r) {
  if (r == null) return '#9b8070'
  if (r >= 100) return '#2e7d32'
  if (r >= 80) return '#e65100'
  return '#c62828'
}

async function load() {
  loading.value = true; err.value = ''
  try {
    const p = { year: year.value }
    if (props.selectedBu) p.bu = props.selectedBu
    const res = await ar.targetDecomp(p)
    data.value = res.data
  } catch (e) {
    err.value = e?.error || '加载失败'
  } finally { loading.value = false }
}

watch(() => props.selectedBu, load)

// ── 完成率矩阵（行=事业部 × 列=月/季，OKR 式红绿看板）────────────────────────
const matrixGran = ref('month')   // 'month' | 'quarter'
const matrixCols = computed(() => matrixGran.value === 'month'
  ? Array.from({ length: 12 }, (_, i) => ({ key: 'm' + (i + 1), label: `${i + 1}月` }))
  : [1, 2, 3, 4].map(q => ({ key: 'q' + q, label: `Q${q}` })))

function cellOf(row, col) {
  if (col.key[0] === 'm') {
    const m = row.months[Number(col.key.slice(1)) - 1]
    return { target: m.target_revenue, actual: m.actual_revenue, rate: m.achieved, past: m.is_past }
  }
  const q = Number(col.key.slice(1))
  const ms = row.months.slice((q - 1) * 3, q * 3)
  const hasTarget = ms.some(m => m.target_revenue != null)
  const target = hasTarget ? ms.reduce((s, m) => s + (m.target_revenue || 0), 0) : null
  const actual = ms.reduce((s, m) => s + (m.actual_revenue || 0), 0)
  const past = ms.some(m => m.is_past)
  const rate = (target && past) ? +(actual / target * 100).toFixed(1) : null
  return { target, actual, rate, past }
}
const matrixRows = computed(() => (data.value?.rows || []).map(row => ({
  bu: row.bu, ytd: row.ytd_achieved,
  cells: matrixCols.value.map(c => cellOf(row, c)),
})))
function cellBg(c) {
  if (!c.past || c.rate == null) return 'transparent'
  if (c.rate >= 100) return 'rgba(46,125,50,0.16)'
  if (c.rate >= 80) return 'rgba(230,81,0,0.13)'
  return 'rgba(198,40,40,0.13)'
}
function cellTitle(c, label) {
  if (!c.past) return `${label}：未到期`
  const t = c.target != null ? wan(c.target) : '未设目标'
  return `${label}：目标 ${t} / 实际 ${wan(c.actual)}${c.rate != null ? ` / 达成 ${c.rate}%` : ''}`
}

// Overview bar chart: each BU's annual target vs YTD actual vs projected
const overviewOption = computed(() => {
  const rows = data.value?.rows || []
  if (!rows.length) return null
  const bus = rows.map(r => r.bu)
  const targets = rows.map(r => r.annual_target_revenue / 10000)
  const ytd = rows.map(r => r.ytd_actual_revenue / 10000)
  const projected = rows.map(r => r.projected != null ? r.projected / 10000 : null)

  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, ...TOOLTIP,
      formatter: p => {
        const bu = p[0]?.axisValueLabel
        const row = rows.find(r => r.bu === bu)
        if (!row) return bu
        return `<b>${bu}</b><br/>年度目标：${wan(row.annual_target_revenue)}<br/>YTD实际：${wan(row.ytd_actual_revenue)}（达成${fmtRate(row.ytd_achieved)}）<br/>全年预测：${row.projected != null ? wan(row.projected) : '—'}`
      } },
    legend: { data: ['年度目标', 'YTD实际', '全年预测'], bottom: 0, textStyle: { fontSize: 11 } },
    ...gridFor({ top: 20, right: 20, bottom: 48, left: 16 }),
    xAxis: { type: 'category', data: bus, axisLabel: { color: '#6b5a4a', fontSize: 11, interval: 0, rotate: bus.length > 6 ? 30 : 0 } },
    yAxis: { type: 'value', axisLabel: { color: '#9b8070', formatter: v => (v / 10000).toFixed(0) + '万' }, splitLine: { lineStyle: { color: 'rgba(180,140,110,.15)' } } },
    series: [
      { name: '年度目标', type: 'bar', data: targets, barMaxWidth: 28, itemStyle: { color: 'rgba(21,101,192,.25)', borderColor: '#1565c0', borderWidth: 1, borderType: 'dashed', borderRadius: [3, 3, 0, 0] } },
      { name: 'YTD实际', type: 'bar', data: ytd, barMaxWidth: 18, barGap: '-60%',
        itemStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: '#2e7d32' }, { offset: 1, color: '#81c784' }] }, borderRadius: [3, 3, 0, 0] } },
      { name: '全年预测', type: 'line', data: projected, symbol: 'diamond', symbolSize: 8, lineStyle: { type: 'dashed', color: '#e65100', width: 1.5 }, itemStyle: { color: '#e65100' } },
    ],
  }
})

// Monthly detail for an expanded BU
const monthlyOption = computed(() => {
  if (!expandedBu.value || !data.value) return null
  const row = data.value.rows.find(r => r.bu === expandedBu.value)
  if (!row) return null
  const past = row.months.filter(m => m.is_past)
  if (!past.length) return null
  const labels = past.map(m => `${m.month}月`)
  const targets = past.map(m => m.target_revenue != null ? m.target_revenue / 10000 : null)
  const actuals = past.map(m => m.actual_revenue / 10000)
  const achieved = past.map(m => m.achieved)

  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, ...TOOLTIP,
      formatter: p => {
        const mo = past[p[0]?.dataIndex]
        return mo ? `${mo.month}月<br/>目标：${mo.target_revenue != null ? wan(mo.target_revenue) : '—'}<br/>实际：${wan(mo.actual_revenue)}<br/>达成：${fmtRate(mo.achieved)}` : ''
      } },
    legend: { data: ['月目标', '月实际', '达成率'], bottom: 0, textStyle: { fontSize: 11 } },
    ...gridFor({ top: 24, right: 56, bottom: 48, left: 16 }),
    xAxis: { type: 'category', data: labels, axisLabel: { color: '#6b5a4a', fontSize: 11 } },
    yAxis: [
      { type: 'value', axisLabel: { color: '#9b8070', formatter: v => v.toFixed(0) + '万' }, splitLine: { lineStyle: { color: 'rgba(180,140,110,.15)' } } },
      { type: 'value', axisLabel: { color: '#e65100', formatter: v => v + '%' }, splitLine: { show: false }, min: 0, max: 150 },
    ],
    series: [
      { name: '月目标', type: 'bar', data: targets, barMaxWidth: 26, itemStyle: { color: 'rgba(21,101,192,.2)', borderColor: '#1565c0', borderWidth: 1, borderType: 'dashed', borderRadius: [3, 3, 0, 0] } },
      { name: '月实际', type: 'bar', data: actuals, barMaxWidth: 18, barGap: '-50%',
        itemStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: '#2e7d32' }, { offset: 1, color: '#a5d6a7' }] }, borderRadius: [3, 3, 0, 0] } },
      { name: '达成率', type: 'line', yAxisIndex: 1, data: achieved, smooth: true, symbol: 'circle', symbolSize: 6,
        lineStyle: { color: '#e65100', width: 2 }, itemStyle: { color: '#e65100' },
        markLine: { silent: true, lineStyle: { color: '#e65100', type: 'dashed' }, data: [{ yAxis: 100, label: { formatter: '目标线', color: '#e65100' } }] } },
    ],
  }
})

const toast = useToast()
// ── 右键上下文菜单 ────────────────────────────────────────────────────────────
const ctxTarget = useContextMenu()
const ctxTargetItems = computed(() => {
  const r = ctxTarget.menu.payload
  if (!r) return []
  return [
    {
      key: 'copy', label: '复制', icon: 'copy',
      children: [
        { key: 'copy-bu', label: '事业部', icon: 'cell', action: row => copyText(row.bu).then(ok => ok ? toast.success('已复制：' + row.bu) : toast.error('复制失败')) },
        { key: 'copy-ytd', label: 'YTD达成率', icon: 'cell', action: row => copyText(row.ytd != null ? row.ytd.toFixed(0) + '%' : '—').then(ok => ok ? toast.success('已复制') : toast.error('复制失败')) },
      ],
    },
  ]
})

onMounted(load)
</script>

<template>
  <div class="td-panel">
    <div class="td-head">
      <div class="td-title">🎯 目标分解 · 年度下钻</div>
      <div class="td-controls">
        <select v-model="year" class="td-sel" @change="load">
          <option v-for="y in years" :key="y" :value="y">{{ y }} 年</option>
        </select>
      </div>
    </div>

    <div v-if="loading" class="td-empty">加载中…</div>
    <div v-else-if="err" class="td-empty err">{{ err }}</div>
    <template v-else-if="data">
      <!-- Summary strip -->
      <div class="td-summary">
        <div class="tds-item">
          <div class="tds-label">集团年度目标</div>
          <div class="tds-val">{{ wan(data.summary.total_annual_target) }}</div>
        </div>
        <div class="tds-item">
          <div class="tds-label">YTD累计实际</div>
          <div class="tds-val">{{ wan(data.summary.total_ytd_actual) }}</div>
        </div>
        <div class="tds-item">
          <div class="tds-label">YTD达成率</div>
          <div class="tds-val" :style="`color:${rateColor(data.summary.total_ytd_achieved)}`">{{ fmtRate(data.summary.total_ytd_achieved) }}</div>
        </div>
        <div class="tds-item">
          <div class="tds-label">全年预测</div>
          <div class="tds-val">{{ wan(data.summary.total_projected) }}</div>
        </div>
        <div class="tds-item">
          <div class="tds-label">预测缺口</div>
          <div class="tds-val" :style="`color:${data.summary.total_gap > 0 ? '#c62828' : '#2e7d32'}`">
            {{ data.summary.total_gap != null ? (data.summary.total_gap > 0 ? '-' : '+') + wan(Math.abs(data.summary.total_gap)) : '—' }}
          </div>
        </div>
      </div>

      <!-- 完成率矩阵 -->
      <div class="card td-chart-card">
        <div class="td-matrix-head">
          <div class="section-title">完成率矩阵
            <span class="tdm-legend"><i class="lg lg-g"></i>≥100% <i class="lg lg-o"></i>80~100% <i class="lg lg-r"></i>&lt;80% <i class="lg lg-n"></i>未到期/无目标</span>
          </div>
          <div class="td-gran">
            <button :class="['tdg-btn', matrixGran === 'month' ? 'on' : '']" @click="matrixGran = 'month'">月度</button>
            <button :class="['tdg-btn', matrixGran === 'quarter' ? 'on' : '']" @click="matrixGran = 'quarter'">季度</button>
          </div>
        </div>
        <div v-if="matrixRows.length" class="td-matrix-wrap">
          <table class="td-matrix">
            <thead>
              <tr>
                <th class="l">事业部</th>
                <th v-for="c in matrixCols" :key="c.key">{{ c.label }}</th>
                <th class="ytd-col">YTD</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in matrixRows" :key="row.bu" @contextmenu.prevent="ctxTarget.open($event, row)">
                <td class="l bu" @click="expandedBu = expandedBu === row.bu ? '' : row.bu" style="cursor:pointer">{{ row.bu }}</td>
                <td v-for="(c, i) in row.cells" :key="i"
                    :style="`background:${cellBg(c)}`"
                    :title="cellTitle(c, matrixCols[i].label)">
                  <template v-if="c.past">
                    <div class="tdmx-rate" :style="`color:${rateColor(c.rate)}`">{{ c.rate != null ? c.rate.toFixed(0) + '%' : '—' }}</div>
                    <div class="tdmx-amt">{{ wan(c.actual) }}</div>
                  </template>
                  <span v-else class="tdmx-future">·</span>
                </td>
                <td class="ytd-col">
                  <span :style="`color:${rateColor(row.ytd)};font-weight:700`">{{ fmtRate(row.ytd) }}</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="td-empty">暂无目标数据</div>
      </div>

      <!-- Overview chart -->
      <div class="card td-chart-card">
        <div class="section-title" style="margin-bottom:8px">各事业部年度目标 vs YTD实际（点击行查看月度进度）</div>
        <BaseChart v-if="overviewOption" :option="overviewOption" height="280px" />
        <div v-else class="td-empty">暂无目标数据</div>
      </div>

      <!-- BU rows table -->
      <div class="card">
        <div class="section-title" style="margin-bottom:8px">事业部分解明细（点击展开月度进度）</div>
        <table class="td-table">
          <thead>
            <tr>
              <th class="l">事业部</th>
              <th>年度目标</th>
              <th>YTD实际</th>
              <th>YTD达成</th>
              <th>全年预测</th>
              <th>预测缺口</th>
            </tr>
          </thead>
          <tbody>
            <template v-for="row in data.rows" :key="row.bu">
              <tr class="td-row drillable" @click="expandedBu = expandedBu === row.bu ? '' : row.bu">
                <td class="l bu">{{ row.bu }} <span class="drill-hint">{{ expandedBu === row.bu ? '▲' : '▼' }}</span></td>
                <td>{{ wan(row.annual_target_revenue) }}</td>
                <td>{{ wan(row.ytd_actual_revenue) }}</td>
                <td><span :style="`color:${rateColor(row.ytd_achieved)};font-weight:700`">{{ fmtRate(row.ytd_achieved) }}</span></td>
                <td>{{ wan(row.projected) }}</td>
                <td :style="`color:${row.gap > 0 ? '#c62828' : '#2e7d32'}`">
                  {{ row.gap != null ? (row.gap > 0 ? '缺口 ' : '超额 ') + wan(Math.abs(row.gap)) : '—' }}
                </td>
              </tr>
              <!-- Monthly detail expanded -->
              <tr v-if="expandedBu === row.bu" class="td-detail-row">
                <td colspan="6" style="padding:0">
                  <div class="td-monthly">
                    <div class="td-monthly-chart">
                      <BaseChart v-if="monthlyOption" :option="monthlyOption" height="220px" />
                      <div v-else class="td-empty">暂无月度目标数据</div>
                    </div>
                    <div class="td-monthly-months">
                      <div v-for="m in row.months.filter(m => m.is_past)" :key="m.month" class="tdm-item">
                        <div class="tdm-mo">{{ m.month }}月</div>
                        <div class="tdm-bar-wrap">
                          <div class="tdm-bar" :style="`width:${m.achieved ? Math.min(100, m.achieved) : 0}%;background:${rateColor(m.achieved)}`"></div>
                        </div>
                        <div class="tdm-rate" :style="`color:${rateColor(m.achieved)}`">{{ fmtRate(m.achieved) }}</div>
                      </div>
                    </div>
                  </div>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
    </template>
    <div v-else class="td-empty">暂无数据</div>
    <ContextMenu :ctx="ctxTarget" :items="ctxTargetItems" />
  </div>
</template>

<style scoped>
.td-panel { padding: 16px 0; }
.td-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; }
.td-title { font-size: 16px; font-weight: 800; color: var(--text); letter-spacing: .2px; }
.td-sel {
  height: 32px; padding: 0 12px; border: 1px solid transparent;
  background: var(--surface-tint); border-radius: var(--radius-xs);
  font-size: 13px; color: var(--text); cursor: pointer; outline: none;
  transition: background .15s, color .15s, border-color .15s, box-shadow .15s;
}
.td-sel:hover, .td-sel:focus {
  background: color-mix(in srgb, var(--primary) 9%, transparent);
  color: var(--primary); border-color: var(--border-strong);
}
.td-sel:focus { box-shadow: 0 0 0 3px var(--primary-glow); }
.td-empty { text-align: center; padding: 40px; color: var(--muted); }
.td-empty.err { color: var(--c-danger); }
.td-chart-card { padding: 16px; margin-bottom: 14px; }

/* 概览条 */
.td-summary { position: relative; display: flex; gap: 0; margin-bottom: 14px;
  background: var(--surface-1); border: 1px solid var(--glass-border); border-radius: var(--radius);
  overflow: hidden; box-shadow: var(--shadow-sm); }
.td-summary::before { content: ''; position: absolute; top: 0; left: 0; right: 0; height: 3px; background: var(--grad); opacity: .9; }
.tds-item { flex: 1; padding: 14px 16px 12px; text-align: center; border-right: 1px solid var(--border-soft); transition: background .15s; }
.tds-item:last-child { border-right: none; }
.tds-item:hover { background: var(--surface-tint); }
.tds-label { font-size: 11px; color: var(--muted); margin-bottom: 5px; font-weight: 600; }
.tds-val { font-size: 19px; font-weight: 800; color: var(--text); font-variant-numeric: tabular-nums; letter-spacing: -.3px; }

.td-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.td-table th { background: var(--surface-tint); color: var(--muted); padding: 9px 12px; font-weight: 700; text-align: right; white-space: nowrap; }
.td-table th.l { text-align: left; }
.td-table td { padding: 10px 12px; border-bottom: 1px solid var(--border-soft); text-align: right; color: var(--text); font-variant-numeric: tabular-nums; }
.td-table td.l { text-align: left; }
.td-row { cursor: pointer; transition: background .14s; }
.td-row:hover { background: var(--surface-tint); }
.bu { font-weight: 700; color: var(--text); }
.drill-hint { font-size: 11px; color: var(--muted); margin-left: 4px; }
.td-detail-row { background: var(--surface-tint); }

.td-monthly { padding: 14px; display: grid; grid-template-columns: 1fr 260px; gap: 16px; }
.td-monthly-months { display: flex; flex-direction: column; gap: 5px; justify-content: center; }
.tdm-item { display: flex; align-items: center; gap: 8px; }
.tdm-mo { font-size: 11px; color: var(--text-2); width: 24px; flex-shrink: 0; }
.tdm-bar-wrap { flex: 1; height: 10px; background: var(--border); border-radius: 5px; overflow: hidden; }
.tdm-bar { height: 100%; border-radius: 5px; transition: width .4s cubic-bezier(.4,0,.2,1); }
.tdm-rate { font-size: 11px; font-weight: 700; width: 40px; text-align: right; font-variant-numeric: tabular-nums; }
.drillable { cursor: pointer; }
.drillable:hover td { background: var(--surface-tint); }

/* 完成率矩阵 */
.td-matrix-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.tdm-legend { font-size: 11px; font-weight: 400; color: var(--muted); margin-left: 10px; }
.lg { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin: 0 3px 0 8px; vertical-align: -1px; }
.lg-g { background: color-mix(in srgb, var(--c-success) 55%, transparent); }
.lg-o { background: color-mix(in srgb, var(--c-warn) 50%, transparent); }
.lg-r { background: color-mix(in srgb, var(--c-danger) 50%, transparent); }
.lg-n { background: var(--border); }
.td-gran { display: inline-flex; gap: 0; border: 1px solid var(--border-strong); border-radius: var(--radius-xs); overflow: hidden; }
.tdg-btn { padding: 4px 13px; border: none; background: transparent; font-size: 12px; font-weight: 600; color: var(--muted); cursor: pointer; transition: all .14s; }
.tdg-btn + .tdg-btn { border-left: 1px solid var(--border); }
.tdg-btn.on { background: var(--primary); color: #fff; }
.td-matrix-wrap { overflow-x: auto; border-radius: var(--radius-xs); }
.td-matrix { width: 100%; border-collapse: collapse; font-size: 12px; }
.td-matrix th { background: var(--surface-tint); color: var(--muted); padding: 7px 8px; font-weight: 700; text-align: center; white-space: nowrap; }
.td-matrix th.l { text-align: left; }
.td-matrix td { padding: 5px 6px; border: 1px solid var(--border-soft); text-align: center; min-width: 56px; }
.td-matrix td.l { text-align: left; white-space: nowrap; }
.tdmx-rate { font-weight: 700; font-size: 12px; font-variant-numeric: tabular-nums; }
.tdmx-amt { font-size: 10px; color: var(--muted); margin-top: 1px; font-variant-numeric: tabular-nums; }
.tdmx-future { color: var(--muted-light); }
.ytd-col { background: var(--surface-tint); }
@media (max-width: 768px) {
  .td-monthly { grid-template-columns: 1fr; }
  .td-summary { flex-wrap: wrap; }
  .tds-item { flex: 0 0 50%; border-bottom: 1px solid var(--border-soft); }
}
</style>
