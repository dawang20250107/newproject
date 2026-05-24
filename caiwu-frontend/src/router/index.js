import { createRouter, createWebHashHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth.js'

const routes = [
  { path: '/login', component: () => import('../views/Login.vue'), meta: { public: true } },
  { path: '/', redirect: '/report' },
  { path: '/report', component: () => import('../views/Report.vue'), meta: { page: 'report' } },
  { path: '/data', component: () => import('../views/DataImport.vue'), meta: { page: 'data' } },
  { path: '/charts', component: () => import('../views/Charts.vue'), meta: { page: 'charts' } },
  { path: '/settings', component: () => import('../views/Settings.vue'), meta: { page: 'settings' } },
  { path: '/users', component: () => import('../views/Users.vue'), meta: { page: 'users' } },
  { path: '/permissions', component: () => import('../views/Permissions.vue'), meta: { page: 'permissions' } },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

const router = createRouter({
  history: createWebHashHistory('/caiwu/'),
  routes,
})

router.beforeEach((to, from, next) => {
  const auth = useAuthStore()
  if (to.meta.public) return next()
  if (!auth.isLoggedIn) return next('/login')
  if (to.meta.page && !auth.canPage(to.meta.page)) {
    // Redirect to first accessible page
    const pages = ['report', 'charts', 'data', 'settings']
    const first = pages.find(p => auth.canPage(p))
    return next(first ? `/${first}` : '/login')
  }
  next()
})

export default router
