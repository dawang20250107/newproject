import { createRouter, createWebHashHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth.js'

const routes = [
  { path: '/login', component: () => import('../views/Login.vue'), meta: { public: true } },
  { path: '/', redirect: '/dashboard' },
  { path: '/dashboard', component: () => import('../views/Dashboard.vue'), meta: { page: 'dashboard' } },
  { path: '/payments', component: () => import('../views/Payments.vue'), meta: { page: 'payments' } },
  { path: '/stats', component: () => import('../views/Stats.vue'), meta: { page: 'stats' } },
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
  for (const p of ['dashboard', 'payments', 'stats']) {
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
