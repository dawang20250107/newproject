import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from '../api/index.js'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('pk_token') || '')
  const user = ref(JSON.parse(localStorage.getItem('pk_user') || 'null'))

  const isLoggedIn = computed(() => !!token.value)
  const role = computed(() => user.value?.role || '')
  const isSuperAdmin = computed(() => role.value === 'super_admin')
  const isManager = computed(() => ['super_admin', 'manager'].includes(role.value))
  const canWrite = computed(() => ['super_admin', 'manager', 'operator'].includes(role.value))

  function setAuth(t, u) {
    token.value = t
    user.value = u
    localStorage.setItem('pk_token', t)
    localStorage.setItem('pk_user', JSON.stringify(u))
  }

  function logout() {
    token.value = ''
    user.value = null
    localStorage.removeItem('pk_token')
    localStorage.removeItem('pk_user')
  }

  async function login(phone, password) {
    const res = await api.post('/login', { phone, password })
    setAuth(res.data.token, res.data.user)
    return res.data.user
  }

  async function register(phone, password, name) {
    const res = await api.post('/register', { phone, password, name })
    setAuth(res.data.token, res.data.user)
    return res.data.user
  }

  return { token, user, isLoggedIn, role, isSuperAdmin, isManager, canWrite, login, register, logout, setAuth }
})
