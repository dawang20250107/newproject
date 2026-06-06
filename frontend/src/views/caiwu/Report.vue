<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useCaiwuAuth } from '../../composables/useCaiwuAuth.js'
import { BUSINESS_UNITS, yearCST, lastMonthCST } from '../../constants.js'
import LevelToggle from '../../components/caiwu/report/LevelToggle.vue'
import AiAnalysisModal from '../../components/caiwu/AiAnalysisModal.vue'
import api from '../../api/caiwu.js'
import { fmtCompact } from '../../utils/format.js'
import { downloadBlob } from '../../utils/download.js'
import { streamAiAnalysis } from '../../utils/aiStream.js'
import EmptyState from '../../components/EmptyState.vue'

const auth = useCaiwuAuth()
const year = ref(lastMonthCST().year)
const selectedBu = ref('')
const level = ref(1)
const data = ref(null)
const loading = ref(false)
const loadErr = ref('')
const exporting = ref(false)

const aiText = ref('')
const aiLoading = ref(false)
const aiErr = ref('')
const aiVisible = ref(false)

const years = Array.from({ length: 5 }, (_, i) => yearCST() - 2 + i)
const accessibleBus = computed(() => {
  if (auth.isAdmin) return BUSINESS_UNITS
  return (auth.user?.departments || []).filter(d => BUSINESS_UNITS.includes(d))
})
const hasFullAccess = computed(() => auth.isAdmin)
const aiScope = computed(() => {
  if (selectedBu.value) return [selectedBu.value]
  const pool = hasFullAccess.value ? BUSINESS_UNITS : accessibleBus.value
  return pool.filter(b => b !== '集团总部')
})
const maxLevel = computed(() => {
  if (!auth.canView('report_l2')) return 1
  if (!auth.canView('report_l3')) return 2
  return 3
})
const canExport = computed(() => auth.canView('export'))

// ── matrix-derived state ─────────────────────────────────────────────────────
const months = computed(() => data.value?.months || [])
const rowsTree = computed(() => data.value?.rows || [])
const lastMonth = computed(() => data.value?.last_month || 0)
const noData = computed(() => !months.value.length)
const fmt = (v) => fmtCompact(v, { space: false })

// 扁平化树（带层级深度）用于矩阵渲染
const flatRows = computed(() => {
  const out = []
  for (const l1 of rowsTree.value) {
    out.push({ key: 'l1-' + l1.l1_id, depth: 0, name: l1.l1_name,
      values: l1.values, total: l1.total, calc: l1.is_calculated,
      pct: l1.pct || null, totalPct: l1.total_pct ?? null })
    for (const l2 of (l1.children || [])) {
      out.push({ key: `l2-${l1.l1_id}-${l2.l2_id}`, depth: 1, name: l2.l2_name,
        values: l2.values, total: l2.total,
        pct: l2.pct || null, totalPct: l2.total_pct ?? null })
      for (const l3 of (l2.children || [])) {
        out.push({ key: `l3-${l1.l1_id}-${l2.l2_id}-${l3.l3_id}`, depth: 2, name: l3.l3_name,
          values: l3.values, total: l3.total,
          pct: l3.pct || null, totalPct: l3.total_pct ?? null })
      }
    }
  }
  return out
})

// ── KPI（取最后一个月，环比上月，均来自矩阵）──────────────────────────────────
const KPI_DEFS = [
  { key: '主营业务收入', color: '#2e7d32' },
  { key: '主营业务成本', color: '#c62828' },
  { key: '运营毛利',    color: '#1565c0', calc: true },
  { key: '经营毛利',    color: '#6a1b9a', calc: true },
  { key: '经营净利',    color: '#e65100', calc: true },
]
const l1ByName = computed(() => {
  const m = {}; for (const r of rowsTree.value) m[r.l1_name] = r; return m
})
const kpis = computed(() => {
  const li = months.value.length - 1
  return KPI_DEFS.map(d => {
    const row = l1ByName.value[d.key]
    const amount = row && li >= 0 ? row.values[li] : null
    const prev = row && li >= 1 ? row.values[li - 1] : null
    let momPct = null
    if (amount !== null && prev !== null && prev !== 0) momPct = ((amount - prev) / Math.abs(prev)) * 100
    const isNeg = amount !== null && d.calc && amount < 0
    const momDown = momPct !== null && momPct < 0
    return { ...d, amount, momPct, isNeg, momDown }
  })
})
const fmtKpi = (v) => fmtCompact(v, { space: true })
function momLabel(pct) {
  if (pct === null) return ''
  const abs = Math.abs(pct).toFixed(1)
  return pct >= 0 ? `▲ ${abs}%` : `▼ ${abs}%`
}

// ── AI ───────────────────────────────────────────────────────────────────────
const aiScopeLabel = computed(() =>
  `${selectedBu.value || (aiScope.value.length + ' 个事业部')} · ${year.value}年${lastMonth.value || ''}${lastMonth.value ? '月' : ''}`)
const hasAnalysis = computed(() => !!aiText.value && !aiErr.value)
function viewAnalysis() { aiVisible.value = true }
async function runAiAnalysis() {
  aiLoading.value = true; aiErr.value = ''; aiText.value = ''; aiVisible.value = true
  try {
    await streamAiAnalysis('/report/ai-analysis/stream',
      { year: year.value, month: lastMonth.value || lastMonthCST().month, bus: aiScope.value },
      { onAnswer: d => { aiText.value += d }, onError: m => { aiErr.value = m } })
  } catch (e) {
    if (!aiErr.value) aiErr.value = e?.message || 'AI 分析失败'
  } finally { aiLoading.value = false }
}

async function load() {
  loading.value = true; loadErr.value = ''; aiText.value = ''; aiVisible.value = false
  try {
    const params = { year: year.value, level: level.value }
    if (selectedBu.value) params.bu = selectedBu.value
    const res = await api.get('/report/matrix', { params })
    data.value = res.data
  } catch (e) { loadErr.value = e?.error || e?.msg || '加载失败' }
  finally { loading.value = false }
}

async function exportReport() {
  exporting.value = true
  try {
    const params = { year: year.value, level: level.value }
    if (selectedBu.value) params.bu = selectedBu.value
    const res = await api.get('/report/export', { params, responseType: 'blob' })
    downloadBlob(res, `财务报表_${year.value}年.xlsx`)
  } catch (e) { alert(e?.msg || e?.error || '导出失败') }
  finally { exporting.value = false }
}

const route = useRoute()
onMounted(() => {
  const qb = route.query.bu, qy = +route.query.year
  if (qb && BUSINESS_UNITS.includes(qb)) selectedBu.value = qb
  if (qy >= 2000 && qy <= 2100) year.value = qy
  load()
})
</script>

<template>
  <div>
    <div class="topbar" style="align-items:flex-start">
      <h1>财务报表</h1>
      <div class="ctrl-row" style="justify-content:flex-end">
        <select v-model="year" class="sel-yr" @change="load">
          <option v-for="y in years" :key="y" :value="y">{{ y }} 年</option>
        </select>
        <select v-if="accessibleBus.length > 1" v-model="selectedBu" class="sel-bu" @change="load">
          <option value="">全部事业部</option>
          <option v-for="bu in accessibleBus" :key="bu" :value="bu">{{ bu }}</option>
        </select>
        <div class="ctrl-sep"></div>
        <LevelToggle v-model="level" :max-level="maxLevel" @update:model-value="load" />
        <button v-if="canExport" class="btn btn-ghost btn-sm" :disabled="exporting" @click="exportReport">
          {{ exporting ? '导出中…' : '↓ 导出美化表' }}
        </button>
      </div>
    </div>

    <EmptyState v-if="loading && !data" loading />
    <EmptyState v-else-if="loadErr" :error="loadErr" />
    <template v-else-if="data">
      <div :class="{ 'data-reloading': loading }">

      <div v-if="noData" class="nodata-banner">
        📭 {{ data.year }}年 · {{ data.bu || '全部事业部' }} 暂无已发布数据
      </div>

      <!-- KPI（最新月度快照）-->
      <div v-else class="kpi-grid kpi-5">
        <div v-for="kpi in kpis" :key="kpi.key" class="kpi-card"
          :class="{ 'kpi-calc': kpi.calc, 'kpi-negative': kpi.isNeg,
                    'kpi-mom-down': !kpi.isNeg && kpi.momDown, 'kpi-empty': kpi.amount === null }">
          <div class="label">{{ kpi.key }}</div>
          <div class="value" :class="{ 'value-neg': kpi.isNeg, 'value-empty': kpi.amount === null }"
            :style="kpi.amount === null || kpi.isNeg ? '' : `color:${kpi.momDown ? 'var(--danger)' : kpi.color}`">
            {{ fmtKpi(kpi.amount) }}
          </div>
          <div v-if="kpi.momPct !== null" class="mom-badge" :class="kpi.momDown ? 'mom-down' : 'mom-up'">{{ momLabel(kpi.momPct) }}</div>
          <div v-else class="mom-badge mom-neutral">— 环比</div>
          <div class="sub">{{ data.year }}年{{ lastMonth }}月{{ data.bu ? ' · ' + data.bu : '' }}</div>
        </div>
      </div>

      <!-- 月度矩阵表 -->
      <div class="card">
        <div class="report-head">
          <div class="section-title" style="margin:0">
            {{ data.bu || '全部事业部' }} · {{ data.year }}年 1月~{{ lastMonth }}月
            <span class="badge badge-primary" style="margin-left:8px">{{ ['一级','二级','三级'][level-1] }}科目</span>
          </div>
          <div class="ai-inline">
            <span class="ai-inline-orb">✨</span>
            <span class="ai-inline-label">AI 财务分析</span>
            <button v-if="hasAnalysis" class="btn btn-ghost btn-sm" @click="viewAnalysis">📄 查看分析</button>
            <button class="btn btn-primary btn-sm" :disabled="aiLoading || noData" @click="runAiAnalysis">
              {{ aiLoading ? '分析中…' : (hasAnalysis ? '↻ 重新分析' : '✨ AI 分析') }}
            </button>
          </div>
        </div>

        <div v-if="!noData" class="mx-wrap">
          <table class="mx-table">
            <thead>
              <tr>
                <th class="mx-name-h">科目</th>
                <th v-for="m in months" :key="m" class="mx-num">{{ m }}月</th>
                <th class="mx-num mx-total">合计</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in flatRows" :key="r.key" :class="['mx-row', `d${r.depth}`, { calc: r.calc, 'has-pct': r.pct }]">
                <td class="mx-name" :style="`padding-left:${10 + r.depth * 16}px`">
                  {{ r.name }}
                  <span v-if="r.pct && r.depth === 0" class="pct-tag">占总收入</span>
                </td>
                <td v-for="(v, i) in r.values" :key="i" class="mx-num" :class="{ neg: v < 0 }">
                  <div class="mx-amt">{{ fmt(v) }}</div>
                  <div v-if="r.pct" class="mx-pct">{{ r.pct[i] != null ? r.pct[i].toFixed(1) + '%' : '—' }}</div>
                </td>
                <td class="mx-num mx-total" :class="{ neg: r.total < 0 }">
                  <div class="mx-amt">{{ fmt(r.total) }}</div>
                  <div v-if="r.pct" class="mx-pct">{{ r.totalPct != null ? r.totalPct.toFixed(1) + '%' : '—' }}</div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
      </div>
    </template>

    <AiAnalysisModal
      :visible="aiVisible" :loading="aiLoading" :text="aiText" :error="aiErr"
      title="AI 财务分析" :subtitle="aiScopeLabel"
      @close="aiVisible = false" @reanalyze="runAiAnalysis" />
  </div>
</template>

<style scoped>
.nodata-banner {
  display: flex; align-items: center; gap: 8px; padding: 12px 16px; margin-bottom: 16px;
  background: rgba(180,140,110,.08); border: 1px dashed var(--border); border-radius: 12px;
  font-size: 13px; color: var(--muted);
}
.kpi-5 { grid-template-columns: repeat(5, 1fr) !important; gap: 12px; margin-bottom: 16px; }
@media (max-width: 900px) { .kpi-5 { grid-template-columns: repeat(3, 1fr) !important; } }
@media (max-width: 560px) { .kpi-5 { grid-template-columns: repeat(2, 1fr) !important; } }
.kpi-5 :deep(.kpi-card) { padding: 12px 14px; }
.kpi-5 :deep(.kpi-card .value) { font-size: 21px; }
.kpi-calc { border-left: 3px solid rgba(201,99,66,.3); }
.kpi-empty { opacity: .72; }
.value-empty { color: var(--muted) !important; opacity: .55; }
.kpi-negative { border-left: 3px solid var(--danger) !important; box-shadow: 0 3px 14px rgba(198,40,40,.22); background: rgba(198,40,40,.04); }
.kpi-mom-down { border-left: 3px solid rgba(198,40,40,.5); }
.value-neg { color: var(--danger) !important; }
.mom-badge { display: inline-block; font-size: 11px; font-weight: 600; padding: 2px 7px; border-radius: 10px; margin-top: 4px; }
.mom-up { background: rgba(46,125,50,.10); color: #2e7d32; }
.mom-down { background: rgba(198,40,40,.10); color: var(--danger); }
.mom-neutral { background: rgba(120,120,120,.08); color: var(--muted); font-weight: 400; }

.report-head { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px; margin-bottom: 12px; }
.ai-inline { display: flex; align-items: center; gap: 8px; }
.ai-inline-orb { font-size: 16px; filter: drop-shadow(0 0 5px rgba(201,99,66,0.45)); }
.ai-inline-label { font-size: 12px; font-weight: 700; color: var(--muted); margin-right: 2px; }
@media (max-width: 560px) { .ai-inline-label { display: none; } }

/* ── 月度矩阵表（压缩：小字号、紧行高、首列与表头吸附、数字等宽）── */
.mx-wrap { overflow: auto; max-height: calc(100vh - 300px); border: 1px solid rgba(0,0,0,0.06); border-radius: 10px; }
.mx-table { border-collapse: separate; border-spacing: 0; font-size: 12px; min-width: 100%; }
.mx-table thead th {
  position: sticky; top: 0; z-index: 3; background: #f4efeb; color: var(--muted);
  font-weight: 700; padding: 7px 10px; white-space: nowrap; border-bottom: 1px solid rgba(0,0,0,0.08);
}
.mx-name-h { position: sticky; left: 0; z-index: 4; text-align: left; }
.mx-num { text-align: right; font-variant-numeric: tabular-nums; min-width: 64px; }
.mx-total { background: #faf2ec; }
.mx-table thead .mx-total { background: #efe2d8; }
.mx-table tbody td { padding: 6px 10px; border-bottom: 1px solid rgba(0,0,0,0.035); }
.mx-name { position: sticky; left: 0; z-index: 2; background: #fff; white-space: nowrap; max-width: 240px; overflow: hidden; text-overflow: ellipsis; }
.mx-row.d0 .mx-name { font-weight: 700; color: var(--text); }
.mx-row.d1 .mx-name { color: #555; }
.mx-row.d2 .mx-name { color: var(--muted); font-size: 11.5px; }
.mx-row.calc { background: rgba(201,99,66,0.05); }
.mx-row.calc .mx-name { background: #fbf1ec; color: #8a3b22; font-weight: 800; }
.mx-row.calc .mx-num { font-weight: 700; color: #8a3b22; }
.mx-row:hover td { background: rgba(201,99,66,0.04); }
.mx-row:hover .mx-name { background: #fbf1ec; }
.mx-num.neg { color: var(--danger); }
.mx-total { font-weight: 700; }

/* 费销比：成本/费用/集团管理费 行在金额下方加一行占总收入百分比 */
.mx-pct { font-size: 10px; line-height: 1.2; color: #5b7763; font-weight: 600; margin-top: 1px; }
.mx-row.has-pct .mx-num { vertical-align: top; }
.mx-row.has-pct .mx-amt { line-height: 1.3; }
.pct-tag {
  display: inline-block; margin-left: 6px; padding: 0 6px; border-radius: 8px;
  font-size: 10px; font-weight: 600; color: #5b7763; background: rgba(91,119,99,0.12);
  vertical-align: middle;
}
</style>
