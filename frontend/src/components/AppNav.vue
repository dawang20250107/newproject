<script setup>
import { computed, ref, watch, onBeforeUnmount } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '../stores/auth.js'
import { ROLE_LABELS, JOB_LABELS } from '../constants.js'
import ChangePasswordModal from './ChangePasswordModal.vue'

const props = defineProps({
  collapsed: { type: Boolean, default: false },
  mobileOpen: { type: Boolean, default: false },
})
const emit = defineEmits(['update:collapsed', 'close-mobile', 'hover'])

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

// When the mobile drawer is open we always show full labels, regardless of
// the desktop collapse preference.
const effectiveCollapsed = computed(() => props.mobileOpen ? false : props.collapsed)

// 性能模式：关停毛玻璃/动画等装饰效果，解决低配电脑滚动闪屏
const perfLite = ref(document.documentElement.classList.contains('perf-lite'))
function togglePerfLite() {
  perfLite.value = !perfLite.value
  document.documentElement.classList.toggle('perf-lite', perfLite.value)
  localStorage.setItem('pk_perf_lite', perfLite.value ? '1' : '0')
}

// 表格密度切换：compact → comfortable → spacious，持久化
const DENSITIES = ['compact', 'comfortable', 'spacious']
const DENSITY_LABELS = { compact: '紧凑', comfortable: '适中', spacious: '宽松' }
const density = ref(localStorage.getItem('pk_density') || 'comfortable')
function applyDensity(d) {
  DENSITIES.forEach(v => document.documentElement.classList.remove(`density-${v}`))
  if (d !== 'comfortable') document.documentElement.classList.add(`density-${d}`)
}
applyDensity(density.value)
function cycleDensity() {
  const next = DENSITIES[(DENSITIES.indexOf(density.value) + 1) % DENSITIES.length]
  density.value = next
  localStorage.setItem('pk_density', next)
  applyDensity(next)
}

function logout() {
  emit('close-mobile')
  auth.logout()
  router.push('/login')
}

const showChangePwd = ref(false)
const pwdChangedOk = ref(false)
let _pwdOkTimer = null
function onChangePwdClose(success) {
  showChangePwd.value = false
  if (success) {
    pwdChangedOk.value = true
    clearTimeout(_pwdOkTimer)
    _pwdOkTimer = setTimeout(() => { pwdChangedOk.value = false }, 3000)
  }
}

function toggleCollapse() {
  emit('update:collapsed', !props.collapsed)
}

function onNavClick() {
  emit('close-mobile')
}

// ── Active-department picker ──────────────────────────────────────────────
const deptPopOpen = ref(false)
// Local draft state — only committed on "应用". Init from current activeDepts;
// empty activeDepts means "all" → pre-check everything for clearer affordance.
const draftDepts = ref([])

const hasDeptChoice = computed(() => auth.allowedDepts.length > 1)
const scopeLabel = computed(() =>
  `管辖 ${auth.effectiveDepts.length} / ${auth.allowedDepts.length} 部门`)

function openDeptPop() {
  if (!hasDeptChoice.value) return
  // Pre-fill draft from current effective selection (all if unscoped)
  draftDepts.value = [...auth.effectiveDepts]
  deptPopOpen.value = true
}
function closeDeptPop() { deptPopOpen.value = false }
function toggleDraft(d) {
  const i = draftDepts.value.indexOf(d)
  if (i >= 0) draftDepts.value.splice(i, 1)
  else draftDepts.value.push(d)
}
function selectAll() { draftDepts.value = [...auth.allowedDepts] }
function clearAll() { draftDepts.value = [] }
function applyDepts() {
  // setActiveDepts collapses "all" → [] internally
  auth.setActiveDepts(draftDepts.value)
  deptPopOpen.value = false
}

// Click outside to close
function onDocClick(e) {
  if (!deptPopOpen.value) return
  const root = document.querySelector('.dept-pop-anchor')
  if (root && !root.contains(e.target)) deptPopOpen.value = false
}
watch(deptPopOpen, (v) => {
  if (v) setTimeout(() => document.addEventListener('mousedown', onDocClick), 0)
  else document.removeEventListener('mousedown', onDocClick)
})
onBeforeUnmount(() => document.removeEventListener('mousedown', onDocClick))
</script>

<template>
  <nav :class="['sidebar', collapsed ? 'collapsed' : '', mobileOpen ? 'mobile-open' : '']"
    @mouseenter="emit('hover', true)" @mouseleave="emit('hover', false)">

    <!-- Brand -->
    <div class="sidebar-brand">
      <div class="brand-mark">
        <svg width="36" height="36" viewBox="0 0 36 36" fill="none">
          <rect x="1.5" y="1.5" width="33" height="33" rx="10" fill="url(#navgrad)"/>
          <rect x="2" y="2" width="32" height="32" rx="9.5" stroke="#fff" stroke-opacity="0.18"/>
          <path d="M14 10.5v15" stroke="#fff" stroke-width="2.4" stroke-linecap="round"/>
          <path d="M23 10.5 14 18l9.3 7.5" stroke="#fff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>
          <defs>
            <linearGradient id="navgrad" x1="1.5" y1="1.5" x2="34.5" y2="34.5" gradientUnits="userSpaceOnUse">
              <stop offset="0%" stop-color="#e8855a"/>
              <stop offset="100%" stop-color="#c96342"/>
            </linearGradient>
          </defs>
        </svg>
      </div>
      <Transition name="label-fade">
        <span v-if="!effectiveCollapsed" class="brand-name">KXT 财务系统</span>
      </Transition>
    </div>

    <!-- Nav links -->
    <div class="nav-links">
      <router-link v-if="auth.canPage('dashboard')" to="/dashboard" class="nav-item"
        :class="{ active: route.path === '/dashboard' }"
        :title="effectiveCollapsed ? '今日工作台' : undefined"
        @click="onNavClick">
        <span class="nav-icon">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/>
            <rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>
          </svg>
        </span>
        <Transition name="label-fade">
          <span v-if="!effectiveCollapsed" class="nav-label">今日工作台</span>
        </Transition>
      </router-link>

      <router-link v-if="auth.canPage('payments')" to="/payments" class="nav-item"
        :class="{ active: route.path === '/payments' }"
        :title="effectiveCollapsed ? '付款管理' : undefined"
        @click="onNavClick">
        <span class="nav-icon">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8l-6-6z"/>
            <path d="M14 2v6h6M8 13h8M8 17h5"/>
          </svg>
        </span>
        <Transition name="label-fade">
          <span v-if="!effectiveCollapsed" class="nav-label">付款管理</span>
        </Transition>
      </router-link>

      <router-link v-if="auth.canPage('approval_records')" to="/approvals" class="nav-item"
        :class="{ active: route.path === '/approvals' }"
        :title="effectiveCollapsed ? '审批管理' : undefined"
        @click="onNavClick">
        <span class="nav-icon">🧾</span>
        <Transition name="label-fade">
          <span v-if="!effectiveCollapsed" class="nav-label">审批管理</span>
        </Transition>
      </router-link>

      <router-link v-if="auth.canPage('stats') && auth.canView('total_amount')" to="/stats" class="nav-item"
        :class="{ active: route.path === '/stats' }"
        :title="effectiveCollapsed ? '月度统计' : undefined"
        @click="onNavClick">
        <span class="nav-icon">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/>
            <line x1="6" y1="20" x2="6" y2="14"/><line x1="2" y1="20" x2="22" y2="20"/>
          </svg>
        </span>
        <Transition name="label-fade">
          <span v-if="!effectiveCollapsed" class="nav-label">月度统计</span>
        </Transition>
      </router-link>

      <!-- ── 应收账款 section ───────────────────── -->
      <div v-if="auth.canPage('ar_projects') || auth.canPage('ar_records') || auth.canPage('ar_analytics') || auth.canPage('ar_cashflow') || auth.canPage('ar_budget')"
           class="nav-section-label">
        <Transition name="label-fade">
          <span v-if="!effectiveCollapsed" class="nav-sl-text">应收账款</span>
        </Transition>
        <span class="nav-sl-line"></span>
      </div>

      <router-link v-if="auth.canPage('ar_projects')" to="/ar/projects" class="nav-item"
        :class="{ active: route.path === '/ar/projects' }"
        :title="effectiveCollapsed ? '项目台账' : undefined"
        @click="onNavClick">
        <span class="nav-icon">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z"/>
          </svg>
        </span>
        <Transition name="label-fade">
          <span v-if="!effectiveCollapsed" class="nav-label">项目台账</span>
        </Transition>
      </router-link>

      <router-link v-if="auth.canPage('ar_projects')" to="/ar/customers" class="nav-item"
        :class="{ active: route.path === '/ar/customers' }"
        :title="effectiveCollapsed ? '客户管理' : undefined"
        @click="onNavClick">
        <span class="nav-icon">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/>
            <circle cx="9" cy="7" r="4"/>
            <path d="M23 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75"/>
          </svg>
        </span>
        <Transition name="label-fade">
          <span v-if="!effectiveCollapsed" class="nav-label">客户管理</span>
        </Transition>
      </router-link>

      <router-link v-if="auth.canPage('ar_records')" to="/ar/records" class="nav-item"
        :class="{ active: route.path === '/ar/records' }"
        :title="effectiveCollapsed ? '应收账款' : undefined"
        @click="onNavClick">
        <span class="nav-icon">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/>
          </svg>
        </span>
        <Transition name="label-fade">
          <span v-if="!effectiveCollapsed" class="nav-label">应收账款</span>
        </Transition>
      </router-link>

      <router-link v-if="auth.canPage('ar_advance')" to="/ar/advances" class="nav-item"
        :class="{ active: route.path === '/ar/advances' }"
        :title="effectiveCollapsed ? '预收预付' : undefined"
        @click="onNavClick">
        <span class="nav-icon">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 1v22"/><path d="M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6"/>
          </svg>
        </span>
        <Transition name="label-fade">
          <span v-if="!effectiveCollapsed" class="nav-label">预收预付</span>
        </Transition>
      </router-link>

      <router-link v-if="auth.canPage('ar_budget')" to="/ar/budget" class="nav-item"
        :class="{ active: route.path === '/ar/budget' }"
        :title="effectiveCollapsed ? '预算管理' : undefined"
        @click="onNavClick">
        <span class="nav-icon">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M3 3h18v4H3zM3 10h18v4H3zM3 17h18v4H3z"/>
          </svg>
        </span>
        <Transition name="label-fade">
          <span v-if="!effectiveCollapsed" class="nav-label">预算管理</span>
        </Transition>
      </router-link>

      <!-- ── 财务分析 section ───────────────────── -->
      <div v-if="auth.canPage('caiwu_report') || auth.canPage('caiwu_data') || auth.canPage('caiwu_charts') || auth.canPage('caiwu_metrics') || auth.canPage('caiwu_cockpit') || auth.isSuperAdmin"
           class="nav-section-label">
        <Transition name="label-fade">
          <span v-if="!effectiveCollapsed" class="nav-sl-text">财务分析</span>
        </Transition>
        <span class="nav-sl-line"></span>
      </div>

      <router-link v-if="auth.canPage('caiwu_cockpit')" to="/caiwu/cockpit" class="nav-item"
        :class="{ active: route.path === '/caiwu/cockpit' }"
        :title="effectiveCollapsed ? '财务驾驶舱' : undefined"
        @click="onNavClick">
        <span class="nav-icon">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <rect x="3" y="3" width="7" height="9"/><rect x="14" y="3" width="7" height="5"/>
            <rect x="14" y="12" width="7" height="9"/><rect x="3" y="16" width="7" height="5"/>
          </svg>
        </span>
        <Transition name="label-fade">
          <span v-if="!effectiveCollapsed" class="nav-label">财务驾驶舱</span>
        </Transition>
      </router-link>

      <router-link v-if="auth.canPage('caiwu_cockpit')" to="/caiwu/knowledge" class="nav-item"
        :class="{ active: route.path === '/caiwu/knowledge' }"
        :title="effectiveCollapsed ? '经营知识库' : undefined"
        @click="onNavClick">
        <span class="nav-icon">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>
          </svg>
        </span>
        <Transition name="label-fade">
          <span v-if="!effectiveCollapsed" class="nav-label">经营知识库</span>
        </Transition>
      </router-link>

      <router-link v-if="auth.canPage('caiwu_metrics')" to="/caiwu/metrics" class="nav-item"
        :class="{ active: route.path === '/caiwu/metrics' }"
        :title="effectiveCollapsed ? '指标管理' : undefined"
        @click="onNavClick">
        <span class="nav-icon">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M22 12h-4l-3 9L9 3l-3 9H2"/>
          </svg>
        </span>
        <Transition name="label-fade">
          <span v-if="!effectiveCollapsed" class="nav-label">指标管理</span>
        </Transition>
      </router-link>

      <router-link v-if="auth.canPage('caiwu_report')" to="/caiwu/report" class="nav-item"
        :class="{ active: route.path === '/caiwu/report' }"
        :title="effectiveCollapsed ? '财务报表' : undefined"
        @click="onNavClick">
        <span class="nav-icon">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/>
            <path d="M14 2v6h6M9 13l2 2 4-4"/>
          </svg>
        </span>
        <Transition name="label-fade">
          <span v-if="!effectiveCollapsed" class="nav-label">财务报表</span>
        </Transition>
      </router-link>

      <router-link v-if="auth.canPage('caiwu_charts')" to="/caiwu/project-margin" class="nav-item"
        :class="{ active: route.path === '/caiwu/project-margin' }"
        :title="effectiveCollapsed ? '项目毛利' : undefined"
        @click="onNavClick">
        <span class="nav-icon">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M3 3v18h18"/><rect x="7" y="10" width="3" height="7"/><rect x="12" y="6" width="3" height="11"/><rect x="17" y="13" width="3" height="4"/>
          </svg>
        </span>
        <Transition name="label-fade">
          <span v-if="!effectiveCollapsed" class="nav-label">项目毛利</span>
        </Transition>
      </router-link>

      <router-link v-if="auth.canPage('ar_analytics')" to="/caiwu/project-cashflow" class="nav-item"
        :class="{ active: route.path === '/caiwu/project-cashflow' }"
        :title="effectiveCollapsed ? '项目现金流' : undefined"
        @click="onNavClick">
        <span class="nav-icon">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 2v20M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6"/>
          </svg>
        </span>
        <Transition name="label-fade">
          <span v-if="!effectiveCollapsed" class="nav-label">项目现金流</span>
        </Transition>
      </router-link>

      <router-link v-if="auth.canPage('caiwu_data')" to="/caiwu/data" class="nav-item"
        :class="{ active: route.path === '/caiwu/data' }"
        :title="effectiveCollapsed ? '数据加工' : undefined"
        @click="onNavClick">
        <span class="nav-icon">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v6c0 1.66 4 3 9 3s9-1.34 9-3V5M3 11v6c0 1.66 4 3 9 3s9-1.34 9-3v-6"/>
          </svg>
        </span>
        <Transition name="label-fade">
          <span v-if="!effectiveCollapsed" class="nav-label">数据加工</span>
        </Transition>
      </router-link>

      <!-- ── 系统管理 section ───────────────────── -->
      <div v-if="auth.isSuperAdmin" class="nav-section-label">
        <Transition name="label-fade">
          <span v-if="!effectiveCollapsed" class="nav-sl-text">系统管理</span>
        </Transition>
        <span class="nav-sl-line"></span>
      </div>

      <router-link v-if="auth.isSuperAdmin" to="/caiwu/settings" class="nav-item"
        :class="{ active: route.path === '/caiwu/settings' }"
        :title="effectiveCollapsed ? '科目设置' : undefined"
        @click="onNavClick">
        <span class="nav-icon">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 11-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 11-2.83-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 112.83-2.83l.06.06a1.65 1.65 0 001.82.33H9a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 112.83 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z"/>
          </svg>
        </span>
        <Transition name="label-fade">
          <span v-if="!effectiveCollapsed" class="nav-label">科目设置</span>
        </Transition>
      </router-link>

      <router-link v-if="auth.isSuperAdmin" to="/users" class="nav-item"
        :class="{ active: route.path === '/users' }"
        :title="effectiveCollapsed ? '用户管理' : undefined"
        @click="onNavClick">
        <span class="nav-icon">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/>
            <circle cx="9" cy="7" r="4"/>
            <path d="M23 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75"/>
          </svg>
        </span>
        <Transition name="label-fade">
          <span v-if="!effectiveCollapsed" class="nav-label">用户管理</span>
        </Transition>
      </router-link>

      <router-link v-if="auth.isSuperAdmin" to="/permissions" class="nav-item"
        :class="{ active: route.path === '/permissions' }"
        :title="effectiveCollapsed ? '权限配置' : undefined"
        @click="onNavClick">
        <span class="nav-icon">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
            <path d="M9 12l2 2 4-4"/>
          </svg>
        </span>
        <Transition name="label-fade">
          <span v-if="!effectiveCollapsed" class="nav-label">权限配置</span>
        </Transition>
      </router-link>

      <router-link v-if="auth.isSuperAdmin" to="/audit" class="nav-item"
        :class="{ active: route.path === '/audit' }"
        :title="effectiveCollapsed ? '审计日志' : undefined"
        @click="onNavClick">
        <span class="nav-icon">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/>
            <path d="M14 2v6h6"/>
            <path d="M16 13H8M16 17H8M10 9H8"/>
          </svg>
        </span>
        <Transition name="label-fade">
          <span v-if="!effectiveCollapsed" class="nav-label">审计日志</span>
        </Transition>
      </router-link>

      <router-link v-if="auth.canDelete" to="/trash" class="nav-item"
        :class="{ active: route.path === '/trash' }"
        :title="effectiveCollapsed ? '回收站' : undefined"
        @click="onNavClick">
        <span class="nav-icon">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4h6v2"/>
          </svg>
        </span>
        <Transition name="label-fade">
          <span v-if="!effectiveCollapsed" class="nav-label">回收站</span>
        </Transition>
      </router-link>
    </div>

    <!-- Footer -->
    <div class="sidebar-footer dept-pop-anchor">
      <template v-if="!effectiveCollapsed">
        <div class="user-info" :class="{ 'user-info-clickable': hasDeptChoice, 'is-scoped': auth.isDeptScoped }"
             @click="openDeptPop" :title="hasDeptChoice ? '点击切换管辖部门范围' : ''">
          <div class="user-avatar">{{ auth.user?.name?.[0] || '?' }}</div>
          <div class="user-meta">
            <div class="user-name">{{ auth.user?.name }}</div>
            <div class="user-role-wrap">
              <template v-if="auth.user?.role === 'super_admin'">
                <span class="badge badge-super_admin" style="font-size:10px;padding:2px 7px">超级管理员</span>
              </template>
              <template v-else>
                <span v-if="auth.user?.job_title" style="font-size:11px;color:#b09080;font-weight:600">
                  {{ JOB_LABELS[auth.user?.job_title] || '' }}
                </span>
              </template>
            </div>
            <div v-if="hasDeptChoice" class="dept-scope-line" :class="{ 'is-scoped': auth.isDeptScoped }">
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
                <path d="M3 21h18M5 21V7l8-4v18M19 21V11l-6-4"/>
              </svg>
              <span>{{ scopeLabel }}</span>
              <svg class="dept-caret" width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"><path d="M6 9l6 6 6-6"/></svg>
            </div>
          </div>
        </div>
        <div class="footer-actions">
          <button class="footer-btn pwd-btn" title="修改密码" @click="showChangePwd = true">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0110 0v4"/>
            </svg>
            改密
          </button>
          <button class="footer-btn logout-btn" @click="logout">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9"/>
            </svg>
            退出
          </button>
          <button class="footer-btn density-btn" @click="cycleDensity"
            :title="`表格密度：${DENSITY_LABELS[density]}（点击切换）`">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round">
              <line x1="3" y1="6" x2="21" y2="6"/>
              <line x1="3" y1="12" x2="21" y2="12"/>
              <line x1="3" y1="18" x2="21" y2="18"/>
            </svg>
          </button>
          <button class="footer-btn perf-btn" :class="{ on: perfLite }" @click="togglePerfLite"
            :title="perfLite ? '性能模式已开启（点击恢复完整视觉）' : '滚动卡顿？点击开启性能模式'">
            ⚡
          </button>
        </div>
      </template>
      <template v-else>
        <div class="user-avatar-sm" :class="{ 'is-scoped': auth.isDeptScoped, 'clickable': hasDeptChoice }"
             :title="hasDeptChoice ? scopeLabel + '（点击切换）' : ''" @click="openDeptPop">
          {{ auth.user?.name?.[0] || '?' }}
          <span v-if="auth.isDeptScoped" class="scope-dot"></span>
        </div>
        <button class="footer-btn logout-btn icon-only" @click="logout" title="退出登录">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9"/>
          </svg>
        </button>
      </template>

      <!-- Department picker popover -->
      <Transition name="deptpop-fade">
        <div v-if="deptPopOpen" class="dept-pop" :class="{ 'pop-collapsed': effectiveCollapsed }">
          <div class="dept-pop-head">
            <div class="dept-pop-title">管辖部门</div>
            <div class="dept-pop-tools">
              <button class="dept-mini-btn" @click="selectAll">全选</button>
              <button class="dept-mini-btn" @click="clearAll">清空</button>
            </div>
          </div>
          <div class="dept-pop-hint">勾选本次会话关心的部门，整个系统数据将按此范围联动过滤</div>
          <ul class="dept-pop-list">
            <li v-for="d in auth.allowedDepts" :key="d" class="dept-pop-item" :class="{ checked: draftDepts.includes(d) }" @click="toggleDraft(d)">
              <span class="dept-check">
                <svg v-if="draftDepts.includes(d)" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
              </span>
              <span class="dept-name">{{ d }}</span>
            </li>
          </ul>
          <div class="dept-pop-foot">
            <span class="dept-pop-count">已选 <b>{{ draftDepts.length }}</b> / {{ auth.allowedDepts.length }}</span>
            <div style="display:flex;gap:6px">
              <button class="dept-mini-btn ghost" @click="closeDeptPop">取消</button>
              <button class="dept-mini-btn primary" @click="applyDepts">应用</button>
            </div>
          </div>
        </div>
      </Transition>
    </div>

    <!-- Collapse toggle -->
    <button class="collapse-btn" @click="toggleCollapse" :title="collapsed ? '展开导航' : '收起导航'">
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
        <path v-if="!effectiveCollapsed" d="M15 18l-6-6 6-6"/>
        <path v-else d="M9 18l6-6-6-6"/>
      </svg>
    </button>
    <ChangePasswordModal v-if="showChangePwd" @close="onChangePwdClose" />
    <Transition name="pwd-ok-fade">
      <div v-if="pwdChangedOk" class="pwd-ok-toast">✓ 密码已修改</div>
    </Transition>
  </nav>
</template>

<style scoped>
/* ── toast ── */
.pwd-ok-toast {
  position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%);
  background: #2e7d32; color: #fff; padding: 8px 20px;
  border-radius: 20px; font-size: 13px; z-index: 9999; pointer-events: none;
  box-shadow: 0 4px 16px rgba(0,0,0,0.25);
}
.pwd-ok-fade-enter-active, .pwd-ok-fade-leave-active { transition: opacity 0.35s; }
.pwd-ok-fade-enter-from, .pwd-ok-fade-leave-to { opacity: 0; }

/* ═══════════════════════════════════════════════════
   SIDEBAR SHELL
═══════════════════════════════════════════════════ */
.sidebar {
  width: var(--nav-w);
  background: linear-gradient(170deg, rgba(26,12,4,0.92) 0%, rgba(38,20,10,0.90) 100%);
  backdrop-filter: blur(28px) saturate(200%);
  -webkit-backdrop-filter: blur(28px) saturate(200%);
  border-right: 1px solid rgba(255,255,255,0.055);
  color: #e8d4c4;
  display: flex; flex-direction: column;
  position: fixed; top: 0; left: 0; bottom: 0;
  z-index: 100;
  transition: width 0.38s cubic-bezier(0.45, 0, 0.15, 1);
  will-change: width;
  overflow: hidden;
  box-shadow: 3px 0 28px rgba(8,3,1,0.32), inset -1px 0 0 rgba(255,255,255,0.03);
}
.sidebar.collapsed { width: var(--nav-w-collapsed); }

/* ═══════════════════════════════════════════════════
   BRAND
═══════════════════════════════════════════════════ */
.sidebar-brand {
  padding: 20px 14px 16px;
  display: flex; align-items: center; gap: 11px;
  min-height: 64px; flex-shrink: 0;
  position: relative;
}
.sidebar-brand::after {
  content: '';
  position: absolute; bottom: 0; left: 14px; right: 14px; height: 1px;
  background: linear-gradient(90deg, transparent, rgba(201,99,66,0.28) 40%, rgba(201,99,66,0.14) 70%, transparent);
}
.brand-mark {
  width: 36px; height: 36px; border-radius: 10px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  box-shadow: 0 4px 18px rgba(201,99,66,0.42), inset 0 0 0 1px rgba(255,255,255,0.12);
}
.brand-name {
  font-size: 15px; font-weight: 700; color: #fff;
  white-space: nowrap; letter-spacing: -0.01em;
}

/* ═══════════════════════════════════════════════════
   NAV LINKS
═══════════════════════════════════════════════════ */
.nav-links {
  flex: 1; padding: 10px 8px 8px;
  display: flex; flex-direction: column; gap: 1px;
  overflow-y: auto; overflow-x: hidden;
}

/* Section labels */
.nav-section-label {
  margin-top: 10px; padding: 0 4px 6px;
  display: flex; align-items: center; gap: 8px;
  overflow: hidden;
}
.nav-sl-text {
  font-size: 10px; font-weight: 700; letter-spacing: 0.1em;
  color: rgba(196,168,152,0.38); text-transform: uppercase;
  white-space: nowrap; flex-shrink: 0;
}
.nav-sl-line {
  flex: 1; height: 1px; min-width: 4px;
  background: linear-gradient(90deg, rgba(201,99,66,0.2), rgba(201,99,66,0.05) 60%, transparent);
}
.sidebar.collapsed .nav-sl-line { background: rgba(255,255,255,0.07); }

/* Nav items */
.nav-item {
  display: flex; align-items: center;
  padding: 0; height: 42px;
  border-radius: 9px;
  color: rgba(200,174,158,0.7);
  font-size: 13.5px; font-weight: 500;
  transition: background 0.17s, color 0.17s, transform 0.17s;
  text-decoration: none;
  white-space: nowrap; overflow: hidden;
  position: relative;
}
.nav-item:hover {
  background: rgba(255,255,255,0.062);
  color: rgba(255,248,244,0.9);
  transform: translateX(1px);
}
.nav-item.active {
  background: rgba(201,99,66,0.15);
  color: #fff;
  box-shadow: 0 2px 14px rgba(201,99,66,0.12);
}
.nav-item.active::before {
  content: '';
  position: absolute; left: 0; top: 18%; bottom: 18%;
  width: 3.5px; border-radius: 0 3px 3px 0;
  background: linear-gradient(180deg, #f09870, #c96342);
  box-shadow: 0 0 8px rgba(201,99,66,0.48);
}

.nav-icon {
  flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  width: 42px; height: 42px;
  transition: color 0.17s;
}
.nav-item.active .nav-icon { color: #e89570; }
.nav-item:hover:not(.active) .nav-icon { color: rgba(255,230,210,0.85); }

.nav-label { flex: 1; padding-left: 2px; }

/* ═══════════════════════════════════════════════════
   FOOTER
═══════════════════════════════════════════════════ */
.sidebar-footer {
  padding: 12px 10px 18px;
  border-top: 1px solid transparent;
  display: flex; flex-direction: column; gap: 9px;
  flex-shrink: 0; position: relative;
}
.sidebar-footer::before {
  content: '';
  position: absolute; top: 0; left: 10px; right: 10px; height: 1px;
  background: linear-gradient(90deg, transparent, rgba(201,99,66,0.22) 40%, rgba(201,99,66,0.08) 70%, transparent);
}

.user-info { display: flex; align-items: center; gap: 9px; overflow: hidden; }
.user-avatar {
  width: 34px; height: 34px; border-radius: 9px; flex-shrink: 0;
  background: linear-gradient(135deg, #d4714e, #a84e32);
  display: flex; align-items: center; justify-content: center;
  color: #fff; font-weight: 700; font-size: 14px;
  box-shadow: 0 2px 10px rgba(201,99,66,0.26), inset 0 0 0 1px rgba(255,255,255,0.1);
}
.user-avatar-sm {
  width: 34px; height: 34px; border-radius: 9px; margin: 0 auto;
  background: linear-gradient(135deg, #d4714e, #a84e32);
  display: flex; align-items: center; justify-content: center;
  color: #fff; font-weight: 700; font-size: 14px;
  position: relative;
}
.user-meta { overflow: hidden; }
.user-name { font-weight: 600; color: #fff; font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.user-role-wrap { display: flex; align-items: center; margin-top: 2px; overflow: hidden; }

/* Footer action row */
.footer-actions { display: flex; gap: 5px; }
.footer-btn {
  display: flex; align-items: center; justify-content: center; gap: 5px;
  flex: 1; padding: 7px 6px; border-radius: 8px;
  background: rgba(255,255,255,0.052); border: 1px solid rgba(255,255,255,0.068);
  color: rgba(200,172,156,0.72); font-size: 12px;
  transition: all 0.16s; white-space: nowrap; cursor: pointer;
}
.footer-btn.logout-btn:hover { background: rgba(220,70,50,0.16); color: #ff8a7a; border-color: rgba(220,70,50,0.24); }
.footer-btn.pwd-btn:hover { background: rgba(255,255,255,0.09); color: rgba(255,248,244,0.9); border-color: rgba(255,255,255,0.12); }
.footer-btn.density-btn { flex: none; width: 30px; padding: 6px; }
.footer-btn.density-btn:hover { background: rgba(255,255,255,0.09); color: rgba(255,248,244,0.9); border-color: rgba(255,255,255,0.12); }
.footer-btn.perf-btn { flex: none; width: 30px; padding: 6px; font-size: 13px; }
.footer-btn.perf-btn.on { border-color: #ffd54f; color: #ffd54f; background: rgba(255,213,79,0.1); }
.footer-btn.icon-only { width: 34px; flex: none; margin: 0 auto; padding: 8px; }

/* Dept trigger */
.user-info.user-info-clickable {
  cursor: pointer; border-radius: 9px; padding: 4px 5px; margin: -4px -5px;
  transition: background 0.16s;
}
.user-info.user-info-clickable:hover { background: rgba(255,255,255,0.044); }
.user-info.is-scoped .user-avatar { box-shadow: 0 0 0 2px rgba(245,127,23,0.52), 0 2px 10px rgba(201,99,66,0.26); }
.dept-scope-line {
  display: flex; align-items: center; gap: 4px;
  margin-top: 3px; font-size: 11px; color: rgba(196,168,152,0.65);
  letter-spacing: 0.02em; white-space: nowrap;
}
.dept-scope-line.is-scoped { color: #f5b977; font-weight: 600; }
.dept-scope-line .dept-caret { opacity: 0.48; }

.user-avatar-sm.clickable { cursor: pointer; }
.user-avatar-sm.is-scoped { box-shadow: 0 0 0 2px rgba(245,127,23,0.5); }
.user-avatar-sm .scope-dot {
  position: absolute; top: -2px; right: -2px; width: 8px; height: 8px;
  border-radius: 50%; background: #f57f17; border: 1.5px solid #1e0d05;
}

/* ═══════════════════════════════════════════════════
   DEPT PICKER POPOVER
═══════════════════════════════════════════════════ */
.dept-pop {
  position: absolute; left: 10px; right: 10px; bottom: calc(100% - 6px);
  background: rgba(26,12,4,0.97);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 13px; padding: 12px 12px 10px;
  box-shadow: 0 -10px 32px rgba(8,3,1,0.52);
  backdrop-filter: blur(24px);
  z-index: 200;
}
.dept-pop.pop-collapsed { left: calc(100% + 8px); right: auto; bottom: 14px; width: 240px; }
.dept-pop-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 4px; }
.dept-pop-title { font-size: 13px; font-weight: 700; color: #fff; }
.dept-pop-tools { display: flex; gap: 4px; }
.dept-pop-hint { font-size: 11px; color: rgba(196,168,152,0.52); line-height: 1.5; margin-bottom: 8px; }
.dept-pop-list { list-style: none; margin: 0; padding: 0; max-height: 250px; overflow-y: auto; }
.dept-pop-item {
  display: flex; align-items: center; gap: 8px;
  padding: 6px 8px; border-radius: 7px;
  font-size: 12.5px; color: #e8d4c4; cursor: pointer;
  transition: background 0.12s;
}
.dept-pop-item:hover { background: rgba(255,255,255,0.044); }
.dept-pop-item.checked { background: rgba(245,127,23,0.12); color: #fff; }
.dept-check {
  width: 15px; height: 15px; border-radius: 4px;
  border: 1.5px solid rgba(196,168,152,0.32);
  display: flex; align-items: center; justify-content: center; flex-shrink: 0;
}
.dept-pop-item.checked .dept-check { background: #c96342; border-color: #c96342; color: #fff; }
.dept-pop-foot {
  display: flex; align-items: center; justify-content: space-between; gap: 8px;
  padding-top: 7px; margin-top: 5px;
  border-top: 1px solid rgba(255,255,255,0.06);
}
.dept-pop-count { font-size: 11.5px; color: rgba(196,168,152,0.58); }
.dept-pop-count b { color: #f5b977; font-weight: 700; }
.dept-mini-btn {
  padding: 4px 9px; border-radius: 7px;
  background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.07);
  color: rgba(196,168,152,0.85); font-size: 11.5px; cursor: pointer;
  transition: all 0.13s;
}
.dept-mini-btn:hover { background: rgba(255,255,255,0.1); color: #fff; }
.dept-mini-btn.primary { background: #c96342; color: #fff; border-color: #c96342; }
.dept-mini-btn.primary:hover { background: #d97252; }
.dept-mini-btn.ghost { background: transparent; }

.deptpop-fade-enter-active, .deptpop-fade-leave-active { transition: opacity 0.15s, transform 0.15s; }
.deptpop-fade-enter-from, .deptpop-fade-leave-to { opacity: 0; transform: translateY(5px); }

/* ═══════════════════════════════════════════════════
   COLLAPSE BUTTON
═══════════════════════════════════════════════════ */
.collapse-btn {
  position: absolute; top: 50%; right: -12px;
  transform: translateY(-50%);
  width: 24px; height: 24px; border-radius: 50%;
  background: rgba(34,16,8,0.96);
  border: 1px solid rgba(255,255,255,0.13);
  color: rgba(200,172,156,0.6);
  display: flex; align-items: center; justify-content: center;
  transition: all 0.18s; z-index: 110; cursor: pointer;
  box-shadow: 2px 0 12px rgba(8,3,1,0.26), 0 0 0 3px rgba(26,12,4,0.5);
}
.collapse-btn:hover {
  background: var(--primary); color: #fff; border-color: var(--primary);
  box-shadow: 2px 0 14px rgba(201,99,66,0.3);
}

/* ═══════════════════════════════════════════════════
   TRANSITIONS
═══════════════════════════════════════════════════ */
.label-fade-enter-active { transition: opacity 0.22s 0.12s, transform 0.22s 0.12s; }
.label-fade-leave-active { transition: opacity 0.16s, transform 0.16s; }
.label-fade-enter-from { opacity: 0; transform: translateX(-8px); }
.label-fade-leave-to   { opacity: 0; transform: translateX(-8px); }

/* ═══════════════════════════════════════════════════
   MOBILE OFF-CANVAS DRAWER
═══════════════════════════════════════════════════ */
@media (max-width: 768px) {
  .sidebar {
    width: var(--nav-w);
    transform: translateX(-100%);
    transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    z-index: 300;
  }
  .sidebar.collapsed { width: var(--nav-w); }
  .sidebar.mobile-open { transform: translateX(0); }
  .collapse-btn { display: none; }
}
</style>
