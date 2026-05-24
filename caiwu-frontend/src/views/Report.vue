<script setup>
import { ref, computed, onMounted } from 'vue'
import { useAuthStore } from '../stores/auth.js'
import { BUSINESS_UNITS, yearCST, monthCST } from '../constants.js'
import ReportTable from '../components/report/ReportTable.vue'
import LevelToggle from '../components/report/LevelToggle.vue'
import api from '../api/index.js'

const auth = useAuthStore()
const year = ref(yearCST())
const month = ref(monthCST())
const selectedBu = ref('')
const level = ref(1)
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

function fmtKpi(v) {
  if (v === null || v === undefined) return '—'
  const abs = Math.abs(v)
  if (abs >= 100000000) return (v / 100000000).toFixed(2) + ' 亿'
  if (abs >= 10000) return (v / 10000).toFixed(2) + ' 万'
  return v.toFixed(2)
}

function momLabel(pct) {
  if (pct === null) return ''
  const abs = Math.abs(pct).toFixed(1)
  return pct >= 0 ? `▲ ${abs}%` : `▼ ${abs}%`
}

// ── AI helpers ────────────────────────────────────────────────────────────────
function renderAiHtml(text) {
  if (!text) return []
  return text.split(/\n\n+/).map(para => {
    const html = para
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/\n/g, '<br>')
    return html
  })
}

async function runAiAnalysis() {
  aiLoading.value = true
  aiErr.value = ''
  aiVisible.value = true
  try {
    const res = await api.post('/report/ai-analysis', {
      year: year.value,
      month: month.value,
      bus: aiScope.value,
    })
    aiText.value = res.data?.analysis || res.analysis || ''
  } catch (e) {
    aiErr.value = e?.error || 'AI 分析失败'
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
    const url = URL.createObjectURL(res)
    const a = document.createElement('a')
    a.href = url
    a.download = `财务报表_${year.value}年${month.value}月.xlsx`
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    alert(e?.error || '导出失败')
  } finally {
    exporting.value = false
  }
}

onMounted(load)
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

    <div v-if="loading" class="empty"><div class="icon">⏳</div>加载中…</div>
    <div v-else-if="loadErr" class="empty" style="color:var(--danger)"><div class="icon">⚠️</div>{{ loadErr }}</div>
    <template v-else-if="data">

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

      <!-- ── AI analysis panel ──────────────────────────────────────────────── -->
      <div class="card ai-panel-card">
        <div class="ai-panel-header">
          <div class="section-title" style="margin:0">✨ AI 财务分析</div>
          <div style="display:flex;align-items:center;gap:10px">
            <span class="ai-scope-label">
              {{ selectedBu ? selectedBu : (aiScope.length + ' 个事业部') }}
              · {{ data.year }}年{{ data.month }}月
            </span>
            <button
              class="btn btn-ghost btn-sm"
              :disabled="aiLoading || noData"
              @click="runAiAnalysis"
            >{{ aiLoading ? '分析中…' : (aiVisible ? '✨ 重新分析' : '✨ AI 分析') }}</button>
          </div>
        </div>

        <div v-if="aiLoading" class="ai-loading">
          <span class="ai-spin">⏳</span> DeepSeek 分析中，请稍候…
        </div>
        <div v-else-if="aiErr" class="ai-error">{{ aiErr }}</div>
        <div v-else-if="aiVisible && aiText" class="ai-result">
          <p v-for="(para, i) in renderAiHtml(aiText)" :key="i" v-html="para"></p>
        </div>
        <div v-else-if="!aiVisible" class="ai-hint">
          点击「AI 分析」获取财务报表的智能解读与决策建议。
        </div>
      </div>

      <!-- ── Report table ───────────────────────────────────────────────────── -->
      <div class="card">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px">
          <div class="section-title" style="margin:0">
            {{ data.bu || '全部事业部' }} · {{ data.year }}年{{ data.month }}月
            <span class="badge badge-primary" style="margin-left:8px">{{ ['一级', '二级', '三级'][level-1] }}明细</span>
          </div>
        </div>
        <ReportTable :rows="data.rows || []" :level="level" :total="data.total || 0" :total-label="data.total_label || '合计'" />
      </div>
    </template>
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

/* ── KPI grid ─────────────────────────────────────────────────────────────── */
.kpi-5 { grid-template-columns: repeat(5, 1fr) !important; }
@media (max-width: 900px) { .kpi-5 { grid-template-columns: repeat(3, 1fr) !important; } }
@media (max-width: 560px) { .kpi-5 { grid-template-columns: repeat(2, 1fr) !important; } }

.kpi-calc { border-left: 3px solid rgba(201,99,66,.3); }

/* empty placeholder card */
.kpi-empty { opacity: .72; }
.value-empty { color: var(--muted) !important; opacity: .55; }

/* negative calc KPI: red border + breathing glow */
.kpi-negative {
  border-left: 3px solid var(--danger) !important;
  animation: negBreathe 2.2s ease-in-out infinite;
}
@keyframes negBreathe {
  0%, 100% { box-shadow: 0 2px 8px rgba(198,40,40,.10); }
  50%       { box-shadow: 0 4px 18px rgba(198,40,40,.30); background: rgba(198,40,40,.04); }
}

/* MoM down (non-calc): subtle red tint */
.kpi-mom-down { border-left: 3px solid rgba(198,40,40,.5); }

/* negative value pulsing text */
.value-neg {
  color: var(--danger) !important;
  animation: valuePulse 2.2s ease-in-out infinite;
}
@keyframes valuePulse {
  0%, 100% { opacity: 1; }
  50%       { opacity: .65; }
}

/* MoM badge */
.mom-badge {
  display: inline-block; font-size: 11px; font-weight: 600;
  padding: 2px 7px; border-radius: 10px; margin-top: 4px;
}
.mom-up      { background: rgba(46,125,50,.10); color: #2e7d32; }
.mom-down    { background: rgba(198,40,40,.10); color: var(--danger); }
.mom-neutral { background: rgba(120,120,120,.08); color: var(--muted); font-weight: 400; }

/* ── AI panel ─────────────────────────────────────────────────────────────── */
.ai-panel-card { padding: 18px 20px; }
.ai-panel-header {
  display: flex; align-items: center; justify-content: space-between;
  flex-wrap: wrap; gap: 10px; margin-bottom: 12px;
}
.ai-scope-label { font-size: 12px; color: var(--muted); }

.ai-loading {
  display: flex; align-items: center; gap: 8px;
  font-size: 13px; color: var(--muted); padding: 12px 0;
}
.ai-spin { animation: spin 1.2s linear infinite; display: inline-block; }
@keyframes spin { to { transform: rotate(360deg); } }

.ai-error { color: var(--danger); font-size: 13px; padding: 8px 0; }

.ai-result {
  margin-top: 8px; padding: 16px 20px;
  background: rgba(201,99,66,.04); border: 1px solid rgba(201,99,66,.15);
  border-radius: 12px; font-size: 13px; line-height: 1.8; color: var(--text);
}
.ai-result p { margin: 0 0 8px; }
.ai-result p:last-child { margin-bottom: 0; }

.ai-hint { font-size: 13px; color: var(--muted); padding: 4px 0; }
</style>
