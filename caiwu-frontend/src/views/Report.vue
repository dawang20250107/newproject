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

const years = Array.from({ length: 5 }, (_, i) => yearCST() - 2 + i)
const months = Array.from({ length: 12 }, (_, i) => i + 1)

const accessibleBus = computed(() => {
  if (auth.isAdmin) return BUSINESS_UNITS
  return (auth.user?.departments || []).filter(d => BUSINESS_UNITS.includes(d))
})

const maxLevel = computed(() => {
  if (!auth.canView('report_l2')) return 1
  if (!auth.canView('report_l3')) return 2
  return 3
})
const canExport = computed(() => auth.canView('export'))

// ── 5 key financial KPIs ─────────────────────────────────────────────────────
const KPI_DEFS = [
  { key: '主营业务收入', color: '#2e7d32' },
  { key: '主营业务成本', color: '#c62828' },
  { key: '运营毛利',    color: '#1565c0', calc: true },
  { key: '经营毛利',    color: '#6a1b9a', calc: true },
  { key: '经营净利',    color: '#e65100', calc: true },
]
const kpis = computed(() => {
  if (!data.value?.rows) return []
  const map = {}
  for (const row of data.value.rows) map[row.l1_name] = row.amount
  return KPI_DEFS.map(d => ({ ...d, amount: map[d.key] ?? null }))
    .filter(d => d.amount !== null)
})

function fmtKpi(v) {
  if (v === null || v === undefined) return '—'
  const abs = Math.abs(v)
  if (abs >= 100000000) return (v / 100000000).toFixed(2) + ' 亿'
  if (abs >= 10000) return (v / 10000).toFixed(2) + ' 万'
  return v.toFixed(2)
}

async function load() {
  loading.value = true
  loadErr.value = ''
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
      <div style="display:flex;flex-direction:column;align-items:flex-end;gap:10px">
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
          <select v-model="year" style="width:90px" @change="load">
            <option v-for="y in years" :key="y" :value="y">{{ y }} 年</option>
          </select>
          <select v-model="month" style="width:76px" @change="load">
            <option v-for="m in months" :key="m" :value="m">{{ m }} 月</option>
          </select>
          <LevelToggle v-model="level" :max-level="maxLevel" @update:model-value="load" />
          <button v-if="canExport" class="btn btn-ghost btn-sm" :disabled="exporting" @click="exportReport">
            {{ exporting ? '导出中…' : '导出 Excel' }}
          </button>
        </div>

        <!-- BU filter -->
        <div v-if="accessibleBus.length > 1" style="display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end">
          <button
            :class="['dept-chip', !selectedBu ? 'on' : '']"
            @click="selectedBu = ''; load()"
          >全部</button>
          <button
            v-for="bu in accessibleBus" :key="bu"
            :class="['dept-chip', selectedBu === bu ? 'on' : '']"
            @click="selectedBu = bu; load()"
          >{{ bu }}</button>
        </div>
      </div>
    </div>

    <div v-if="loading" class="empty"><div class="icon">⏳</div>加载中…</div>
    <div v-else-if="loadErr" class="empty" style="color:var(--danger)"><div class="icon">⚠️</div>{{ loadErr }}</div>
    <template v-else-if="data">
      <!-- 关键财务指标 KPIs -->
      <div v-if="kpis.length" class="kpi-grid kpi-5">
        <div
          v-for="kpi in kpis" :key="kpi.key"
          class="kpi-card"
          :class="{ 'kpi-calc': kpi.calc }"
        >
          <div class="label">{{ kpi.key }}</div>
          <div
            class="value"
            :style="`color:${kpi.amount < 0 ? 'var(--danger)' : kpi.color}`"
          >{{ fmtKpi(kpi.amount) }}</div>
          <div class="sub">{{ data.year }}年{{ data.month }}月{{ data.bu ? ' · ' + data.bu : '' }}</div>
        </div>
      </div>

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
.dept-chip {
  padding: 4px 11px; border-radius: 16px; font-size: 12px; cursor: pointer;
  border: 1.5px solid var(--border); background: rgba(255,253,250,.7); color: var(--text);
  transition: all .16s; white-space: nowrap;
}
.dept-chip:hover { border-color: var(--primary); color: var(--primary); }
.dept-chip.on { border-color: var(--primary); background: rgba(201,99,66,.1); color: var(--primary); font-weight: 600; }

.kpi-5 { grid-template-columns: repeat(5, 1fr) !important; }
@media (max-width: 900px) { .kpi-5 { grid-template-columns: repeat(3, 1fr) !important; } }
@media (max-width: 560px) { .kpi-5 { grid-template-columns: repeat(2, 1fr) !important; } }
.kpi-calc { border-left: 3px solid rgba(201,99,66,.3); }
</style>
