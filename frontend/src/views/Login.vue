<script setup>
import { ref, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth.js'
import api from '../api/index.js'
import { DEPARTMENTS, JOB_OPTIONS } from '../constants.js'

const router = useRouter()
const auth = useAuthStore()

const mode = ref('login')
const phone = ref('')
const password = ref('')
const name = ref('')
const jobTitle = ref('')
const selectedDepts = ref([])
const error = ref('')
const loading = ref(false)
const pendingMsg = ref('')
const pendingState = ref('waiting')   // 'waiting' | 'approved' | 'rejected'
let pollTimer = null
let approvalTimer = null

const JOB_TITLES = JOB_OPTIONS

function switchMode(m) {
  mode.value = m
  error.value = ''
  pendingMsg.value = ''
  stopPolling()
}

function validateRegister() {
  const ph = phone.value.trim()
  if (!ph) return '请输入手机号'
  if (!/^\d{8,}$/.test(ph)) return '手机号格式有误（至少8位数字）'
  if (!name.value.trim()) return '请输入姓名'
  if (!password.value) return '请输入密码'
  if (password.value.length < 6) return '密码至少6位'
  if (!jobTitle.value) return '请选择职务'
  if (!selectedDepts.value.length) return '请至少选择一个所属部门'
  return ''
}

async function submit() {
  error.value = ''
  pendingMsg.value = ''
  if (mode.value === 'register') {
    const msg = validateRegister()
    if (msg) { error.value = msg; return }
  } else {
    if (!phone.value.trim() || !password.value) { error.value = '请输入手机号和密码'; return }
  }
  loading.value = true
  try {
    if (mode.value === 'login') {
      await auth.login(phone.value, password.value)
      router.push('/dashboard')
    } else {
      const result = await auth.register({
        phone: phone.value,
        password: password.value,
        name: name.value,
        job_title: jobTitle.value,
        departments: selectedDepts.value,
      })
      if (result.pending) {
        pendingMsg.value = result.message || '注册成功！请等待管理员审批'
        pendingState.value = 'waiting'
        mode.value = 'pending'
        startPolling()
      } else {
        router.push('/dashboard')
      }
    }
  } catch (e) {
    error.value = e?.error || '操作失败，请重试'
  } finally {
    loading.value = false
  }
}

// ── real-time approval polling ──
function startPolling() {
  stopPolling()
  pollTimer = setInterval(checkStatus, 3000)
}
function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}
async function checkStatus() {
  try {
    const res = await api.get('/registration-status', { params: { phone: phone.value } })
    const s = res.data.status
    if (s === 'approved') {
      stopPolling()
      pendingState.value = 'approved'
      approvalTimer = setTimeout(enterAfterApproval, 1800)
    } else if (s === 'rejected' || s === 'none') {
      stopPolling()
      pendingState.value = 'rejected'
    }
  } catch { /* keep polling */ }
}
async function enterAfterApproval() {
  try {
    await auth.login(phone.value, password.value)
    sessionStorage.setItem('pk_welcome', auth.user?.name || '1')
    router.push('/dashboard')
  } catch (e) {
    pendingState.value = 'rejected'
    error.value = e?.error || '自动登录失败，请返回手动登录'
  }
}
onUnmounted(() => {
  stopPolling()
  if (approvalTimer) { clearTimeout(approvalTimer); approvalTimer = null }
})

function toggleDept(d) {
  const idx = selectedDepts.value.indexOf(d)
  if (idx === -1) selectedDepts.value.push(d)
  else selectedDepts.value.splice(idx, 1)
}
</script>

<template>
  <div class="login-page">
    <!-- animated background specific to login -->
    <div class="login-bg">
      <div class="login-orb lo1"></div>
      <div class="login-orb lo2"></div>
      <div class="login-orb lo3"></div>
    </div>

    <div class="login-wrap">
      <!-- Branding side (desktop) -->
      <div class="login-brand">
        <div class="brand-icon-lg">
          <svg width="52" height="52" viewBox="0 0 60 60" fill="none">
            <circle cx="30" cy="30" r="28" fill="url(#lg1)" opacity="0.92"/>
            <path d="M20 30h20M30 20v20" stroke="white" stroke-width="4" stroke-linecap="round"/>
            <defs>
              <linearGradient id="lg1" x1="0" y1="0" x2="60" y2="60">
                <stop offset="0%" stop-color="#e8855a"/>
                <stop offset="100%" stop-color="#c96342"/>
              </linearGradient>
            </defs>
          </svg>
        </div>
        <h1 class="brand-title">应收应付管理系统</h1>
        <p class="brand-sub">精准 · 高效 · 安全</p>
        <div class="brand-features">
          <div class="feature">
            <span class="f-dot"></span>应收应付全流程追踪
          </div>
          <div class="feature">
            <span class="f-dot"></span>多部门协同管理
          </div>
          <div class="feature">
            <span class="f-dot"></span>逾期预警与统计
          </div>
        </div>
      </div>

      <!-- Card -->
      <div class="login-card">
        <!-- pending state (real-time) -->
        <template v-if="mode === 'pending'">
          <!-- waiting for approval -->
          <div v-if="pendingState === 'waiting'" class="pending-state">
            <div class="approve-loader">
              <div class="ring"></div>
              <div class="ring-icon">⏳</div>
            </div>
            <h3>正在等待管理员审批</h3>
            <p>{{ pendingMsg }}</p>
            <p class="pending-hint">
              <span class="live-dot"></span>实时检测中，审批通过后将自动进入系统…
            </p>
            <button class="btn btn-ghost mt" style="width:100%;justify-content:center" @click="switchMode('login')">
              返回登录
            </button>
          </div>

          <!-- approved -->
          <div v-else-if="pendingState === 'approved'" class="pending-state approved-state">
            <div class="confetti">
              <i v-for="n in 14" :key="n" :style="`--i:${n}`"></i>
            </div>
            <div class="success-check">
              <svg width="40" height="40" viewBox="0 0 52 52">
                <circle class="sc-circle" cx="26" cy="26" r="24" fill="none"/>
                <path class="sc-check" fill="none" d="M14 27l8 8 16-16"/>
              </svg>
            </div>
            <h3 class="approved-title">🎉 审批已通过！</h3>
            <p class="approved-sub">恭喜加入，正在为您进入系统…</p>
          </div>

          <!-- rejected -->
          <div v-else class="pending-state">
            <div class="pending-icon">⚠️</div>
            <h3 style="color:#c62828">申请未通过</h3>
            <p>很抱歉，您的注册申请未获通过，或账号已被停用。</p>
            <p class="pending-hint">如有疑问请联系管理员</p>
            <button class="btn btn-primary mt" style="width:100%;justify-content:center" @click="switchMode('login')">
              返回登录
            </button>
          </div>
        </template>

        <template v-else>
          <!-- mode tabs -->
          <div class="mode-tabs">
            <button :class="['mode-tab', mode === 'login' ? 'active' : '']" @click="switchMode('login')">登录</button>
            <button :class="['mode-tab', mode === 'register' ? 'active' : '']" @click="switchMode('register')">注册</button>
          </div>

          <div v-if="error" class="alert alert-err" style="margin-bottom:16px">{{ error }}</div>

          <!-- login form -->
          <template v-if="mode === 'login'">
            <div class="lf-group">
              <label>手机号</label>
              <div class="input-wrap">
                <svg class="input-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M22 16.92v3a2 2 0 01-2.18 2 19.79 19.79 0 01-8.63-3.07 19.5 19.5 0 01-6-6A19.79 19.79 0 012.12 4.18 2 2 0 014.11 2h3a2 2 0 012 1.72c.127.96.361 1.903.7 2.81a2 2 0 01-.45 2.11L8.09 9.91a16 16 0 006 6l1.27-1.27a2 2 0 012.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0122 16.92z"/>
                </svg>
                <input v-model="phone" type="tel" placeholder="请输入手机号" class="has-icon" @keyup.enter="submit" />
              </div>
            </div>
            <div class="lf-group">
              <label>密码</label>
              <div class="input-wrap">
                <svg class="input-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0110 0v4"/>
                </svg>
                <input v-model="password" type="password" placeholder="请输入密码" class="has-icon" @keyup.enter="submit" />
              </div>
            </div>
          </template>

          <!-- register form -->
          <template v-else>
            <div class="lf-group">
              <label>手机号 <span class="req">*</span></label>
              <div class="input-wrap">
                <svg class="input-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M22 16.92v3a2 2 0 01-2.18 2 19.79 19.79 0 01-8.63-3.07 19.5 19.5 0 01-6-6A19.79 19.79 0 012.12 4.18 2 2 0 014.11 2h3a2 2 0 012 1.72c.127.96.361 1.903.7 2.81a2 2 0 01-.45 2.11L8.09 9.91a16 16 0 006 6l1.27-1.27a2 2 0 012.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0122 16.92z"/>
                </svg>
                <input v-model="phone" type="tel" placeholder="11位手机号" class="has-icon" />
              </div>
            </div>
            <div class="lf-row">
              <div class="lf-group">
                <label>姓名 <span class="req">*</span></label>
                <input v-model="name" placeholder="真实姓名" />
              </div>
              <div class="lf-group">
                <label>密码 <span class="req">*</span></label>
                <input v-model="password" type="password" placeholder="至少6位" />
              </div>
            </div>

            <div class="lf-group">
              <label>职务 <span class="req">*</span></label>
              <div class="radio-group">
                <label v-for="jt in JOB_TITLES" :key="jt.v" class="radio-item" :class="{ selected: jobTitle === jt.v }">
                  <input type="radio" v-model="jobTitle" :value="jt.v" />
                  {{ jt.label }}
                </label>
              </div>
            </div>

            <div class="lf-group">
              <label>所属部门 <span class="req">*</span> <span class="hint-text">可多选</span></label>
              <div class="check-group">
                <label
                  v-for="d in DEPARTMENTS" :key="d"
                  class="check-item"
                  :class="{ selected: selectedDepts.includes(d) }"
                  @click="toggleDept(d)"
                >
                  <span class="check-box">
                    <svg v-if="selectedDepts.includes(d)" width="10" height="10" viewBox="0 0 12 12" fill="none">
                      <path d="M2 6l3 3 5-5" stroke="white" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>
                  </span>
                  {{ d }}
                </label>
              </div>
            </div>
          </template>

          <button class="btn btn-primary submit-btn" :disabled="loading" @click="submit">
            <span v-if="loading" class="loading-dot"></span>
            {{ loading ? '处理中…' : (mode === 'login' ? '登 录' : '提交注册') }}
          </button>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex; align-items: center; justify-content: center;
  position: relative;
  overflow: hidden;
}

/* extra background orbs for login page */
.login-bg { position: fixed; inset: 0; pointer-events: none; }
.login-orb { position: absolute; border-radius: 50%; filter: blur(80px); }
.lo1 { width:650px; height:650px; background:radial-gradient(circle,#c96342,transparent); top:-200px; left:-200px; opacity:0.25; animation: orb1 20s ease-in-out infinite; }
.lo2 { width:450px; height:450px; background:radial-gradient(circle,#e8a84a,transparent); bottom:-150px; right:-100px; opacity:0.2; animation: orb2 16s ease-in-out infinite; }
.lo3 { width:350px; height:350px; background:radial-gradient(circle,#c96342,transparent); top:40%; left:45%; opacity:0.12; animation: orb3 18s ease-in-out infinite; }

@keyframes orb1 { 0%,100%{transform:translate(0,0)scale(1)}33%{transform:translate(50px,70px)scale(1.07)}66%{transform:translate(-30px,40px)scale(0.96)} }
@keyframes orb2 { 0%,100%{transform:translate(0,0)scale(1)}40%{transform:translate(-60px,-40px)scale(1.09)}70%{transform:translate(25px,60px)scale(0.93)} }
@keyframes orb3 { 0%,100%{transform:translate(0,0)scale(1)}50%{transform:translate(-70px,-50px)scale(1.14)} }

.login-wrap {
  position: relative; z-index: 1;
  display: flex; align-items: stretch; gap: 0;
  max-width: 960px; width: 95vw;
  border-radius: 26px;
  overflow: hidden;
  box-shadow: 0 32px 96px rgba(100,60,30,0.28), 0 1px 0 rgba(255,255,255,0.5) inset;
  animation: cardIn 0.5s cubic-bezier(0.34,1.4,0.64,1) both, wrapBreathe 6s ease-in-out 0.6s infinite;
}

/* gentle breathing of the whole panel */
@keyframes wrapBreathe {
  0%, 100% { box-shadow: 0 32px 96px rgba(100,60,30,0.28), 0 1px 0 rgba(255,255,255,0.5) inset; }
  50%      { box-shadow: 0 38px 110px rgba(201,99,66,0.34), 0 1px 0 rgba(255,255,255,0.6) inset; }
}

@keyframes cardIn {
  from { opacity:0; transform:scale(0.94) translateY(20px); }
  to   { opacity:1; transform:scale(1) translateY(0); }
}

/* brand panel */
.login-brand {
  width: 312px; flex-shrink: 0;
  background: linear-gradient(160deg, rgba(40,20,12,0.92) 0%, rgba(60,28,14,0.88) 100%);
  backdrop-filter: blur(20px);
  border-right: 1px solid rgba(255,255,255,0.07);
  padding: 56px 38px;
  display: flex; flex-direction: column; justify-content: center; gap: 20px;
  color: #e8d4c4;
}
.brand-icon-lg {
  width: 72px; height: 72px; border-radius: 20px;
  background: rgba(201,99,66,0.18);
  display: flex; align-items: center; justify-content: center;
  box-shadow: 0 0 28px rgba(201,99,66,0.25);
  margin-bottom: 4px;
  animation: iconBreathe 3.4s ease-in-out infinite;
}
@keyframes iconBreathe {
  0%, 100% { box-shadow: 0 0 26px rgba(201,99,66,0.25); transform: scale(1); }
  50%      { box-shadow: 0 0 40px rgba(232,133,90,0.55); transform: scale(1.05); }
}
.brand-title { font-size: 31px; font-weight: 800; color: #fff; line-height: 1.2; white-space: nowrap; letter-spacing: 0.01em; }
.brand-sub { font-size: 13px; color: rgba(201,99,66,0.9); letter-spacing: 0.2em; font-weight: 600; }
.brand-features { display: flex; flex-direction: column; gap: 10px; margin-top: 8px; }
.feature { display: flex; align-items: center; gap: 10px; font-size: 13px; color: rgba(232,212,196,0.75); }
.f-dot { width: 6px; height: 6px; border-radius: 50%; background: linear-gradient(135deg, #e8855a, #c96342); flex-shrink: 0; }

/* card panel */
.login-card {
  flex: 1;
  background: rgba(255,252,248,0.78);
  backdrop-filter: blur(28px) saturate(180%);
  -webkit-backdrop-filter: blur(28px) saturate(180%);
  padding: 48px 44px;
  display: flex; flex-direction: column; justify-content: center;
}

/* mode tabs */
.mode-tabs {
  display: flex; gap: 0; margin-bottom: 28px;
  background: rgba(0,0,0,0.05); border-radius: 12px;
  padding: 4px; width: fit-content;
}
.mode-tab {
  padding: 8px 28px; border-radius: 8px; font-size: 14px; font-weight: 500;
  cursor: pointer; border: none; background: transparent;
  color: var(--muted); transition: all 0.22s;
}
.mode-tab.active {
  background: rgba(255,252,248,0.9);
  color: var(--primary); font-weight: 700;
  box-shadow: 0 2px 10px rgba(100,60,30,0.12);
}

/* form fields */
.lf-group { display: flex; flex-direction: column; gap: 6px; margin-bottom: 16px; }
.lf-group label { font-size: 12px; color: var(--muted); font-weight: 600; letter-spacing: 0.03em; display: flex; align-items: center; gap: 4px; }
.lf-row { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }

.req { color: #c62828; }
.hint-text { color: rgba(155,128,112,0.6); font-weight: 400; font-size: 11px; }

.input-wrap { position: relative; }
.input-icon {
  position: absolute; left: 12px; top: 50%; transform: translateY(-50%);
  color: rgba(155,128,112,0.6); pointer-events: none;
}
.has-icon { padding-left: 38px !important; }

/* radio for job title */
.radio-group { display: flex; gap: 8px; flex-wrap: wrap; }
.radio-item {
  display: flex; align-items: center; gap: 6px;
  padding: 7px 14px; border-radius: 20px;
  border: 1.5px solid var(--border);
  background: rgba(255,253,250,0.7);
  font-size: 13px; cursor: pointer;
  transition: all 0.18s;
}
.radio-item input { display: none; }
.radio-item.selected {
  border-color: var(--primary);
  background: rgba(201,99,66,0.08);
  color: var(--primary); font-weight: 600;
  box-shadow: 0 0 0 2px rgba(201,99,66,0.12);
}
.radio-item:hover:not(.selected) { border-color: rgba(201,99,66,0.4); background: rgba(201,99,66,0.05); }

/* checkboxes for departments */
.check-group { display: flex; flex-wrap: wrap; gap: 7px; }
.check-item {
  display: flex; align-items: center; gap: 6px;
  padding: 6px 12px; border-radius: 20px;
  border: 1.5px solid var(--border);
  background: rgba(255,253,250,0.7);
  font-size: 12px; cursor: pointer;
  transition: all 0.18s; user-select: none;
}
.check-item.selected {
  border-color: var(--primary);
  background: rgba(201,99,66,0.1);
  color: var(--primary); font-weight: 600;
}
.check-box {
  width: 14px; height: 14px; border-radius: 4px;
  border: 1.5px solid currentColor;
  background: transparent;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0; transition: background 0.15s;
}
.check-item.selected .check-box { background: var(--primary); border-color: var(--primary); }

/* submit */
.submit-btn {
  width: 100%; justify-content: center;
  padding: 12px; font-size: 15px; font-weight: 600;
  border-radius: 12px; margin-top: 8px;
  letter-spacing: 0.04em;
}

/* loading dot */
.loading-dot {
  width: 14px; height: 14px; border-radius: 50%;
  border: 2px solid rgba(255,255,255,0.4);
  border-top-color: white;
  animation: spin 0.7s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* pending state */
.pending-state { text-align: center; padding: 16px 0; }
.pending-icon { font-size: 56px; margin-bottom: 16px; display: block; animation: float 2s ease-in-out infinite; }
@keyframes float { 0%,100%{transform:translateY(0)} 50%{transform:translateY(-6px)} }
.pending-state h3 { font-size: 20px; font-weight: 700; margin-bottom: 12px; }
.pending-state p { color: var(--muted); font-size: 14px; line-height: 1.6; }
.pending-hint { font-size: 12px; margin-top: 8px; color: rgba(155,128,112,0.7) !important; display: flex; align-items: center; justify-content: center; gap: 6px; }
.mt { margin-top: 24px; }

/* waiting loader */
.approve-loader { position: relative; width: 76px; height: 76px; margin: 0 auto 20px; }
.approve-loader .ring {
  position: absolute; inset: 0; border-radius: 50%;
  border: 3px solid rgba(201,99,66,0.15);
  border-top-color: var(--primary);
  animation: spin 1s linear infinite;
}
.approve-loader .ring-icon {
  position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
  font-size: 30px; animation: float 2s ease-in-out infinite;
}
.live-dot {
  width: 7px; height: 7px; border-radius: 50%; background: #2e7d32;
  display: inline-block; animation: livepulse 1.4s ease-in-out infinite;
}
@keyframes livepulse { 0%,100%{opacity:1;box-shadow:0 0 0 0 rgba(46,125,50,0.4)} 50%{opacity:0.5;box-shadow:0 0 0 5px rgba(46,125,50,0)} }

/* success check */
.success-check { margin: 0 auto 18px; width: 52px; height: 52px; animation: checkPop 0.5s cubic-bezier(0.34,1.7,0.5,1) both; }
.sc-circle { stroke: #2e7d32; stroke-width: 2.5; stroke-dasharray: 151; stroke-dashoffset: 151; animation: scCircle 0.5s ease forwards; }
.sc-check  { stroke: #2e7d32; stroke-width: 3.5; stroke-linecap: round; stroke-linejoin: round; stroke-dasharray: 40; stroke-dashoffset: 40; animation: scCheck 0.35s 0.45s ease forwards; }
@keyframes scCircle { to { stroke-dashoffset: 0; } }
@keyframes scCheck  { to { stroke-dashoffset: 0; } }
@keyframes checkPop { 0% { transform: scale(0.3); opacity: 0; } 100% { transform: scale(1); opacity: 1; } }

/* approved celebration */
.approved-state { position: relative; }
.approved-title {
  color: #2e7d32; font-size: 23px !important;
  animation: joyPop 0.55s cubic-bezier(0.34,1.7,0.5,1) both;
}
.approved-sub { animation: slideUpJoy 0.5s 0.15s both; }
@keyframes joyPop { 0% { transform: scale(0.6); opacity: 0; } 100% { transform: scale(1); opacity: 1; } }
@keyframes slideUpJoy { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }

.confetti { position: absolute; inset: 0; pointer-events: none; overflow: visible; }
.confetti i {
  position: absolute; top: 18%; left: 50%;
  width: 8px; height: 14px; border-radius: 2px;
  background: hsl(calc(var(--i) * 50), 85%, 60%);
  opacity: 0;
  animation: confettiBurst 1.5s calc(var(--i) * 0.04s) ease-out infinite;
}
@keyframes confettiBurst {
  0%   { opacity: 0; transform: translate(0,0) rotate(0deg) scale(0.6); }
  15%  { opacity: 1; }
  100% {
    opacity: 0;
    transform:
      translate(calc((var(--i) - 7) * 26px), calc(120px + var(--i) * 6px))
      rotate(calc(var(--i) * 90deg)) scale(1);
  }
}

/* responsive: hide brand panel on mobile */
@media (max-width: 640px) {
  .login-brand { display: none; }
  .login-card { padding: 36px 28px; }
  .login-wrap { max-width: 400px; }
  .lf-row { grid-template-columns: 1fr; }
}
</style>
