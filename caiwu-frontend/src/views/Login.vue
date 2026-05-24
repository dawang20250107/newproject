<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth.js'
import { BUSINESS_UNITS, JOB_OPTIONS } from '../constants.js'
import api from '../api/index.js'

const router = useRouter()
const auth = useAuthStore()

const mode = ref('login')  // 'login' | 'register' | 'pending'
const phone = ref('')
const password = ref('')
const name = ref('')
const jobTitle = ref('')
const departments = ref([])
const loading = ref(false)
const error = ref('')
const pendingPhone = ref('')

let pollTimer = null
let approvalTimer = null

async function doLogin() {
  error.value = ''
  if (!phone.value || !password.value) { error.value = '请填写手机号和密码'; return }
  loading.value = true
  try {
    const res = await api.post('/login', { phone: phone.value, password: password.value })
    if (res.data?.pending) {
      pendingPhone.value = phone.value
      mode.value = 'pending'
      startPolling()
      return
    }
    auth.setAuth(res.data.token, res.data.user, res.data.permissions)
    router.push('/')
  } catch (e) {
    error.value = e?.error || '登录失败，请重试'
  } finally {
    loading.value = false
  }
}

async function doRegister() {
  error.value = ''
  if (!phone.value || !password.value || !name.value) { error.value = '请填写手机号、密码和姓名'; return }
  if (password.value.length < 6) { error.value = '密码至少6位'; return }
  loading.value = true
  try {
    const body = { phone: phone.value, password: password.value, name: name.value, job_title: jobTitle.value, departments: departments.value }
    const res = await api.post('/register', body)
    if (res.data?.token) {
      auth.setAuth(res.data.token, res.data.user, res.data.permissions)
      router.push('/')
      return
    }
    pendingPhone.value = phone.value
    mode.value = 'pending'
    startPolling()
  } catch (e) {
    error.value = e?.error || '注册失败，请重试'
  } finally {
    loading.value = false
  }
}

function startPolling() {
  pollTimer = setInterval(async () => {
    try {
      const res = await api.post('/login', { phone: pendingPhone.value, password: password.value })
      if (res.data?.token) {
        stopPolling()
        auth.setAuth(res.data.token, res.data.user, res.data.permissions)
        approvalTimer = setTimeout(() => router.push('/'), 1800)
        mode.value = 'approved'
      }
    } catch {}
  }, 5000)
}

function stopPolling() {
  clearInterval(pollTimer); pollTimer = null
}

function toggleDept(d) {
  const i = departments.value.indexOf(d)
  if (i === -1) departments.value.push(d)
  else departments.value.splice(i, 1)
}

onUnmounted(() => {
  stopPolling()
  if (approvalTimer) { clearTimeout(approvalTimer); approvalTimer = null }
})

if (auth.isLoggedIn) router.push('/')
</script>

<template>
  <div class="login-page">
    <div class="login-card">
      <div class="brand">
        <div class="brand-icon">📑</div>
        <div class="brand-name">KXT 财务分析系统</div>
      </div>

      <!-- PENDING / APPROVED -->
      <template v-if="mode === 'pending' || mode === 'approved'">
        <div class="pending-box">
          <div class="pending-icon">{{ mode === 'approved' ? '✅' : '⏳' }}</div>
          <div class="pending-title">{{ mode === 'approved' ? '审批通过！' : '等待管理员审批' }}</div>
          <div class="pending-sub">
            {{ mode === 'approved' ? '正在跳转到系统…' : '注册申请已提交，管理员审批后您将自动登入' }}
          </div>
          <div v-if="mode === 'pending'" class="pending-dots">
            <span v-for="n in 3" :key="n" :style="`animation-delay:${(n-1)*.2}s`"></span>
          </div>
          <button v-if="mode === 'pending'" class="btn btn-ghost btn-sm" style="margin-top:20px" @click="stopPolling(); mode='login'">返回登录</button>
        </div>
      </template>

      <!-- LOGIN -->
      <template v-else-if="mode === 'login'">
        <h2>登录</h2>
        <div v-if="error" class="error-banner">{{ error }}</div>
        <div class="form-row">
          <label>手机号</label>
          <input v-model="phone" type="tel" placeholder="请输入手机号" @keyup.enter="doLogin" />
        </div>
        <div class="form-row">
          <label>密码</label>
          <input v-model="password" type="password" placeholder="请输入密码" @keyup.enter="doLogin" />
        </div>
        <button class="btn btn-primary" style="width:100%;margin-top:8px" :disabled="loading" @click="doLogin">
          {{ loading ? '登录中…' : '登录' }}
        </button>
        <div class="switch-mode">
          还没有账号？<a @click="mode = 'register'; error = ''">立即注册</a>
        </div>
      </template>

      <!-- REGISTER -->
      <template v-else-if="mode === 'register'">
        <h2>注册账号</h2>
        <div v-if="error" class="error-banner">{{ error }}</div>
        <div class="form-grid form-grid-2">
          <div class="form-row">
            <label>手机号</label>
            <input v-model="phone" type="tel" placeholder="请输入手机号" />
          </div>
          <div class="form-row">
            <label>姓名</label>
            <input v-model="name" placeholder="请输入姓名" />
          </div>
        </div>
        <div class="form-row">
          <label>密码（至少6位）</label>
          <input v-model="password" type="password" placeholder="设置登录密码" />
        </div>
        <div class="form-row">
          <label>职务</label>
          <select v-model="jobTitle">
            <option value="">不指定</option>
            <option v-for="j in JOB_OPTIONS" :key="j.v" :value="j.v">{{ j.label }}</option>
          </select>
        </div>
        <div class="form-row">
          <label>负责事业部（可多选）</label>
          <div class="dept-chips">
            <button
              v-for="d in BUSINESS_UNITS" :key="d"
              :class="['dept-chip', departments.includes(d) ? 'on' : '']"
              @click="toggleDept(d)"
            >{{ d }}</button>
          </div>
        </div>
        <button class="btn btn-primary" style="width:100%;margin-top:8px" :disabled="loading" @click="doRegister">
          {{ loading ? '提交中…' : '提交注册申请' }}
        </button>
        <div class="switch-mode">
          已有账号？<a @click="mode = 'login'; error = ''">返回登录</a>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  min-height: 100vh; display: flex; align-items: center; justify-content: center;
  background: var(--bg);
  background-image: radial-gradient(ellipse at 20% 50%, rgba(201,99,66,.08) 0%, transparent 60%),
                    radial-gradient(ellipse at 80% 20%, rgba(232,133,90,.06) 0%, transparent 60%);
}
.login-card {
  width: min(440px, 94vw); background: var(--card);
  border: 1px solid var(--border); border-radius: 24px;
  padding: 40px 36px; box-shadow: 0 24px 64px rgba(100,60,30,.14);
}
.brand { text-align: center; margin-bottom: 28px; }
.brand-icon { font-size: 42px; margin-bottom: 8px; }
.brand-name { font-size: 18px; font-weight: 800; color: var(--text); letter-spacing: -.02em; }
h2 { font-size: 18px; font-weight: 700; margin: 0 0 18px; color: var(--text); }
.switch-mode { text-align: center; margin-top: 16px; font-size: 13px; color: var(--muted); }
.switch-mode a { color: var(--primary); cursor: pointer; font-weight: 600; }
.switch-mode a:hover { text-decoration: underline; }

.dept-chips { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 4px; }
.dept-chip {
  padding: 5px 13px; border-radius: 16px; font-size: 12px; cursor: pointer;
  border: 1.5px solid var(--border); background: rgba(255,253,250,.7); color: var(--text);
  transition: all .16s;
}
.dept-chip:hover { border-color: var(--primary); color: var(--primary); }
.dept-chip.on { border-color: var(--primary); background: rgba(201,99,66,.1); color: var(--primary); font-weight: 600; }

.pending-box { text-align: center; padding: 16px 0 8px; }
.pending-icon { font-size: 52px; margin-bottom: 14px; }
.pending-title { font-size: 18px; font-weight: 700; color: var(--text); margin-bottom: 8px; }
.pending-sub { font-size: 13px; color: var(--muted); line-height: 1.6; }
.pending-dots { display: flex; gap: 6px; justify-content: center; margin-top: 16px; }
.pending-dots span {
  width: 7px; height: 7px; background: var(--primary); border-radius: 50%;
  animation: dotPulse 1.2s ease-in-out infinite;
}
@keyframes dotPulse { 0%,80%,100% { opacity:.2; transform:scale(.8); } 40% { opacity:1; transform:scale(1); } }
</style>
