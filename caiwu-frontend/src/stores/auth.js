import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import api from '../api/index.js'

// Pages restricted to super_admin (not part of the job-title matrix).
const ADMIN_ONLY_PAGES = ['settings', 'users', 'permissions']

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('cw_token') || '')
  const user = ref(JSON.parse(localStorage.getItem('cw_user') || 'null'))
  const perms = ref(JSON.parse(localStorage.getItem('cw_perms') || 'null'))

  const isLoggedIn = computed(() => !!token.value)
  const role = computed(() => user.value?.role || '')
  const isSuperAdmin = computed(() => role.value === 'super_admin')
  const isAdmin = computed(() => isSuperAdmin.value || perms.value?.is_admin === true)

  // ── granular permission helpers (job-title matrix from backend) ──
  function canPage(key) {
    if (isAdmin.value) return true
    if (ADMIN_ONLY_PAGES.includes(key)) return false
    return perms.value?.pages?.[key] !== false
  }
  function canView(key) {
    if (isAdmin.value) return true
    return perms.value?.view?.[key] !== false
  }
  const canUpload = computed(() => isAdmin.value || perms.value?.can_upload === true)
  const canPublish = computed(() => isAdmin.value || perms.value?.can_publish === true)
  const canDelete = computed(() => isAdmin.value || perms.value?.can_delete === true)

  function setAuth(t, u, p) {
    token.value = t
    user.value = u
    if (p !== undefined) perms.value = p
    localStorage.setItem('cw_token', t)
    localStorage.setItem('cw_user', JSON.stringify(u))
    if (p !== undefined) localStorage.setItem('cw_perms', JSON.stringify(p))
  }

  function logout() {
    token.value = ''
    user.value = null
    perms.value = null
    localStorage.removeItem('cw_token')
    localStorage.removeItem('cw_user')
    localStorage.removeItem('cw_perms')
  }

  async function login(phone, password) {
    const res = await api.post('/login', { phone, password })
    if (res.data?.pending) {
      return { pending: true, msg: res.data.msg }
    }
    setAuth(res.data.token, res.data.user, res.data.permissions)
    return { pending: false }
  }

  async function register(payload) {
    const res = await api.post('/register', payload)
    if (res.data?.pending) {
      return { pending: true, msg: res.data.msg }
    }
    setAuth(res.data.token, res.data.user, res.data.permissions)
    return { pending: false }
  }

  async function refresh() {
    if (!token.value) return
    try {
      const res = await api.get('/me')
      if (res.data?.token) setAuth(res.data.token, res.data.user, res.data.permissions)
    } catch {}
  }

  return {
    token, user, perms,
    isLoggedIn, role, isSuperAdmin, isAdmin,
    canUpload, canPublish, canDelete,
    canPage, canView, setAuth, logout, login, register, refresh,
  }
})
