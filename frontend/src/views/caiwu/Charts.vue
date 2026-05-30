<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useCaiwuAuth } from '../../composables/useCaiwuAuth.js'
import { BUSINESS_UNITS, yearCST, monthCST } from '../../constants.js'
import TrendLineChart from '../../components/caiwu/charts/TrendLineChart.vue'
import WaterfallChart from '../../components/caiwu/charts/WaterfallChart.vue'
import AiAnalysisModal from '../../components/caiwu/AiAnalysisModal.vue'
import api from '../../api/caiwu.js'
import { fmtCompact } from '../../utils/format.js'
import EmptyState from '../../components/EmptyState.vue'

const auth = useCaiwuAuth()

// ── Global BU + year filter ─────────────────────────────
const globalBu = ref('')
const trendYear = ref(yearCST())

const years = Array.from({ length: 5 }, (_, i) => yearCST() - 2 + i)

const accessibleBus = computed(() => {
  if (auth.isAdmin) return BUSINESS_UNITS
  return (auth.user?.departments || []).filter(d => BUSINESS_UNITS.includes(d))
})

const canTrend = computed(() => auth.canView('chart_trend'))
const canWaterfall = computed(() => auth.canView('chart_waterfall'))

// ── Trend chart state ───────────────────────────────────
const trendData = ref(null)
const trendLoading = ref(false)
const trendErr = ref('')
const selectedL1Ids = ref([])
const trendAiText = ref('')
const trendAiLoading = ref(false)
const trendAiErr = ref('')
const trendAiVisible = ref(false)

async function loadTrend() {
  if (!globalBu.value) return
  trendLoading.value = true
  trendErr.value = ''
  try {
    const res = await api.get('/charts/trend', { params: { bu: globalBu.value, year: trendYear.value } })
    trendData.value = res.data
    // default: select first 3 L1 categories
    if (selectedL1Ids.value.length === 0 && res.data.l1_categories?.length) {
      selectedL1Ids.value = res.data.l1_categories.slice(0, 3).map(c => c.id)
    }
  } catch (e) {
    trendErr.value = e?.error || '加载失败'
  } finally {
    trendLoading.value = false
  }
}

function toggleL1(id) {
  const i = selectedL1Ids.value.indexOf(id)
  if (i === -1) selectedL1Ids.value.push(id)
  else if (selectedL1Ids.value.length > 1) selectedL1Ids.value.splice(i, 1)
}

const trendHasAi = computed(() => !!trendAiText.value && !trendAiErr.value)

async function analyzeTrend() {
  if (!trendData.value) return
  trendAiLoading.value = true
  trendAiErr.value = ''
  trendAiVisible.value = true
  try {
    const res = await api.post('/charts/ai-analysis', {
      chart_type: 'trend',
      bu: globalBu.value,
      year: trendYear.value,
      data: trendData.value,
      selected_l1_ids: selectedL1Ids.value,
    })
    trendAiText.value = res.data?.analysis || res.data || ''
  } catch (e) {
    trendAiErr.value = e?.error || 'AI 分析失败'
  } finally {
    trendAiLoading.value = false
  }
}

// ── Waterfall chart state ───────────────────────────────
const wfYear = ref(yearCST())
const wfMonth = ref(monthCST())
const wfCmpYear = ref(yearCST())
const wfCmpMonth = ref(monthCST() === 1 ? 12 : monthCST() - 1)
const wfData = ref(null)
const wfLoading = ref(false)
const wfErr = ref('')
const wfAiText = ref('')
const wfAiLoading = ref(false)
const wfAiErr = ref('')
const wfAiVisible = ref(false)

const months = Array.from({ length: 12 }, (_, i) => i + 1)

async function loadWaterfall() {
  if (!globalBu.value) return
  wfLoading.value = true
  wfErr.value = ''
  try {
    const res = await api.get('/charts/waterfall', {
      params: { bu: globalBu.value, year: wfYear.value, month: wfMonth.value, compare_year: wfCmpYear.value, compare_month: wfCmpMonth.value },
    })
    wfData.value = res.data
  } catch (e) {
    wfErr.value = e?.error || '加载失败'
  } finally {
    wfLoading.value = false
  }
}

const wfHasAi = computed(() => !!wfAiText.value && !wfAiErr.value)
const changedFactors = computed(() => (wfData.value?.factors || []).filter(f => f.delta !== 0))
const trendScopeLabel = computed(() => `${globalBu.value} · ${trendYear.value}年`)
const wfScopeLabel = computed(() => `${globalBu.value} · ${wfCmpYear.value}年${wfCmpMonth.value}月 → ${wfYear.value}年${wfMonth.value}月`)

async function analyzeWaterfall() {
  if (!wfData.value) return
  wfAiLoading.value = true
  wfAiErr.value = ''
  wfAiVisible.value = true
  try {
    const res = await api.post('/charts/ai-analysis', {
      chart_type: 'waterfall',
      bu: globalBu.value,
      year: wfYear.value,
      month: wfMonth.value,
      data: wfData.value,
    })
    wfAiText.value = res.data?.analysis || res.data || ''
  } catch (e) {
    wfAiErr.value = e?.error || 'AI 分析失败'
  } finally {
    wfAiLoading.value = false
  }
}

// 亿/万 两级单位（单位前带空格），万元以下两位小数
const fmtAmt = (v) => fmtCompact(v, { space: true })

// ── Watch globalBu / trendYear to reload ────────────────
watch(globalBu, () => {
  if (canTrend.value) loadTrend()
  if (canWaterfall.value) loadWaterfall()
})

watch(trendYear, () => {
  if (canTrend.value) loadTrend()
})

onMounted(() => {
  if (accessibleBus.value.length) {
    globalBu.value = accessibleBus.value[0]
    // watchers above will fire loadTrend / loadWaterfall
  }
})
</script>

<template>
  <div>
    <div class="topbar">
      <h1>图表分析</h1>
      <!-- Global BU + Year filter -->
      <div class="ctrl-row">
        <select v-model="globalBu" class="sel-bu">
          <option v-for="bu in accessibleBus" :key="bu" :value="bu">{{ bu }}</option>
        </select>
        <div class="ctrl-sep"></div>
        <select v-model="trendYear" class="sel-yr">
          <option v-for="y in years" :key="y" :value="y">{{ y }} 年</option>
        </select>
      </div>
    </div>

    <!-- ── Trend Line Chart ──────────────────────────────── -->
    <div v-if="canTrend" class="card">
      <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;margin-bottom:16px">
        <div class="section-title" style="margin:0">收入 / 利润走势（折线图）</div>
        <div style="display:flex;gap:8px">
          <button
            v-if="trendHasAi"
            class="btn btn-ghost btn-sm"
            @click="trendAiVisible = true"
          >📄 查看分析</button>
          <button
            class="btn btn-primary btn-sm"
            :disabled="trendAiLoading || !trendData"
            @click="analyzeTrend"
          >{{ trendAiLoading ? '分析中…' : (trendHasAi ? '↻ 重新分析' : '✨ AI分析') }}</button>
        </div>
      </div>

      <!-- L1 category selector -->
      <div v-if="trendData?.l1_categories?.length" style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:14px">
        <button
          v-for="cat in trendData.l1_categories"
          :key="cat.id"
          :class="['l1-chip', selectedL1Ids.includes(cat.id) ? 'on' : '']"
          @click="toggleL1(cat.id)"
        >{{ cat.name }}</button>
      </div>

      <div v-if="trendLoading && !trendData" class="empty"><div class="icon">⏳</div>加载中…</div>
      <div v-else-if="!trendLoading && trendErr" class="empty" style="color:var(--danger)">{{ trendErr }}</div>
      <TrendLineChart
        v-else-if="trendData"
        :class="{ 'data-reloading': trendLoading }"
        :months="trendData.months"
        :l1-categories="trendData.l1_categories"
        :selected-l1-ids="selectedL1Ids"
        height="340px"
      />
      <div v-else class="empty"><div class="icon">📊</div>请选择事业部查看</div>
    </div>

    <!-- ── Waterfall Chart ───────────────────────────────── -->
    <div v-if="canWaterfall" class="card">
      <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;margin-bottom:16px">
        <div class="section-title" style="margin:0">因素分析（瀑布图）</div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
          <button
            v-if="wfHasAi"
            class="btn btn-ghost btn-sm"
            @click="wfAiVisible = true"
          >📄 查看分析</button>
          <button
            class="btn btn-primary btn-sm"
            :disabled="wfAiLoading || !wfData"
            @click="analyzeWaterfall"
          >{{ wfAiLoading ? '分析中…' : (wfHasAi ? '↻ 重新分析' : '✨ AI分析') }}</button>
          <span style="font-size:12px;color:var(--muted)">对比</span>
          <select v-model="wfCmpYear" class="sel-yr" @change="loadWaterfall">
            <option v-for="y in years" :key="y" :value="y">{{ y }}</option>
          </select>
          <select v-model="wfCmpMonth" class="sel-mo" @change="loadWaterfall">
            <option v-for="m in months" :key="m" :value="m">{{ m }}月</option>
          </select>
          <span style="font-size:12px;color:var(--muted)">→</span>
          <select v-model="wfYear" class="sel-yr" @change="loadWaterfall">
            <option v-for="y in years" :key="y" :value="y">{{ y }}</option>
          </select>
          <select v-model="wfMonth" class="sel-mo" @change="loadWaterfall">
            <option v-for="m in months" :key="m" :value="m">{{ m }}月</option>
          </select>
        </div>
      </div>

      <div v-if="wfLoading && !wfData" class="empty"><div class="icon">⏳</div>加载中…</div>
      <div v-else-if="!wfLoading && wfErr" class="empty" style="color:var(--danger)">{{ wfErr }}</div>
      <div v-else-if="wfData" :class="{ 'data-reloading': wfLoading }">
        <div v-if="!wfData.factors?.length" class="empty" style="padding:16px">
          <div class="icon">💡</div>
          所选两个期间的数据无变动，或对比期/当期暂无已发布数据。请调整对比期间或先在「数据加工」中发布数据。
        </div>
        <template v-else-if="wfData.waterfall?.length">
          <WaterfallChart :waterfall="wfData.waterfall" height="380px" />
          <!-- Factor detail table (only changed factors; A股 colors: 涨红跌绿) -->
          <div v-if="changedFactors.length" style="margin-top:16px">
            <div class="section-title">因素明细</div>
            <div class="table-wrap">
              <table>
                <thead><tr><th>一级科目</th><th class="amt">对比期</th><th class="amt">当期</th><th class="amt">利润影响</th></tr></thead>
                <tbody>
                  <tr v-for="f in changedFactors" :key="f.l1_id">
                    <td>{{ f.name }}<span v-if="f.is_driver" class="driver-dot" title="关键驱动因素">●</span></td>
                    <td class="amt">{{ fmtAmt(f.base) }}</td>
                    <td class="amt">{{ fmtAmt(f.current) }}</td>
                    <td class="amt" :class="f.delta >= 0 ? 'amt-red' : 'amt-green'">
                      {{ f.delta >= 0 ? '+' : '' }}{{ fmtAmt(f.delta) }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </template>
      </div>
      <div v-else class="empty"><div class="icon">📈</div>请选择事业部查看</div>
    </div>

    <!-- ── AI analysis modals ─────────────────────────────────────────────────── -->
    <AiAnalysisModal
      :visible="trendAiVisible"
      :loading="trendAiLoading"
      :text="trendAiText"
      :error="trendAiErr"
      title="AI 走势分析"
      :subtitle="trendScopeLabel"
      @close="trendAiVisible = false"
      @reanalyze="analyzeTrend"
    />
    <AiAnalysisModal
      :visible="wfAiVisible"
      :loading="wfAiLoading"
      :text="wfAiText"
      :error="wfAiErr"
      title="AI 因素分析"
      :subtitle="wfScopeLabel"
      @close="wfAiVisible = false"
      @reanalyze="analyzeWaterfall"
    />
  </div>
</template>

<style scoped>
.l1-chip {
  padding: 4px 12px; border-radius: 14px; font-size: 12px; cursor: pointer;
  border: 1.5px solid var(--border); background: rgba(255,253,250,.7); color: var(--muted);
  transition: all .16s;
}
.l1-chip:hover { border-color: var(--primary); color: var(--primary); }
.l1-chip.on { border-color: var(--primary); background: rgba(201,99,66,.1); color: var(--primary); font-weight: 600; }

.driver-dot { color: var(--primary); font-size: 9px; margin-left: 5px; vertical-align: middle; }
</style>
