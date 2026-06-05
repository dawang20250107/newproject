<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useCaiwuAuth } from '../../composables/useCaiwuAuth.js'
import { BUSINESS_UNITS, yearCST, lastMonthCST } from '../../constants.js'
import ReportTable from '../../components/caiwu/report/ReportTable.vue'
import LevelToggle from '../../components/caiwu/report/LevelToggle.vue'
import AiAnalysisModal from '../../components/caiwu/AiAnalysisModal.vue'
import api from '../../api/caiwu.js'
import { fmtCompact } from '../../utils/format.js'
import { downloadBlob } from '../../utils/download.js'
import { streamAiAnalysis } from '../../utils/aiStream.js'
import EmptyState from '../../components/EmptyState.vue'

const auth = useCaiwuAuth()
// 默认展示上月：当月财务数据通常尚未导入/发布
const year = ref(lastMonthCST().year)
const month = ref(lastMonthCST().month)
const selectedBu = ref('')
const level = ref(1)
// 趋势线列开关（记忆用户偏好）：行多时可一键收起，仅看环比数字，保持清爽
const showTrend = ref(localStorage.getItem('report_show_trend') !== '0')
watch(showTrend, v => localStorage.setItem('report_show_trend', v ? '1' : '0'))
const data = ref(null)
const loading = ref(false)
const loadErr = ref('')
const exporting = ref(false)

// AI analysis state
const aiText = ref('')
const aiLoading = ref(false)
const aiErr = ref('')
const aiVisible = ref(false)

const years = Array.from({ length: 5 }, (_, i) => yearCST() - 2 + i)
const months = Array.from({ length: 12 }, (_, i) => i + 1)

const accessibleBus = computed(() => {
  if (auth.isAdmin) return BUSINESS_UNITS
  return (auth.user?.departments || []).filter(d => BUSINESS_UNITS.includes(d))
})

const hasFullAccess = computed(() => auth.isAdmin)

// For global AI analysis: all BUs except 集团总部
const aiScope = computed(() => {
  if (selectedBu.value) return [selectedBu.value]
  if (hasFullAccess.value) return BUSINESS_UNITS.filter(b => b !== '集团总部')
  return accessibleBus.value.filter(b => b !== '集团总部')
})

const maxLevel = computed(() => {
  if (!auth.canView('report_l2')) return 1
  if (!auth.canView('report_l3')) return 2
  return 3
})
const canExport = computed(() => auth.canView('export'))

// ── KPI definitions ──────────────────────────────────────────────────────────
const KPI_DEFS = [
  { key: '主营业务收入', color: '#2e7d32' },
  { key: '主营业务成本', color: '#c62828' },
  { key: '运营毛利',    color: '#1565c0', calc: true },
  { key: '经营毛利',    color: '#6a1b9a', calc: true },
  { key: '经营净利',    color: '#e65100', calc: true },
]

const kpis = computed(() => {
  const map = {}
  for (const row of (data.value?.rows || [])) map[row.l1_name] = parseFloat(row.amount ?? 0)
  const prevKpis = data.value?.prev_kpis || {}
  return KPI_DEFS.map(d => {
    const amount = d.key in map ? map[d.key] : null
    const prev = prevKpis[d.key] ?? null
    let momPct = null
    if (amount !== null && prev !== null && prev !== 0) {
      momPct = ((amount - prev) / Math.abs(prev)) * 100
    }
    const isNeg = amount !== null && d.calc && amount < 0
    const momDown = momPct !== null && momPct < 0
    return { ...d, amount, momPct, isNeg, momDown }
  })
})

const noData = computed(() => !(data.value?.rows?.length))

// 亿/万 两级单位（单位前带空格），万元以下两位小数；空值显示「—」
const fmtKpi = (v) => fmtCompact(v, { space: true })

function momLabel(pct) {
  if (pct === null) return ''
  const abs = Math.abs(pct).toFixed(1)
  return pct >= 0 ? `▲ ${abs}%` : `▼ ${abs}%`
}

// ── AI analysis (modal-driven) ─────────────────────────────────────────────────
const aiScopeLabel = computed(() =>
  `${selectedBu.value || (aiScope.value.length + ' 个事业部')} · ${year.value}年${month.value}月`
)
const hasAnalysis = computed(() => !!aiText.value && !aiErr.value)

function viewAnalysis() {
  aiVisible.value = true
}

async function runAiAnalysis() {
  aiLoading.value = true
  aiErr.value = ''
  aiText.value = ''
  aiVisible.value = true
  try {
    // 流式逐字返回（报表用快模型，基本秒开逐字）。
    await streamAiAnalysis('/report/ai-analysis/stream',
      { year: year.value, month: month.value, bus: aiScope.value },
      {
        onAnswer: d => { aiText.value += d },
        onError: m => { aiErr.value = m },
      })
  } catch (e) {
    if (!aiErr.value) aiErr.value = e?.message || 'AI 分析失败'
  } finally {
    aiLoading.value = false
  }
}

async function load() {
  loading.value = true
  loadErr.value = ''
  aiText.value = ''
  aiVisible.value = false
  try {
    const params = { year: year.value, month: month.value, level: level.value }
    if (selectedBu.value) params.bu = selectedBu.value
    const res = await api.get('/report', { params })
    data.value = res.data
  } catch (e) {
    loadErr.value = e?.error || '加载失败'
  } finally {
    loading.value = false
  }
}

async function exportReport() {
  exporting.value = true
  try {
    const params = { year: year.value, month: month.value, level: level.value }
    if (selectedBu.value) params.bu = selectedBu.value
    const res = await api.get('/report/export', { params, responseType: 'blob' })
    downloadBlob(res, `财务报表_${year.value}年${month.value}月.xlsx`)
  } catch (e) {
    alert(e?.msg || e?.error || '导出失败')
  } finally {
    exporting.value = false
  }
}

const route = useRoute()
onMounted(() => {
  // 支持从驾驶舱对话「下钻」带入事业部 / 期间
  const qb = route.query.bu, qy = +route.query.year, qm = +route.query.month
  if (qb && BUSINESS_UNITS.includes(qb)) selectedBu.value = qb
  if (qy >= 2000 && qy <= 2100) year.value = qy
  if (qm >= 1 && qm <= 12) month.value = qm
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
        <select v-model="month" class="sel-mo" @change="load">
          <option v-for="m in months" :key="m" :value="m">{{ m }} 月</option>
        </select>
        <select v-if="accessibleBus.length > 1" v-model="selectedBu" class="sel-bu" @change="load">
          <option value="">全部事业部</option>
          <option v-for="bu in accessibleBus" :key="bu" :value="bu">{{ bu }}</option>
        </select>
        <div class="ctrl-sep"></div>
        <LevelToggle v-model="level" :max-level="maxLevel" @update:model-value="load" />
        <button v-if="canExport" class="btn btn-ghost btn-sm" :disabled="exporting" @click="exportReport">
          {{ exporting ? '导出中…' : '导出 Excel' }}
        </button>
      </div>
    </div>

    <EmptyState v-if="loading && !data" loading />
    <EmptyState v-else-if="loadErr" :error="loadErr" />
    <template v-else-if="data">
      <div :class="{ 'data-reloading': loading }">

      <!-- ── KPI cards ──────────────────────────────────────────────────────── -->
      <div v-if="noData" class="nodata-banner">
        📭 {{ data.year }}年{{ data.month }}月 · {{ data.bu || '全部事业部' }} 暂无已发布数据
      </div>
      <div class="kpi-grid kpi-5">
        <div
          v-for="kpi in kpis" :key="kpi.key"
          class="kpi-card"
          :class="{
            'kpi-calc': kpi.calc,
            'kpi-negative': kpi.isNeg,
            'kpi-mom-down': !kpi.isNeg && kpi.momDown,
            'kpi-empty': kpi.amount === null,
          }"
        >
          <div class="label">{{ kpi.key }}</div>
          <div
            class="value"
            :class="{ 'value-neg': kpi.isNeg, 'value-empty': kpi.amount === null }"
            :style="kpi.amount === null || kpi.isNeg ? '' : `color:${kpi.momDown ? 'var(--danger)' : kpi.color}`"
          >{{ fmtKpi(kpi.amount) }}</div>

          <!-- MoM badge -->
          <div v-if="kpi.momPct !== null" class="mom-badge" :class="kpi.momDown ? 'mom-down' : 'mom-up'">
            {{ momLabel(kpi.momPct) }}
          </div>
          <div v-else class="mom-badge mom-neutral">— 环比</div>

          <div class="sub">{{ data.year }}年{{ data.month }}月{{ data.bu ? ' · ' + data.bu : '' }}</div>
        </div>
      </div>

      <!-- ── Report table（AI 分析并入表头，节省竖向空间）────────────────────── -->
      <div class="card">
        <div class="report-head">
          <div class="rh-left">
            <div class="section-title" style="margin:0">
              {{ data.bu || '全部事业部' }} · {{ data.year }}年{{ data.month }}月
              <span class="badge badge-primary" style="margin-left:8px">{{ ['一级', '二级', '三级'][level-1] }}明细</span>
            </div>
            <button
              class="trend-toggle" :class="{ on: showTrend }" role="switch" :aria-checked="showTrend"
              :title="showTrend ? '点击隐藏趋势线列' : '点击显示趋势线列'"
              @click="showTrend = !showTrend"
            >
              <span class="tt-track"><span class="tt-dot"></span></span>
              <span class="tt-label">趋势线</span>
            </button>
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
        <ReportTable :rows="data.rows || []" :level="level" :total="data.total || 0" :total-label="data.total_label || '合计'" :show-trend="showTrend" />
      </div>
      </div>
    </template>

    <!-- ── AI analysis modal ──────────────────────────────────────────────────── -->
    <AiAnalysisModal
      :visible="aiVisible"
      :loading="aiLoading"
      :text="aiText"
      :error="aiErr"
      title="AI 财务分析"
      :subtitle="aiScopeLabel"
      @close="aiVisible = false"
      @reanalyze="runAiAnalysis"
    />
  </div>
</template>

<style scoped>
/* ── no-data banner ───────────────────────────────────────────────────────── */
.nodata-banner {
  display: flex; align-items: center; gap: 8px;
  padding: 12px 16px; margin-bottom: 16px;
  background: rgba(180,140,110,.08); border: 1px dashed var(--border);
  border-radius: 12px; font-size: 13px; color: var(--muted);
}

/* ── KPI grid（紧凑：缩小卡片为表格让出空间）──────────────────────────────── */
.kpi-5 { grid-template-columns: repeat(5, 1fr) !important; gap: 12px; margin-bottom: 16px; }
@media (max-width: 900px) { .kpi-5 { grid-template-columns: repeat(3, 1fr) !important; } }
@media (max-width: 560px) { .kpi-5 { grid-template-columns: repeat(2, 1fr) !important; } }
.kpi-5 :deep(.kpi-card) { padding: 12px 14px; }
.kpi-5 :deep(.kpi-card .label) { margin-bottom: 4px; }
.kpi-5 :deep(.kpi-card .value) { font-size: 21px; }
.kpi-5 :deep(.kpi-card .sub) { margin-top: 3px; font-size: 11px; }

.kpi-calc { border-left: 3px solid rgba(201,99,66,.3); }

/* empty placeholder card */
.kpi-empty { opacity: .72; }
.value-empty { color: var(--muted) !important; opacity: .55; }

/* negative calc KPI: red border + static red glow */
.kpi-negative {
  border-left: 3px solid var(--danger) !important;
  box-shadow: 0 3px 14px rgba(198,40,40,.22);
  background: rgba(198,40,40,.04);
}

/* MoM down (non-calc): subtle red tint */
.kpi-mom-down { border-left: 3px solid rgba(198,40,40,.5); }

/* negative value: static red emphasis */
.value-neg {
  color: var(--danger) !important;
}

/* MoM badge */
.mom-badge {
  display: inline-block; font-size: 11px; font-weight: 600;
  padding: 2px 7px; border-radius: 10px; margin-top: 4px;
}
.mom-up      { background: rgba(46,125,50,.10); color: #2e7d32; }
.mom-down    { background: rgba(198,40,40,.10); color: var(--danger); }
.mom-neutral { background: rgba(120,120,120,.08); color: var(--muted); font-weight: 400; }

/* ── 表头（标题 + 行内 AI 分析，合二为一省空间）─────────────────────────────── */
.report-head {
  display: flex; align-items: center; justify-content: space-between;
  flex-wrap: wrap; gap: 10px; margin-bottom: 12px;
}
.rh-left { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }

/* 趋势线开关：迷你圆点滑块 */
.trend-toggle {
  display: inline-flex; align-items: center; gap: 6px;
  border: none; background: transparent; cursor: pointer;
  font-size: 12px; color: var(--muted); padding: 2px 2px; line-height: 1;
}
.tt-track {
  position: relative; width: 30px; height: 16px; border-radius: 10px;
  background: rgba(120,110,100,.28); transition: background .18s;
}
.tt-dot {
  position: absolute; top: 2px; left: 2px; width: 12px; height: 12px;
  border-radius: 50%; background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,.28);
  transition: transform .18s;
}
.trend-toggle.on .tt-track { background: var(--primary); }
.trend-toggle.on .tt-dot { transform: translateX(14px); }
.tt-label { font-weight: 600; }
.trend-toggle.on .tt-label { color: var(--primary); font-weight: 700; }
.ai-inline { display: flex; align-items: center; gap: 8px; }
.ai-inline-orb { font-size: 16px; filter: drop-shadow(0 0 5px rgba(201,99,66,0.45)); }
.ai-inline-label { font-size: 12px; font-weight: 700; color: var(--muted); margin-right: 2px; }
@media (max-width: 560px) {
  .ai-inline-label { display: none; }
}
</style>
