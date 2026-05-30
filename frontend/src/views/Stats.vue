<script setup>
import { ref, onMounted, computed } from 'vue'
import api from '../api/index.js'
import { useAuthStore } from '../stores/auth.js'
import { DEPARTMENTS as ALL_DEPTS_LIST, yearCST, monthCST } from '../constants.js'
import { fmtCompact } from '../utils/format.js'
import EmptyState from '../components/EmptyState.vue'

const auth = useAuthStore()
const year = ref(yearCST())
const month = ref(monthCST())
const data = ref(null)
const loading = ref(false)
const loadErr = ref('')

const availableDepts = computed(() => {
  if (auth.isAdmin) return ALL_DEPTS_LIST
  return (auth.user?.departments || []).filter(d => ALL_DEPTS_LIST.includes(d))
})

const selectedDepts = ref([])

function toggleDept(d) {
  const i = selectedDepts.value.indexOf(d)
  if (i === -1) selectedDepts.value.push(d)
  else selectedDepts.value.splice(i, 1)
  load()
}

// 亿/万/元 三级单位，单位前带空格；空值显示 0.00 元（保持原表现）
const fmt = (n) => fmtCompact(n, { space: true, yuan: true, dash: '0.00 元' })

async function load() {
  loading.value = true
  loadErr.value = ''
  try {
    const params = { year: year.value, month: month.value }
    if (selectedDepts.value.length) params.depts = selectedDepts.value.join(',')
    const res = await api.get('/stats', { params })
    data.value = res.data
  } catch (e) {
    loadErr.value = e?.error || '加载失败，请刷新重试'
  } finally {
    loading.value = false
  }
}

onMounted(load)

const months = Array.from({ length: 12 }, (_, i) => i + 1)
const years = Array.from({ length: 5 }, (_, i) => yearCST() - 2 + i)
</script>

<template>
  <div>
    <div class="topbar" style="align-items:flex-start">
      <h1>月度统计</h1>
      <div style="display:flex;flex-direction:column;align-items:flex-end;gap:10px">
        <div style="display:flex;gap:8px;align-items:center">
          <select v-model="year" style="width:90px" @change="load">
            <option v-for="y in years" :key="y" :value="y">{{ y }} 年</option>
          </select>
          <select v-model="month" style="width:80px" @change="load">
            <option v-for="m in months" :key="m" :value="m">{{ m }} 月</option>
          </select>
          <button class="btn btn-ghost btn-sm" @click="load">查询</button>
        </div>
        <div v-if="availableDepts.length > 1" class="dept-filter">
          <span class="dept-filter-label">部门</span>
          <button
            v-for="d in availableDepts" :key="d"
            :class="['dept-chip', selectedDepts.includes(d) ? 'on' : '']"
            @click="toggleDept(d)"
          >{{ d }}</button>
          <button v-if="selectedDepts.length" class="dept-chip-clear" @click="selectedDepts = []; load()">清空</button>
        </div>
      </div>
    </div>

    <EmptyState v-if="loading" loading />
    <EmptyState v-else-if="loadErr" :error="loadErr" />

    <template v-else-if="data">
      <!-- KPI -->
      <div class="kpi-grid">
        <div class="kpi-card">
          <div class="label">计划总金额</div>
          <div class="value">{{ fmt(data.total_amount) }}</div>
          <div class="sub">共 {{ data.total_records }} 笔</div>
        </div>
        <div class="kpi-card">
          <div class="label">已付金额</div>
          <div class="value" style="color:#2e7d32">{{ fmt(data.total_paid) }}</div>
          <div class="sub">完成率 {{ data.completion_rate }}%</div>
        </div>
        <div class="kpi-card">
          <div class="label">剩余未付</div>
          <div class="value" :style="parseFloat(data.total_remaining)>0?'color:#c62828':''">{{ fmt(data.total_remaining) }}</div>
        </div>
        <div class="kpi-card">
          <div class="label">付款状态分布</div>
          <div style="font-size:13px;margin-top:8px;display:flex;flex-direction:column;gap:4px">
            <span>✅ 已付清 {{ data.by_status.settled }} 笔</span>
            <span>⚡ 部分付款 {{ data.by_status.partial }} 笔</span>
            <span>⏳ 待付款 {{ data.by_status.pending }} 笔</span>
          </div>
        </div>
      </div>

      <!-- completion rate bar -->
      <div class="card" style="margin-bottom:16px">
        <div class="section-title">付款完成率</div>
        <div style="background:var(--bg2);border-radius:8px;height:20px;overflow:hidden">
          <div :style="`width:${data.completion_rate}%;background:var(--grad);height:100%;transition:width .6s;border-radius:8px`"></div>
        </div>
        <div style="text-align:right;font-size:13px;color:var(--muted);margin-top:6px">{{ data.completion_rate }}%</div>
      </div>

      <!-- by dept -->
      <div class="card">
        <div class="section-title">各部门明细</div>
        <EmptyState v-if="!data.by_dept.length" empty text="本月暂无数据" />
        <div v-else class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>部门</th>
                <th>笔数</th>
                <th>计划总额</th>
                <th>已付金额</th>
                <th>剩余金额</th>
                <th>完成率</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="d in data.by_dept" :key="d.dept">
                <td>{{ d.dept }}</td>
                <td>{{ d.count }}</td>
                <td class="amt">{{ fmt(d.total) }}</td>
                <td class="amt amt-green">{{ fmt(d.paid) }}</td>
                <td class="amt" :class="parseFloat(d.remaining)>0?'amt-red':''">{{ fmt(d.remaining) }}</td>
                <td>
                  <div style="display:flex;align-items:center;gap:8px">
                    <div style="flex:1;background:var(--bg2);border-radius:4px;height:8px;overflow:hidden;min-width:80px">
                      <div :style="`width:${d.completion_rate}%;background:var(--grad);height:100%`"></div>
                    </div>
                    <span style="font-size:12px;color:var(--muted);min-width:38px">{{ d.completion_rate }}%</span>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.dept-filter {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  justify-content: flex-end;
}
.dept-filter-label {
  font-size: 12px;
  color: var(--muted);
  white-space: nowrap;
  margin-right: 2px;
}
.dept-chip {
  padding: 4px 11px;
  border-radius: 16px;
  font-size: 12px;
  border: 1.5px solid var(--border);
  background: rgba(255, 253, 250, 0.7);
  color: var(--text);
  cursor: pointer;
  transition: all 0.16s;
  white-space: nowrap;
}
.dept-chip:hover { border-color: var(--primary); color: var(--primary); }
.dept-chip.on {
  border-color: var(--primary);
  background: rgba(201, 99, 66, 0.1);
  color: var(--primary);
  font-weight: 600;
}
.dept-chip-clear {
  padding: 4px 10px;
  border-radius: 16px;
  font-size: 11px;
  border: 1px dashed rgba(155,128,112,0.4);
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  transition: all 0.16s;
}
.dept-chip-clear:hover { border-color: #c62828; color: #c62828; }
</style>
