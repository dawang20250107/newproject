<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth.js'

const router = useRouter()
const auth = useAuthStore()

const mode = ref('login')  // 'login' | 'register'
const phone = ref('')
const password = ref('')
const name = ref('')
const error = ref('')
const loading = ref(false)

async function submit() {
  error.value = ''
  loading.value = true
  try {
    if (mode.value === 'login') {
      await auth.login(phone.value, password.value)
    } else {
      await auth.register(phone.value, password.value, name.value)
    }
    router.push('/dashboard')
  } catch (e) {
    error.value = e?.error || '操作失败，请重试'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <div class="login-card">
      <div class="login-logo">💸</div>
      <h2>排款管理系统</h2>
      <p class="login-sub">{{ mode === 'login' ? '登录账号' : '注册新账号' }}</p>

      <div v-if="error" class="alert alert-err">{{ error }}</div>

      <div class="form-group" style="margin-bottom:12px">
        <label>手机号</label>
        <input v-model="phone" type="tel" placeholder="请输入手机号" @keyup.enter="submit" />
      </div>

      <div v-if="mode === 'register'" class="form-group" style="margin-bottom:12px">
        <label>姓名</label>
        <input v-model="name" placeholder="请输入姓名" @keyup.enter="submit" />
      </div>

      <div class="form-group" style="margin-bottom:20px">
        <label>密码</label>
        <input v-model="password" type="password" placeholder="至少6位" @keyup.enter="submit" />
      </div>

      <button class="btn btn-primary" style="width:100%;justify-content:center" :disabled="loading" @click="submit">
        {{ loading ? '处理中…' : (mode === 'login' ? '登录' : '注册') }}
      </button>

      <p class="login-toggle">
        {{ mode === 'login' ? '没有账号？' : '已有账号？' }}
        <a href="#" @click.prevent="mode = mode === 'login' ? 'register' : 'login'">
          {{ mode === 'login' ? '注册' : '返回登录' }}
        </a>
      </p>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  min-height: 100vh; display: flex; align-items: center; justify-content: center;
  background: var(--bg);
}
.login-card {
  width: 380px; max-width: 94vw;
  background: var(--card); border-radius: 20px; padding: 40px 36px;
  box-shadow: 0 8px 32px rgba(100,60,30,.18);
  text-align: center;
}
.login-logo { font-size: 44px; margin-bottom: 12px; }
h2 { font-size: 22px; font-weight: 700; margin-bottom: 4px; }
.login-sub { color: var(--muted); margin-bottom: 24px; font-size: 13px; }
.login-toggle { margin-top: 16px; font-size: 13px; color: var(--muted); }
.login-toggle a { color: var(--primary); font-weight: 600; }
</style>
