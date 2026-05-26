<script setup>
import { ref, onMounted, computed } from 'vue'
import api from '../api/index.js'
import { useAuthStore } from '../stores/auth.js'
import StatusBadge from '../components/StatusBadge.vue'

const auth = useAuthStore()
const data = ref(null)
const loading = ref(true)
const loadErr = ref('')
const welcomeName = ref('')

const showAmount = computed(() => auth.canView('total_amount'))
const showPaid = computed(() => auth.canView('pay1') || auth.canView('pay2') || auth.canView('pay3'))

function fmt(n) {
  if (n === null || n === undefined) return '—'
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

onMounted(() => {
  load()
  const name = sessionStorage.getItem('pk_welcome')
  if (name && name !== '1') {
    welcomeName.value = name
    sessionStorage.removeItem('pk_welcome')
    setTimeout(() => { welcomeName.value = '' }, 3500)
  } else if (name === '1') {
    sessionStorage.removeItem('pk_welcome')
  }
})

const today = new Date().toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric', weekday: 'long' })
</script>

<template>
  <div>
    <!-- welcome toast shown once after approval auto-login -->
    <Transition name="welcome-fade">
      <div v-if="welcomeName" class="welcome-toast">
        🎉 欢迎加入，{{ welcomeName }}！账号已通过审批，正式进入系统。
      </div>
    </Transition>

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
          <div v-if="showAmount" class="sub">共 {{ fmt(data.today_amount) }}</div>
        </div>
        <div class="kpi-card">
          <div class="label">待付款记录</div>
          <div class="value" style="color:#c62828">{{ data.pending_count }}</div>
          <div v-if="showAmount" class="sub">{{ fmt(data.pending_amount) }}</div>
        </div>
        <div class="kpi-card">
          <div class="label">部分付款中</div>
          <div class="value" style="color:#f57f17">{{ data.partial_count }}</div>
          <div class="sub">待完成</div>
        </div>
        <div :class="['kpi-card', data.overdue_count > 0 ? 'overdue-kpi-card' : '']">
          <div class="label">已逾期未付</div>
          <div :class="['value', data.overdue_count > 0 ? 'kpi-value-pulse' : '']" style="color:#c62828">
            {{ data.overdue_count }}
          </div>
          <div v-if="showAmount" class="sub">{{ fmt(data.overdue_amount) }}</div>
        </div>
      </div>

      <!-- overdue alert banner -->
      <div v-if="data.overdue_count > 0" class="overdue-alert">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/>
          <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
        </svg>
        <span>
          当前有 <strong>{{ data.overdue_count }}</strong> 笔排款已逾期未付
          <template v-if="showAmount">，合计 <strong>{{ fmt(data.overdue_amount) }}</strong></template>
          ，请及时跟进处理。
        </span>
      </div>

      <div class="card">
        <div class="section-title">今日计划付款 ({{ data.today_count }} 笔)</div>
        <div v-if="!data.today_payments.length" class="empty">
          <div class="icon">🎉</div>今日暂无计划付款
        </div>
        <div v-else class="table-wrap">
          <table class="today-table">
            <thead>
              <tr>
                <th v-if="auth.canView('department')">部门</th>
                <th v-if="auth.canView('project_desc')">付款事项</th>
                <th v-if="auth.canView('payee')">收款方</th>
                <th v-if="showAmount">计划金额</th>
                <th v-if="showPaid">已付</th>
                <th>状态</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="p in data.today_payments" :key="p.id">
                <td v-if="auth.canView('department')">{{ p.department }}</td>
                <td v-if="auth.canView('project_desc')" class="desc">{{ p.project_desc }}</td>
                <td v-if="auth.canView('payee')">{{ p.payee }}</td>
                <td v-if="showAmount" class="amt">{{ fmt(p.total_amount) }}</td>
                <td v-if="showPaid" class="amt">{{ fmt(p.total_paid) }}</td>
                <td><StatusBadge :status="p.status" /></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.welcome-toast {
  position: fixed;
  top: 24px;
  left: 50%;
  transform: translateX(-50%);
  background: linear-gradient(135deg, #c96342, #e8855a 55%, #e8a84a);
  background-size: 200% 100%;
  color: #fff;
  padding: 16px 34px;
  border-radius: 32px;
  font-size: 16px;
  font-weight: 700;
  letter-spacing: 0.02em;
  box-shadow: 0 10px 34px rgba(201,99,66,0.5);
  z-index: 9999;
  white-space: nowrap;
  overflow: hidden;
  animation: toastShine 2.6s ease-in-out infinite, toastBob 2.8s ease-in-out infinite;
}
.welcome-toast::after {
  content: '';
  position: absolute; top: 0; bottom: 0; left: -60%;
  width: 50%;
  background: linear-gradient(100deg, transparent, rgba(255,255,255,0.45), transparent);
  transform: skewX(-18deg);
  animation: toastSweep 2.8s ease-in-out 0.5s infinite;
}
@keyframes toastShine { 0%,100% { background-position: 0% 0; } 50% { background-position: 100% 0; } }
@keyframes toastBob { 0%,100% { transform: translateX(-50%) translateY(0); } 50% { transform: translateX(-50%) translateY(-3px); } }
@keyframes toastSweep { 0% { left: -60%; } 55%,100% { left: 130%; } }
.welcome-fade-enter-active { transition: all 0.55s cubic-bezier(0.22,1,0.36,1); }
.welcome-fade-leave-active { transition: all 0.6s ease; }
.welcome-fade-enter-from  { opacity: 0; transform: translateX(-50%) translateY(-18px) scale(0.92); }
.welcome-fade-leave-to    { opacity: 0; transform: translateX(-50%) translateY(-10px) scale(0.96); }

.overdue-alert {
  display: flex; align-items: center; gap: 10px;
  background: rgba(198,40,40,0.08);
  border: 1px solid rgba(198,40,40,0.22);
  border-left: 4px solid #c62828;
  border-radius: 10px;
  padding: 11px 16px;
  margin-bottom: 16px;
  color: #b71c1c;
  font-size: 13.5px;
  animation: overdue-breathe 2.8s ease-in-out infinite;
}
.overdue-alert svg { flex-shrink: 0; color: #c62828; }
.today-table { table-layout: fixed; width: 100%; font-size: 12px; }
.today-table th, .today-table td { padding: 6px 8px; line-height: 1.25; }
.today-table .desc { max-width: 240px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
</style>
