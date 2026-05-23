<script setup>
import { ref, onMounted } from 'vue'
import api from '../api/index.js'

const today = new Date()
const year = ref(today.getFullYear())
const month = ref(today.getMonth() + 1)
const data = ref(null)
const loading = ref(false)

function fmt(n) {
  const v = parseFloat(n || 0)
  if (v >= 100000000) return (v / 100000000).toFixed(2) + ' 亿'
  if (v >= 10000) return (v / 10000).toFixed(2) + ' 万'
  return v.toFixed(2) + ' 元'
}

async function load() {
  loading.value = true
  try {
    const res = await api.get('/stats', { params: { year: year.value, month: month.value } })
    data.value = res.data
  } finally {
    loading.value = false
  }
}

onMounted(load)

const months = Array.from({ length: 12 }, (_, i) => i + 1)
const years = Array.from({ length: 5 }, (_, i) => today.getFullYear() - 2 + i)
</script>

<template>
  <div>
    <div class="topbar">
      <h1>月度统计</h1>
      <div style="display:flex;gap:8px;align-items:center">
        <select v-model="year" style="width:90px" @change="load">
          <option v-for="y in years" :key="y" :value="y">{{ y }} 年</option>
        </select>
        <select v-model="month" style="width:80px" @change="load">
          <option v-for="m in months" :key="m" :value="m">{{ m }} 月</option>
        </select>
        <button class="btn btn-ghost btn-sm" @click="load">查询</button>
      </div>
    </div>

    <div v-if="loading" class="empty"><div class="icon">⏳</div>加载中…</div>

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
        <div v-if="!data.by_dept.length" class="empty">
          <div class="icon">📭</div>本月暂无数据
        </div>
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
