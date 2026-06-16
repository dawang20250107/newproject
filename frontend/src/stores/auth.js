import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from '../api/index.js'
import { DEPARTMENTS } from '../constants.js'

function loadPerms() {
  try { return JSON.parse(localStorage.getItem('pk_perms') || 'null') } catch { return null }
}

function loadActiveDepts() {
  try { return JSON.parse(localStorage.getItem('pk_active_depts') || '[]') } catch { return [] }
}

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('pk_token') || '')
  const user = ref(JSON.parse(localStorage.getItem('pk_user') || 'null'))
  const perms = ref(loadPerms())
  const activeDepts = ref(loadActiveDepts())

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
  // AR field show/hide (keys namespaced p_* / r_*)
  function canArView(fieldKey) {
    if (isAdmin.value) return true
    return perms.value?.ar_view?.[fieldKey] !== false
  }
  const canCreate = computed(() => isAdmin.value || perms.value?.can_create === true)
  // AR (应收) 写入能力：含 ar_can_create（结算会计等），回退通用 can_create
  const canArWrite = computed(() => isAdmin.value ||
    perms.value?.ar_can_create === true || perms.value?.can_create === true)
  const canDelete = computed(() => isAdmin.value || perms.value?.can_delete === true)
  // any write capability (used to show the edit button at all)
  const canWrite = computed(() => isAdmin.value || perms.value?.can_create === true ||
    Object.values(perms.value?.edit || {}).some(Boolean))
  // 操作级权限（核销/回款录入等细粒度动作）。旧登录态无 actions 键时回退写权限，
  // 避免权限升级后未重新登录的用户被锁在外面。
  function canAction(key) {
    if (isAdmin.value) return true
    const acts = perms.value?.actions
    if (acts && typeof acts === 'object') return acts[key] === true
    return canArWrite.value || canCreate.value
  }

  // ── active-department scope (global filter at sidebar footer) ──
  // allowed = the user's full permission set (immutable per login)
  const allowedDepts = computed(() =>
    isSuperAdmin.value ? DEPARTMENTS : (user.value?.departments || []))
  // effective = currently active subset; empty selection means "all allowed"
  const effectiveDepts = computed(() => {
    if (!activeDepts.value.length) return allowedDepts.value
    return activeDepts.value.filter(d => allowedDepts.value.includes(d))
  })
  // true when activeDepts is a proper non-empty subset of allowed
  const isDeptScoped = computed(() =>
    activeDepts.value.length > 0 && activeDepts.value.length < allowedDepts.value.length)

  function setActiveDepts(list) {
    const allowed = allowedDepts.value
    const clean = Array.isArray(list) ? list.filter(d => allowed.includes(d)) : []
    // 全选等同于未选——按"无作用域"处理，避免在 URL 上拖一长串无意义参数
    activeDepts.value = (clean.length === allowed.length) ? [] : clean
    localStorage.setItem('pk_active_depts', JSON.stringify(activeDepts.value))
  }

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
    activeDepts.value = []
    localStorage.removeItem('pk_token')
    localStorage.removeItem('pk_user')
    localStorage.removeItem('pk_perms')
    localStorage.removeItem('pk_active_depts')
  }

  // 超管重置临时密码后，登录响应带 must_change_password → 强制改密
  const mustChangePassword = ref(false)

  async function login(phone, password) {
    const res = await api.post('/login', { phone, password })
    setAuth(res.data.token, res.data.user, res.data.permissions)
    mustChangePassword.value = !!res.data.must_change_password
    return res.data.user
  }

  // 自助改密：成功后服务端返回新 token（旧会话已失效），无缝续上
  async function changePassword(oldPassword, newPassword) {
    const res = await api.post('/me/password', { old_password: oldPassword, new_password: newPassword })
    if (res.data?.token) {
      token.value = res.data.token
      localStorage.setItem('pk_token', res.data.token)
    }
    if (res.data?.user) {
      user.value = res.data.user
      localStorage.setItem('pk_user', JSON.stringify(res.data.user))
    }
    mustChangePassword.value = false
    return res.data
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
    canView, canEdit, canPage, canArView, canCreate, canArWrite, canDelete, canWrite, canAction,
    activeDepts, allowedDepts, effectiveDepts, isDeptScoped, setActiveDepts,
    login, register, logout, setAuth, setPerms, refresh,
    mustChangePassword, changePassword,
  }
})
