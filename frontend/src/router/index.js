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
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

function firstAllowedPage(auth) {
  for (const p of ['dashboard', 'payments', 'stats']) {
    if (auth.canPage(p)) return '/' + p
  }
  return '/payments'
}

router.beforeEach((to, _from, next) => {
  const auth = useAuthStore()
  if (to.meta.public) return next()
  if (!auth.isLoggedIn) return next('/login')
  if (to.meta.role === 'super_admin' && !auth.isSuperAdmin) return next(firstAllowedPage(auth))
  if (to.meta.page && !auth.canPage(to.meta.page)) return next(firstAllowedPage(auth))
  next()
})

export default router
