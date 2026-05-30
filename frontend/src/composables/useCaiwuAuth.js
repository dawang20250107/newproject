import { computed, reactive } from 'vue'
import { useAuthStore } from '../stores/auth.js'

// Adapter exposing the caiwu views' expected auth interface, backed by the
// unified paikuan auth store. Page keys (report/data/charts) map to the
// caiwu_* page namespace; field/capability checks read the caiwu_* perm keys.
// This lets the financial-analysis views run inside the paikuan SPA almost
// unchanged (they import this instead of their old standalone store).

const CAIWU_PAGE_MAP = {
  report: 'caiwu_report',
  data: 'caiwu_data',
  charts: 'caiwu_charts',
}
// Pages that were super_admin-only in the standalone caiwu app.
const ADMIN_ONLY_PAGES = ['settings', 'users', 'permissions']

export function useCaiwuAuth() {
  const auth = useAuthStore()

  const isLoggedIn = computed(() => auth.isLoggedIn)
  const user = computed(() => auth.user)
  const role = computed(() => auth.role)
  const isSuperAdmin = computed(() => auth.isSuperAdmin)
  const isAdmin = computed(() => auth.isAdmin)

  function canPage(key) {
    if (auth.isAdmin) return true
    if (ADMIN_ONLY_PAGES.includes(key)) return false
    const pk = CAIWU_PAGE_MAP[key]
    if (!pk) return false
    return auth.canPage(pk)
  }
  function canView(key) {
    if (auth.isAdmin) return true
    return auth.perms?.caiwu_view?.[key] !== false
  }
  const canUpload = computed(() => auth.isAdmin || auth.perms?.caiwu_upload === true)
  const canPublish = computed(() => auth.isAdmin || auth.perms?.caiwu_publish === true)
  const canDelete = computed(() => auth.isAdmin || auth.perms?.caiwu_delete === true)

  // reactive() unwraps the computed refs on property access, mirroring how a
  // Pinia store instance exposes its getters as plain reactive values.
  return reactive({
    isLoggedIn, user, role, isSuperAdmin, isAdmin,
    canPage, canView, canUpload, canPublish, canDelete,
    logout: auth.logout,
  })
}
