import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import api from '../api/index.js'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('cw_token') || '')
  const user = ref(JSON.parse(localStorage.getItem('cw_user') || 'null'))
  const perms = ref(JSON.parse(localStorage.getItem('cw_perms') || 'null'))

  const isLoggedIn = computed(() => !!token.value)
  const role = computed(() => user.value?.role || '')
  const isSuperAdmin = computed(() => role.value === 'super_admin')
  const isAdmin = computed(() => isSuperAdmin.value || perms.value?.is_admin)
  const canUpload = computed(() => perms.value?.can_upload || false)
  const canPublish = computed(() => perms.value?.can_publish || false)
  const canDelete = computed(() => perms.value?.can_delete || false)

  function canPage(key) {
    return perms.value?.pages?.[key] ?? false
  }

  function setAuth(t, u, p) {
    token.value = t
    user.value = u
    perms.value = p
    localStorage.setItem('cw_token', t)
    localStorage.setItem('cw_user', JSON.stringify(u))
    localStorage.setItem('cw_perms', JSON.stringify(p))
  }

  function logout() {
    token.value = ''
    user.value = null
    perms.value = null
    localStorage.removeItem('cw_token')
    localStorage.removeItem('cw_user')
    localStorage.removeItem('cw_perms')
  }

  async function refresh() {
    if (!token.value) return
    try {
      const res = await api.get('/me')
      if (res.code === 0) setAuth(res.data.token, res.data.user, res.data.permissions)
    } catch {}
  }

  return {
    token, user, perms,
    isLoggedIn, role, isSuperAdmin, isAdmin,
    canUpload, canPublish, canDelete,
    canPage, setAuth, logout, refresh,
  }
})
