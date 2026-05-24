<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useAuthStore } from '../stores/auth.js'
import { BUSINESS_UNITS, yearCST, monthCST } from '../constants.js'
import TrendLineChart from '../components/charts/TrendLineChart.vue'
import WaterfallChart from '../components/charts/WaterfallChart.vue'
import api from '../api/index.js'

const auth = useAuthStore()

// ── Trend chart state ───────────────────────────────────
const trendBu = ref('')
const trendYear = ref(yearCST())
const trendData = ref(null)
const trendLoading = ref(false)
const trendErr = ref('')
const selectedL1Ids = ref([])

const years = Array.from({ length: 5 }, (_, i) => yearCST() - 2 + i)

const accessibleBus = computed(() => {
  if (auth.isAdmin || ['general_manager', 'viewer'].includes(auth.role)) return BUSINESS_UNITS
  return (auth.user?.departments || []).filter(d => BUSINESS_UNITS.includes(d))
})

async function loadTrend() {
  if (!trendBu.value) return
  trendLoading.value = true
  trendErr.value = ''
  try {
    const res = await api.get('/charts/trend', { params: { bu: trendBu.value, year: trendYear.value } })
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

// ── Waterfall chart state ───────────────────────────────
const wfBu = ref('')
const wfYear = ref(yearCST())
const wfMonth = ref(monthCST())
const wfCmpYear = ref(yearCST())
const wfCmpMonth = ref(monthCST() === 1 ? 12 : monthCST() - 1)
const wfData = ref(null)
const wfLoading = ref(false)
const wfErr = ref('')

const months = Array.from({ length: 12 }, (_, i) => i + 1)

async function loadWaterfall() {
  if (!wfBu.value) return
  wfLoading.value = true
  wfErr.value = ''
  try {
    const res = await api.get('/charts/waterfall', {
      params: { bu: wfBu.value, year: wfYear.value, month: wfMonth.value, compare_year: wfCmpYear.value, compare_month: wfCmpMonth.value },
    })
    wfData.value = res.data
  } catch (e) {
    wfErr.value = e?.error || '加载失败'
  } finally {
    wfLoading.value = false
  }
}

function fmtAmt(v) {
  if (Math.abs(v) >= 100000000) return (v / 100000000).toFixed(2) + ' 亿'
  if (Math.abs(v) >= 10000) return (v / 10000).toFixed(2) + ' 万'
  return v.toFixed(2)
}

onMounted(() => {
  if (accessibleBus.value.length) {
    trendBu.value = accessibleBus.value[0]
    wfBu.value = accessibleBus.value[0]
    loadTrend()
    loadWaterfall()
  }
})
</script>

<template>
  <div>
    <div class="topbar"><h1>图表分析</h1></div>

    <!-- ── Trend Line Chart ──────────────────────────────── -->
    <div class="card">
      <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;margin-bottom:16px">
        <div class="section-title" style="margin:0">收入 / 利润走势（折线图）</div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
          <select v-model="trendBu" style="width:130px" @change="loadTrend">
            <option v-for="bu in accessibleBus" :key="bu" :value="bu">{{ bu }}</option>
          </select>
          <select v-model="trendYear" style="width:86px" @change="loadTrend">
            <option v-for="y in years" :key="y" :value="y">{{ y }} 年</option>
          </select>
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

      <div v-if="trendLoading" class="empty"><div class="icon">⏳</div>加载中…</div>
      <div v-else-if="trendErr" class="empty" style="color:var(--danger)">{{ trendErr }}</div>
      <TrendLineChart
        v-else-if="trendData"
        :months="trendData.months"
        :l1-categories="trendData.l1_categories"
        :selected-l1-ids="selectedL1Ids"
        height="340px"
      />
      <div v-else class="empty"><div class="icon">📊</div>请选择事业部查看</div>
    </div>

    <!-- ── Waterfall Chart ───────────────────────────────── -->
    <div class="card">
      <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;margin-bottom:16px">
        <div class="section-title" style="margin:0">因素分析（瀑布图）</div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
          <select v-model="wfBu" style="width:130px" @change="loadWaterfall">
            <option v-for="bu in accessibleBus" :key="bu" :value="bu">{{ bu }}</option>
          </select>
          <span style="font-size:12px;color:var(--muted)">对比</span>
          <select v-model="wfCmpYear" style="width:82px" @change="loadWaterfall">
            <option v-for="y in years" :key="y" :value="y">{{ y }}</option>
          </select>
          <select v-model="wfCmpMonth" style="width:70px" @change="loadWaterfall">
            <option v-for="m in months" :key="m" :value="m">{{ m }}月</option>
          </select>
          <span style="font-size:12px;color:var(--muted)">→</span>
          <select v-model="wfYear" style="width:82px" @change="loadWaterfall">
            <option v-for="y in years" :key="y" :value="y">{{ y }}</option>
          </select>
          <select v-model="wfMonth" style="width:70px" @change="loadWaterfall">
            <option v-for="m in months" :key="m" :value="m">{{ m }}月</option>
          </select>
        </div>
      </div>

      <div v-if="wfData && !wfData.factors?.length" class="empty" style="padding:16px">
        <div class="icon">💡</div>
        尚未配置「利润驱动因素」科目。请在「系统设置 → 一级科目」中勾选相关科目的「利润驱动因素」标记。
      </div>

      <div v-if="wfLoading" class="empty"><div class="icon">⏳</div>加载中…</div>
      <div v-else-if="wfErr" class="empty" style="color:var(--danger)">{{ wfErr }}</div>
      <template v-else-if="wfData?.waterfall?.length">
        <WaterfallChart :waterfall="wfData.waterfall" height="380px" />
        <!-- Factor detail table -->
        <div v-if="wfData.factors?.length" style="margin-top:16px">
          <div class="section-title">因素明细</div>
          <div class="table-wrap">
            <table>
              <thead><tr><th>驱动因素（一级科目）</th><th class="amt">对比期</th><th class="amt">当期</th><th class="amt">变动</th></tr></thead>
              <tbody>
                <tr v-for="f in wfData.factors" :key="f.l1_id">
                  <td>{{ f.name }}</td>
                  <td class="amt">{{ fmtAmt(f.base) }}</td>
                  <td class="amt">{{ fmtAmt(f.current) }}</td>
                  <td class="amt" :class="f.delta >= 0 ? 'amt-green' : 'amt-red'">
                    {{ f.delta >= 0 ? '+' : '' }}{{ fmtAmt(f.delta) }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </template>
      <div v-else-if="!wfLoading" class="empty"><div class="icon">📈</div>请选择事业部查看</div>
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
</style>
