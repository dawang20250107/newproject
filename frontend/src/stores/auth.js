import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from '../api/index.js'

function loadPerms() {
  try { return JSON.parse(localStorage.getItem('pk_perms') || 'null') } catch { return null }
}

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('pk_token') || '')
  const user = ref(JSON.parse(localStorage.getItem('pk_user') || 'null'))
  const perms = ref(loadPerms())

  const isLoggedIn = computed(() => !!token.value)
  const role = computed(() => user.value?.role || '')
  const isSuperAdmin = computed(() => role.value === 'super_admin')

  // ── permission helpers (driven by job-title config from the backend) ──
  const isAdmin = computed(() => isSuperAdmin.value || perms.value?.is_admin === true)
  function canView(fieldKey) {
    if (isAdmin.value) return true
    return perms.value?.view?.[fieldKey] !== false
  }
  function canEdit(fieldKey) {
    if (isAdmin.value) return true
    return perms.value?.edit?.[fieldKey] === true
  }
  function canPage(pageKey) {
    if (isAdmin.value) return true
    return perms.value?.pages?.[pageKey] !== false
  }
  const canCreate = computed(() => isAdmin.value || perms.value?.can_create === true)
  const canDelete = computed(() => isAdmin.value || perms.value?.can_delete === true)
  // any write capability (used to show the edit button at all)
  const canWrite = computed(() => isAdmin.value || perms.value?.can_create === true ||
    Object.values(perms.value?.edit || {}).some(Boolean))

  function setPerms(p) {
    perms.value = p
    if (p) localStorage.setItem('pk_perms', JSON.stringify(p))
    else localStorage.removeItem('pk_perms')
  }

  function setAuth(t, u, p) {
    token.value = t
    user.value = u
    localStorage.setItem('pk_token', t)
    localStorage.setItem('pk_user', JSON.stringify(u))
    if (p !== undefined) setPerms(p)
  }

  function logout() {
    token.value = ''
    user.value = null
    perms.value = null
    localStorage.removeItem('pk_token')
    localStorage.removeItem('pk_user')
    localStorage.removeItem('pk_perms')
  }

  async function login(phone, password) {
    const res = await api.post('/login', { phone, password })
    setAuth(res.data.token, res.data.user, res.data.permissions)
    return res.data.user
  }

  // Refresh user + permissions from server (perms may change while logged in).
  async function refresh() {
    try {
      const res = await api.get('/me')
      if (res.data?.user) {
        user.value = res.data.user
        localStorage.setItem('pk_user', JSON.stringify(res.data.user))
      }
      if (res.data?.permissions) setPerms(res.data.permissions)
    } catch { /* keep cached perms */ }
  }

  async function register({ phone, password, name, job_title, departments }) {
    const res = await api.post('/register', { phone, password, name, job_title, departments })
    if (res.data.pending) {
      return { pending: true, message: res.data.message }
    }
    setAuth(res.data.token, res.data.user, res.data.permissions)
    return { pending: false }
  }

  return {
    token, user, perms, isLoggedIn, role, isSuperAdmin, isAdmin,
    canView, canEdit, canPage, canCreate, canDelete, canWrite,
    login, register, logout, setAuth, setPerms, refresh,
  }
})
