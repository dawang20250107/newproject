<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useCaiwuAuth } from '../../composables/useCaiwuAuth.js'
import { BUSINESS_UNITS, yearCST, lastMonthCST } from '../../constants.js'
import TrendLineChart from '../../components/caiwu/charts/TrendLineChart.vue'
import WaterfallChart from '../../components/caiwu/charts/WaterfallChart.vue'
import api from '../../api/caiwu.js'
import { fmtCompact } from '../../utils/format.js'
import EmptyState from '../../components/EmptyState.vue'

defineProps({ embedded: { type: Boolean, default: false } })

const auth = useCaiwuAuth()

// ── Global BU + year filter ─────────────────────────────
const globalBu = ref('')
// 默认上月所在年度（1 月时即去年），趋势图展示含最新完整数据的年份
const trendYear = ref(lastMonthCST().year)

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

async function loadTrend() {
  if (!globalBu.value) return
  trendLoading.value = true
  trendErr.value = ''
  try {
    const res = await api.get('/charts/trend', { params: { bu: globalBu.value, year: trendYear.value } })
    trendData.value = res.data
    // 默认选中：主营业务收入 / 主营业务成本 / 经营毛利；缺失则回退取前 3 项
    if (selectedL1Ids.value.length === 0 && res.data.l1_categories?.length) {
      const cats = res.data.l1_categories
      const want = ['主营业务收入', '主营业务成本', '经营毛利']
      const picked = want
        .map(n => cats.find(c => c.name === n)?.id)
        .filter(id => id != null)
      selectedL1Ids.value = picked.length ? picked : cats.slice(0, 3).map(c => c.id)
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

// ── Waterfall chart state ───────────────────────────────
// 默认终点=上月、起点=上上月，开箱即看最近一次环比因素分析
const _wfTo = lastMonthCST()
const _wfFrom = _wfTo.month === 1 ? { year: _wfTo.year - 1, month: 12 } : { year: _wfTo.year, month: _wfTo.month - 1 }
const wfYear = ref(_wfTo.year)
const wfMonth = ref(_wfTo.month)
const wfCmpYear = ref(_wfFrom.year)
const wfCmpMonth = ref(_wfFrom.month)
const wfData = ref(null)
const wfLoading = ref(false)
const wfErr = ref('')

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

const changedFactors = computed(() => (wfData.value?.factors || []).filter(f => f.delta !== 0))

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
      <h1 v-if="!embedded">报表分析</h1>
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
      <div style="margin-bottom:16px">
        <div class="section-title" style="margin:0">收入 / 利润走势（折线图）</div>
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

      <EmptyState v-if="trendLoading && !trendData" loading />
      <EmptyState v-else-if="!trendLoading && trendErr" :error="trendErr" />
      <TrendLineChart
        v-else-if="trendData"
        :class="{ 'data-reloading': trendLoading }"
        :months="trendData.months"
        :l1-categories="trendData.l1_categories"
        :selected-l1-ids="selectedL1Ids"
        height="340px"
      />
      <EmptyState v-else icon="📊" text="请选择事业部查看" />
    </div>

    <!-- ── Waterfall Chart ───────────────────────────────── -->
    <div v-if="canWaterfall" class="card">
      <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;margin-bottom:16px">
        <div class="section-title" style="margin:0">因素分析（瀑布图）</div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
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

      <EmptyState v-if="wfLoading && !wfData" loading />
      <EmptyState v-else-if="!wfLoading && wfErr" :error="wfErr" />
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
      <EmptyState v-else icon="📈" text="请选择事业部查看" />
    </div>

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
