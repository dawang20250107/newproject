<template>
  <div class="login-page">
    <div class="login-card">
      <div class="login-logo">
        <svg width="48" height="48" viewBox="0 0 32 32" fill="none">
          <defs>
            <linearGradient id="lg" x1="4" y1="3" x2="28" y2="29" gradientUnits="userSpaceOnUse">
              <stop stop-color="#fff3b0"/>
              <stop offset="0.5" stop-color="#d4af37"/>
              <stop offset="1" stop-color="#a16207"/>
            </linearGradient>
          </defs>
          <circle cx="16" cy="16" r="14.5" fill="url(#lg)"/>
          <circle cx="11.1" cy="11.3" r="2.1" fill="#fff" fill-opacity=".95"/>
          <circle cx="16" cy="9.5" r="2.3" fill="#fff" fill-opacity=".95"/>
          <circle cx="20.9" cy="11.3" r="2.1" fill="#fff" fill-opacity=".95"/>
          <path d="M11.9 19.8c0-2.4 1.8-4.4 4.1-4.4s4.1 2 4.1 4.4c0 2.3-1.8 4.1-4.1 4.1s-4.1-1.8-4.1-4.1Z" fill="#fff" fill-opacity=".95"/>
        </svg>
      </div>
      <h1 class="login-title">KXT 工作台</h1>
      <p class="login-sub">请登录您的账号</p>

      <form class="login-form" @submit.prevent="handleLogin">
        <div class="field">
          <label>用户名</label>
          <input
            v-model="username"
            type="text"
            placeholder="请输入用户名"
            autocomplete="username"
            :disabled="loading"
          />
        </div>
        <div class="field">
          <label>密码</label>
          <input
            v-model="password"
            type="password"
            placeholder="请输入密码"
            autocomplete="current-password"
            :disabled="loading"
          />
        </div>

        <p v-if="errMsg" class="err-msg">{{ errMsg }}</p>

        <button type="submit" class="btn-login" :disabled="loading">
          <span v-if="loading" class="spinner"></span>
          {{ loading ? '登录中...' : '登录' }}
        </button>
      </form>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { auth } from '@/api/index.js'

const router = useRouter()
const username = ref('')
const password = ref('')
const loading = ref(false)
const errMsg = ref('')

async function handleLogin() {
  if (!username.value.trim() || !password.value) {
    errMsg.value = '请输入用户名和密码'
    return
  }
  loading.value = true
  errMsg.value = ''
  try {
    const data = await auth.login(username.value.trim(), password.value)
    localStorage.setItem('kxt_token', data.token)
    localStorage.setItem('kxt_user', JSON.stringify({ username: data.username, display_name: data.display_name }))
    router.push('/daily-report')
  } catch (err) {
    errMsg.value = err.response?.data?.error || '登录失败，请检查用户名和密码'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #0f172a 0%, #1e293b 60%, #0f172a 100%);
}

.login-card {
  width: 360px;
  background: rgba(30, 41, 59, 0.95);
  border: 1px solid rgba(212, 175, 55, 0.18);
  border-radius: 20px;
  padding: 48px 40px 40px;
  box-shadow: 0 24px 64px rgba(0, 0, 0, 0.5);
  text-align: center;
}

.login-logo {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 72px; height: 72px;
  background: rgba(212, 175, 55, 0.12);
  border-radius: 18px;
  margin-bottom: 20px;
  filter: drop-shadow(0 4px 16px rgba(212, 175, 55, 0.35));
}

.login-title {
  font-size: 24px;
  font-weight: 700;
  background: linear-gradient(135deg, #fff3b0, #d4af37);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  margin: 0 0 6px;
}

.login-sub {
  font-size: 13px;
  color: rgba(148, 163, 184, 0.7);
  margin: 0 0 32px;
}

.login-form {
  text-align: left;
}

.field {
  margin-bottom: 20px;
}
.field label {
  display: block;
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: rgba(148, 163, 184, 0.7);
  margin-bottom: 8px;
}
.field input {
  width: 100%;
  box-sizing: border-box;
  padding: 12px 16px;
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(212, 175, 55, 0.15);
  border-radius: 10px;
  color: #e2e8f0;
  font-size: 14px;
  outline: none;
  transition: border-color 0.2s;
}
.field input:focus {
  border-color: rgba(212, 175, 55, 0.5);
  box-shadow: 0 0 0 3px rgba(212, 175, 55, 0.08);
}
.field input:disabled { opacity: 0.5; cursor: not-allowed; }

.err-msg {
  font-size: 13px;
  color: #f87171;
  margin: -8px 0 16px;
  text-align: center;
}

.btn-login {
  width: 100%;
  padding: 13px;
  background: linear-gradient(135deg, #d4af37, #a16207);
  border: none;
  border-radius: 10px;
  color: #0f172a;
  font-size: 15px;
  font-weight: 700;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  transition: opacity 0.2s, transform 0.1s;
  margin-top: 8px;
}
.btn-login:hover:not(:disabled) { opacity: 0.9; transform: translateY(-1px); }
.btn-login:disabled { opacity: 0.5; cursor: not-allowed; }

.spinner {
  width: 14px; height: 14px;
  border: 2px solid rgba(15,23,42,0.3);
  border-top-color: #0f172a;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
</style>
