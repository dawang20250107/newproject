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
  if (auth.isAdmin || ['general_manager', 'viewer'].includes(auth.role)) return BUSINESS_UNITS
  return (auth.user?.departments || []).filter(d => BUSINESS_UNITS.includes(d))
})

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
          <LevelToggle v-model="level" @update:model-value="load" />
          <button class="btn btn-ghost btn-sm" :disabled="exporting" @click="exportReport">
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
      <!-- KPIs -->
      <div class="kpi-grid">
        <div class="kpi-card">
          <div class="label">本期科目数</div>
          <div class="value">{{ data.rows?.length || 0 }}</div>
          <div class="sub">一级科目合计</div>
        </div>
        <div class="kpi-card">
          <div class="label">合计金额</div>
          <div class="value" :style="data.total < 0 ? 'color:var(--danger)' : 'color:var(--success)'">
            {{ Math.abs(data.total) >= 10000 ? (data.total / 10000).toFixed(2) + ' 万' : (data.total?.toFixed(2) || '0') }}
          </div>
          <div class="sub">{{ data.year }}年{{ data.month }}月{{ data.bu ? ' · ' + data.bu : ' · 全部事业部' }}</div>
        </div>
      </div>

      <div class="card">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px">
          <div class="section-title" style="margin:0">
            {{ data.bu || '全部事业部' }} · {{ data.year }}年{{ data.month }}月
            <span class="badge badge-primary" style="margin-left:8px">{{ ['一级', '二级', '三级'][level-1] }}明细</span>
          </div>
        </div>
        <ReportTable :rows="data.rows || []" :level="level" :total="data.total || 0" />
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
</style>
