<script setup>
import { ref, onMounted } from 'vue'
import api from '../api/index.js'
import StatusBadge from '../components/StatusBadge.vue'

const data = ref(null)
const loading = ref(true)
const loadErr = ref('')

function fmt(n) {
  const v = parseFloat(n || 0)
  return v >= 10000 ? (v / 10000).toFixed(2) + ' 万' : v.toFixed(2) + ' 元'
}

async function load() {
  loading.value = true
  loadErr.value = ''
  try {
    const res = await api.get('/dashboard')
    data.value = res.data
  } catch (e) {
    loadErr.value = e?.error || '加载失败，请刷新重试'
  } finally {
    loading.value = false
  }
}

onMounted(load)

const today = new Date().toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric', weekday: 'long' })
</script>

<template>
  <div>
    <div class="topbar">
      <div>
        <h1>今日工作台</h1>
        <div style="font-size:13px;color:var(--muted);margin-top:2px">{{ today }}</div>
      </div>
      <button class="btn btn-ghost btn-sm" @click="load">刷新</button>
    </div>

    <div v-if="loading" class="empty"><div class="icon">⏳</div>加载中…</div>
    <div v-else-if="loadErr" class="empty" style="color:#c62828"><div class="icon">⚠️</div>{{ loadErr }}</div>

    <template v-else-if="data">
      <div class="kpi-grid">
        <div class="kpi-card">
          <div class="label">今日计划付款</div>
          <div class="value">{{ data.today_count }}</div>
          <div class="sub">共 {{ fmt(data.today_amount) }}</div>
        </div>
        <div class="kpi-card">
          <div class="label">待付款记录</div>
          <div class="value" style="color:#c62828">{{ data.pending_count }}</div>
          <div class="sub">{{ fmt(data.pending_amount) }}</div>
        </div>
        <div class="kpi-card">
          <div class="label">部分付款中</div>
          <div class="value" style="color:#f57f17">{{ data.partial_count }}</div>
          <div class="sub">待完成</div>
        </div>
        <div class="kpi-card">
          <div class="label">已逾期未付</div>
          <div class="value" style="color:#c62828">{{ data.overdue_count }}</div>
          <div class="sub">{{ fmt(data.overdue_amount) }}</div>
        </div>
      </div>

      <div class="card">
        <div class="section-title">今日计划付款 ({{ data.today_count }} 笔)</div>
        <div v-if="!data.today_payments.length" class="empty">
          <div class="icon">🎉</div>今日暂无计划付款
        </div>
        <div v-else class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>部门</th>
                <th>付款事项</th>
                <th>收款方</th>
                <th>计划金额</th>
                <th>已付</th>
                <th>状态</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="p in data.today_payments" :key="p.id">
                <td>{{ p.department }}</td>
                <td style="max-width:240px;white-space:normal">{{ p.project_desc }}</td>
                <td>{{ p.payee }}</td>
                <td class="amt">{{ fmt(p.total_amount) }}</td>
                <td class="amt">{{ fmt(p.total_paid) }}</td>
                <td><StatusBadge :status="p.status" /></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>
  </div>
</template>
