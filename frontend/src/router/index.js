import { createRouter, createWebHashHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth.js'

const routes = [
  { path: '/login', component: () => import('../views/Login.vue'), meta: { public: true } },
  { path: '/', redirect: '/dashboard' },
  { path: '/dashboard', component: () => import('../views/Dashboard.vue'), meta: { page: 'dashboard' } },
  { path: '/payments', component: () => import('../views/Payments.vue'), meta: { page: 'payments' } },
  { path: '/approvals', component: () => import('../views/ApprovalRecords.vue'), meta: { page: 'approval_records' } },
  { path: '/stats', component: () => import('../views/Stats.vue'), meta: { page: 'stats' } },
  // AR module
  { path: '/ar/projects', component: () => import('../views/ar/ARProjects.vue'), meta: { page: 'ar_projects' } },
  { path: '/ar/records', component: () => import('../views/ar/ARRecords.vue'), meta: { page: 'ar_records' } },
  { path: '/ar/advances', component: () => import('../views/ar/Advances.vue'), meta: { page: 'ar_advance' } },
  { path: '/ar/analytics', component: () => import('../views/ar/ARAnalytics.vue'), meta: { page: 'ar_analytics' } },
  { path: '/ar/cashflow', component: () => import('../views/ar/Cashflow.vue'), meta: { page: 'ar_cashflow' } },
  { path: '/ar/budget', component: () => import('../views/ar/Budget.vue'), meta: { page: 'ar_budget' } },
  // 财务分析 (caiwu) module
  { path: '/caiwu/report', component: () => import('../views/caiwu/Report.vue'), meta: { page: 'caiwu_report' } },
  { path: '/caiwu/data', component: () => import('../views/caiwu/DataImport.vue'), meta: { page: 'caiwu_data' } },
  { path: '/caiwu/charts', component: () => import('../views/caiwu/Charts.vue'), meta: { page: 'caiwu_charts' } },
  { path: '/caiwu/project-margin', component: () => import('../views/caiwu/ProjectMargin.vue'), meta: { page: 'caiwu_charts' } },
  { path: '/caiwu/cockpit', component: () => import('../views/caiwu/Cockpit.vue'), meta: { page: 'caiwu_cockpit' } },
  { path: '/caiwu/knowledge', component: () => import('../views/caiwu/KnowledgeBase.vue'), meta: { page: 'caiwu_cockpit' } },
  { path: '/caiwu/metrics', component: () => import('../views/caiwu/Metrics.vue'), meta: { page: 'caiwu_metrics' } },
  { path: '/caiwu/settings', component: () => import('../views/caiwu/Settings.vue'), meta: { role: 'super_admin' } },
  // Admin
  { path: '/users', component: () => import('../views/Users.vue'), meta: { role: 'super_admin' } },
  { path: '/permissions', component: () => import('../views/Permissions.vue'), meta: { role: 'super_admin' } },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

function canVisit(auth, page) {
  if (!auth.canPage(page)) return false
  // 月度统计 is entirely amount-based; hide it from users who can't view amounts.
  if (page === 'stats' && !auth.canView('total_amount')) return false
  return true
}

function firstAllowedPage(auth) {
  for (const p of ['dashboard', 'payments', 'approval_records', 'stats']) {
    if (canVisit(auth, p)) return '/' + p
  }
  return '/payments'
}

router.beforeEach((to, _from, next) => {
  const auth = useAuthStore()
  if (to.meta.public) return next()
  if (!auth.isLoggedIn) return next('/login')
  if (to.meta.role === 'super_admin' && !auth.isSuperAdmin) return next(firstAllowedPage(auth))
  if (to.meta.page && !canVisit(auth, to.meta.page)) return next(firstAllowedPage(auth))
  next()
})

export default router
