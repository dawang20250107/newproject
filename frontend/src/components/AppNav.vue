<script setup>
import { computed, ref, watch, onBeforeUnmount } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '../stores/auth.js'
import { ROLE_LABELS, JOB_LABELS } from '../constants.js'

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

function logout() {
  emit('close-mobile')
  auth.logout()
  router.push('/login')
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
      <router-link v-if="auth.canPage('dashboard')" to="/dashboard" class="nav-item" :class="{ active: route.path === '/dashboard' }" @click="onNavClick">
        <span class="nav-icon">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/>
            <rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>
          </svg>
        </span>
        <Transition name="label-fade">
          <span v-if="!effectiveCollapsed" class="nav-label">今日工作台</span>
        </Transition>
        <Transition name="label-fade">
          <span v-if="!effectiveCollapsed" class="nav-arrow">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M9 18l6-6-6-6"/></svg>
          </span>
        </Transition>
      </router-link>

      <router-link v-if="auth.canPage('payments')" to="/payments" class="nav-item" :class="{ active: route.path === '/payments' }" @click="onNavClick">
        <span class="nav-icon">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8l-6-6z"/>
            <path d="M14 2v6h6M8 13h8M8 17h5"/>
          </svg>
        </span>
        <Transition name="label-fade">
          <span v-if="!effectiveCollapsed" class="nav-label">付款台账</span>
        </Transition>
        <Transition name="label-fade">
          <span v-if="!effectiveCollapsed" class="nav-arrow">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M9 18l6-6-6-6"/></svg>
          </span>
        </Transition>
      </router-link>
      <router-link v-if="auth.canPage('approval_records')" to="/approvals" class="nav-item" :class="{ active: route.path === '/approvals' }" @click="onNavClick">
        <span class="nav-icon">🧾</span>
        <Transition name="label-fade"><span v-if="!effectiveCollapsed" class="nav-label">审批记录</span></Transition>
        <Transition name="label-fade"><span v-if="!effectiveCollapsed" class="nav-arrow"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M9 18l6-6-6-6"/></svg></span></Transition>
      </router-link>

      <router-link v-if="auth.canPage('stats') && auth.canView('total_amount')" to="/stats" class="nav-item" :class="{ active: route.path === '/stats' }" @click="onNavClick">
        <span class="nav-icon">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/>
            <line x1="6" y1="20" x2="6" y2="14"/><line x1="2" y1="20" x2="22" y2="20"/>
          </svg>
        </span>
        <Transition name="label-fade">
          <span v-if="!effectiveCollapsed" class="nav-label">月度统计</span>
        </Transition>
        <Transition name="label-fade">
          <span v-if="!effectiveCollapsed" class="nav-arrow">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M9 18l6-6-6-6"/></svg>
          </span>
        </Transition>
      </router-link>

      <!-- ── 应收账款 section ───────────────────── -->
      <div v-if="auth.canPage('ar_projects') || auth.canPage('ar_records') || auth.canPage('ar_analytics') || auth.canPage('ar_cashflow') || auth.canPage('ar_budget')"
           class="nav-section-label">
        <span style="display:block;width:100%;height:1px;background:rgba(255,255,255,0.1);margin:4px 0"></span>
      </div>

      <router-link v-if="auth.canPage('ar_projects')" to="/ar/projects" class="nav-item" :class="{ active: route.path === '/ar/projects' }" @click="onNavClick">
        <span class="nav-icon">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z"/>
          </svg>
        </span>
        <Transition name="label-fade"><span v-if="!effectiveCollapsed" class="nav-label">项目台账</span></Transition>
        <Transition name="label-fade"><span v-if="!effectiveCollapsed" class="nav-arrow"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M9 18l6-6-6-6"/></svg></span></Transition>
      </router-link>

      <router-link v-if="auth.canPage('ar_projects')" to="/ar/customers" class="nav-item" :class="{ active: route.path === '/ar/customers' }" @click="onNavClick">
        <span class="nav-icon">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/>
            <circle cx="9" cy="7" r="4"/>
            <path d="M23 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75"/>
          </svg>
        </span>
        <Transition name="label-fade"><span v-if="!effectiveCollapsed" class="nav-label">客户管理</span></Transition>
        <Transition name="label-fade"><span v-if="!effectiveCollapsed" class="nav-arrow"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M9 18l6-6-6-6"/></svg></span></Transition>
      </router-link>

      <router-link v-if="auth.canPage('ar_records')" to="/ar/records" class="nav-item" :class="{ active: route.path === '/ar/records' }" @click="onNavClick">
        <span class="nav-icon">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/>
          </svg>
        </span>
        <Transition name="label-fade"><span v-if="!effectiveCollapsed" class="nav-label">应收明细</span></Transition>
        <Transition name="label-fade"><span v-if="!effectiveCollapsed" class="nav-arrow"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M9 18l6-6-6-6"/></svg></span></Transition>
      </router-link>

      <router-link v-if="auth.canPage('ar_advance')" to="/ar/advances" class="nav-item" :class="{ active: route.path === '/ar/advances' }" @click="onNavClick">
        <span class="nav-icon">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 1v22"/><path d="M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6"/>
          </svg>
        </span>
        <Transition name="label-fade"><span v-if="!effectiveCollapsed" class="nav-label">预收预付</span></Transition>
        <Transition name="label-fade"><span v-if="!effectiveCollapsed" class="nav-arrow"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M9 18l6-6-6-6"/></svg></span></Transition>
      </router-link>

      <router-link v-if="auth.canPage('ar_budget')" to="/ar/budget" class="nav-item" :class="{ active: route.path === '/ar/budget' }" @click="onNavClick">
        <span class="nav-icon">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M3 3h18v4H3zM3 10h18v4H3zM3 17h18v4H3z"/>
          </svg>
        </span>
        <Transition name="label-fade"><span v-if="!effectiveCollapsed" class="nav-label">预算管理</span></Transition>
        <Transition name="label-fade"><span v-if="!effectiveCollapsed" class="nav-arrow"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M9 18l6-6-6-6"/></svg></span></Transition>
      </router-link>

      <!-- ── 财务分析 section ───────────────────── -->
      <div v-if="auth.canPage('caiwu_report') || auth.canPage('caiwu_data') || auth.canPage('caiwu_charts') || auth.canPage('caiwu_metrics') || auth.canPage('caiwu_cockpit') || auth.isSuperAdmin"
           class="nav-section-label">
        <span style="display:block;width:100%;height:1px;background:rgba(255,255,255,0.1);margin:4px 0"></span>
      </div>

      <router-link v-if="auth.canPage('caiwu_cockpit')" to="/caiwu/cockpit" class="nav-item" :class="{ active: route.path === '/caiwu/cockpit' }" @click="onNavClick">
        <span class="nav-icon">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <rect x="3" y="3" width="7" height="9"/><rect x="14" y="3" width="7" height="5"/><rect x="14" y="12" width="7" height="9"/><rect x="3" y="16" width="7" height="5"/>
          </svg>
        </span>
        <Transition name="label-fade"><span v-if="!effectiveCollapsed" class="nav-label">财务驾驶舱</span></Transition>
        <Transition name="label-fade"><span v-if="!effectiveCollapsed" class="nav-arrow"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M9 18l6-6-6-6"/></svg></span></Transition>
      </router-link>

      <router-link v-if="auth.canPage('caiwu_cockpit')" to="/caiwu/knowledge" class="nav-item" :class="{ active: route.path === '/caiwu/knowledge' }" @click="onNavClick">
        <span class="nav-icon">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>
          </svg>
        </span>
        <Transition name="label-fade"><span v-if="!effectiveCollapsed" class="nav-label">经营知识库</span></Transition>
        <Transition name="label-fade"><span v-if="!effectiveCollapsed" class="nav-arrow"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M9 18l6-6-6-6"/></svg></span></Transition>
      </router-link>

      <router-link v-if="auth.canPage('caiwu_metrics')" to="/caiwu/metrics" class="nav-item" :class="{ active: route.path === '/caiwu/metrics' }" @click="onNavClick">
        <span class="nav-icon">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M22 12h-4l-3 9L9 3l-3 9H2"/>
          </svg>
        </span>
        <Transition name="label-fade"><span v-if="!effectiveCollapsed" class="nav-label">指标管理</span></Transition>
        <Transition name="label-fade"><span v-if="!effectiveCollapsed" class="nav-arrow"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M9 18l6-6-6-6"/></svg></span></Transition>
      </router-link>

      <router-link v-if="auth.canPage('caiwu_report')" to="/caiwu/report" class="nav-item" :class="{ active: route.path === '/caiwu/report' }" @click="onNavClick">
        <span class="nav-icon">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><path d="M14 2v6h6M9 13l2 2 4-4"/>
          </svg>
        </span>
        <Transition name="label-fade"><span v-if="!effectiveCollapsed" class="nav-label">财务报表</span></Transition>
        <Transition name="label-fade"><span v-if="!effectiveCollapsed" class="nav-arrow"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M9 18l6-6-6-6"/></svg></span></Transition>
      </router-link>

      <router-link v-if="auth.canPage('caiwu_charts')" to="/caiwu/project-margin" class="nav-item" :class="{ active: route.path === '/caiwu/project-margin' }" @click="onNavClick">
        <span class="nav-icon">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M3 3v18h18"/><rect x="7" y="10" width="3" height="7"/><rect x="12" y="6" width="3" height="11"/><rect x="17" y="13" width="3" height="4"/>
          </svg>
        </span>
        <Transition name="label-fade"><span v-if="!effectiveCollapsed" class="nav-label">项目毛利</span></Transition>
        <Transition name="label-fade"><span v-if="!effectiveCollapsed" class="nav-arrow"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M9 18l6-6-6-6"/></svg></span></Transition>
      </router-link>

      <router-link v-if="auth.canPage('caiwu_data')" to="/caiwu/data" class="nav-item" :class="{ active: route.path === '/caiwu/data' }" @click="onNavClick">
        <span class="nav-icon">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v6c0 1.66 4 3 9 3s9-1.34 9-3V5M3 11v6c0 1.66 4 3 9 3s9-1.34 9-3v-6"/>
          </svg>
        </span>
        <Transition name="label-fade"><span v-if="!effectiveCollapsed" class="nav-label">数据加工</span></Transition>
        <Transition name="label-fade"><span v-if="!effectiveCollapsed" class="nav-arrow"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M9 18l6-6-6-6"/></svg></span></Transition>
      </router-link>

      <router-link v-if="auth.isSuperAdmin" to="/caiwu/settings" class="nav-item" :class="{ active: route.path === '/caiwu/settings' }" @click="onNavClick">
        <span class="nav-icon">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 11-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 11-2.83-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 112.83-2.83l.06.06a1.65 1.65 0 001.82.33H9a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 112.83 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z"/>
          </svg>
        </span>
        <Transition name="label-fade"><span v-if="!effectiveCollapsed" class="nav-label">科目设置</span></Transition>
        <Transition name="label-fade"><span v-if="!effectiveCollapsed" class="nav-arrow"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M9 18l6-6-6-6"/></svg></span></Transition>
      </router-link>

      <router-link v-if="auth.isSuperAdmin" to="/users" class="nav-item" :class="{ active: route.path === '/users' }" @click="onNavClick">
        <span class="nav-icon">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/>
            <circle cx="9" cy="7" r="4"/>
            <path d="M23 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75"/>
          </svg>
        </span>
        <Transition name="label-fade">
          <span v-if="!effectiveCollapsed" class="nav-label">用户管理</span>
        </Transition>
        <Transition name="label-fade">
          <span v-if="!effectiveCollapsed" class="nav-arrow">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M9 18l6-6-6-6"/></svg>
          </span>
        </Transition>
      </router-link>

      <router-link v-if="auth.isSuperAdmin" to="/permissions" class="nav-item" :class="{ active: route.path === '/permissions' }" @click="onNavClick">
        <span class="nav-icon">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
            <path d="M9 12l2 2 4-4"/>
          </svg>
        </span>
        <Transition name="label-fade">
          <span v-if="!effectiveCollapsed" class="nav-label">权限配置</span>
        </Transition>
        <Transition name="label-fade">
          <span v-if="!effectiveCollapsed" class="nav-arrow">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M9 18l6-6-6-6"/></svg>
          </span>
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
              <!-- super_admin: show role badge -->
              <template v-if="auth.user?.role === 'super_admin'">
                <span class="badge badge-super_admin" style="font-size:10px;padding:2px 7px">超级管理员</span>
              </template>
              <!-- others: address by job title, not generic role name -->
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
        <button class="logout-btn" @click="logout">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9"/>
          </svg>
          退出
        </button>
      </template>
      <template v-else>
        <div class="user-avatar-sm" :class="{ 'is-scoped': auth.isDeptScoped, 'clickable': hasDeptChoice }"
             :title="hasDeptChoice ? scopeLabel + '（点击切换）' : ''" @click="openDeptPop">
          {{ auth.user?.name?.[0] || '?' }}
          <span v-if="auth.isDeptScoped" class="scope-dot"></span>
        </div>
        <button class="logout-btn icon-only" @click="logout" title="退出登录">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
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
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
        <path v-if="!effectiveCollapsed" d="M15 18l-6-6 6-6"/>
        <path v-else d="M9 18l6-6-6-6"/>
      </svg>
    </button>
  </nav>
</template>

<style scoped>
.sidebar {
  width: var(--nav-w);
  background: rgba(36, 18, 10, 0.82);
  backdrop-filter: blur(24px) saturate(180%);
  -webkit-backdrop-filter: blur(24px) saturate(180%);
  border-right: 1px solid rgba(255, 255, 255, 0.07);
  color: #e8d4c4;
  display: flex;
  flex-direction: column;
  position: fixed;
  top: 0; left: 0; bottom: 0;
  z-index: 100;
  transition: width 0.46s cubic-bezier(0.45, 0, 0.15, 1);
  will-change: width;
  overflow: hidden;
  box-shadow: 4px 0 32px rgba(20, 8, 4, 0.22);
}
.sidebar.collapsed { width: var(--nav-w-collapsed); }

.sidebar-brand {
  padding: 22px 15px 18px;
  display: flex; align-items: center; gap: 10px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.07);
  min-height: 68px; flex-shrink: 0;
}
.brand-mark {
  width: 36px; height: 36px; border-radius: 10px;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
  box-shadow: 0 4px 16px rgba(201, 99, 66, 0.35);
}
.brand-name { font-size: 15px; font-weight: 700; color: #fff; white-space: nowrap; }

.nav-links { flex: 1; padding: 12px 9px; display: flex; flex-direction: column; gap: 2px; overflow-y: auto; overflow-x: hidden; }

.nav-section-label {
  margin-top: 8px; padding: 4px 10px 2px;
  font-size: 10px; font-weight: 700; letter-spacing: 0.08em;
  color: rgba(196,168,152,0.38); text-transform: uppercase;
  white-space: nowrap; overflow: hidden;
}

.nav-item {
  display: flex; align-items: center; gap: 0;
  padding: 0; height: 44px;
  border-radius: 10px;
  color: rgba(196, 168, 152, 0.75);
  font-size: 13.5px; font-weight: 500;
  transition: all 0.2s ease;
  text-decoration: none;
  white-space: nowrap;
  overflow: hidden;
  position: relative;
}
.nav-item:hover { background: rgba(255, 255, 255, 0.07); color: #fff; }
.nav-item.active {
  background: rgba(201, 99, 66, 0.2);
  color: #fff;
  box-shadow: 0 0 20px rgba(201, 99, 66, 0.18), inset 0 0 10px rgba(201, 99, 66, 0.06);
}
.nav-item.active::before {
  content: '';
  position: absolute; left: 0; top: 20%; bottom: 20%;
  width: 3px; border-radius: 0 2px 2px 0;
  background: linear-gradient(180deg, #e8855a, #c96342);
}

.nav-icon {
  flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  width: 46px; height: 44px;
}
.nav-item.active .nav-icon { color: #e8a070; }

.nav-label { flex: 1; padding-left: 2px; }
.nav-arrow { padding-right: 12px; opacity: 0.35; transition: transform 0.2s, opacity 0.2s; }
.nav-item.active .nav-arrow, .nav-item:hover .nav-arrow { opacity: 0.6; transform: translateX(2px); }

.sidebar-footer {
  padding: 14px 11px 20px;
  border-top: 1px solid rgba(255, 255, 255, 0.07);
  display: flex; flex-direction: column; gap: 10px; flex-shrink: 0;
}
.user-info { display: flex; align-items: center; gap: 9px; overflow: hidden; }
.user-avatar {
  width: 36px; height: 36px; border-radius: 10px; flex-shrink: 0;
  background: linear-gradient(135deg, #c96342, #a84e32);
  display: flex; align-items: center; justify-content: center;
  color: #fff; font-weight: 700; font-size: 15px;
  box-shadow: 0 2px 10px rgba(201,99,66,0.3);
}
.user-avatar-sm {
  width: 36px; height: 36px; border-radius: 10px; margin: 0 auto;
  background: linear-gradient(135deg, #c96342, #a84e32);
  display: flex; align-items: center; justify-content: center;
  color: #fff; font-weight: 700; font-size: 15px;
}
.user-meta { overflow: hidden; }
.user-name { font-weight: 600; color: #fff; font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.user-role-wrap { display: flex; align-items: center; flex-wrap: nowrap; margin-top: 3px; overflow: hidden; }

.logout-btn {
  display: flex; align-items: center; justify-content: center; gap: 7px;
  width: 100%; padding: 8px 10px; border-radius: 9px;
  background: rgba(255, 255, 255, 0.06); border: 1px solid rgba(255,255,255,0.08);
  color: rgba(196, 168, 152, 0.75); font-size: 13px;
  transition: all 0.2s; white-space: nowrap;
}
.logout-btn:hover { background: rgba(231, 76, 60, 0.18); color: #ff8a7a; border-color: rgba(231,76,60,0.28); }
.logout-btn.icon-only { width: 36px; margin: 0 auto; padding: 9px; }

/* ── Active-department picker ── */
.sidebar-footer { position: relative; }
.user-info.user-info-clickable {
  cursor: pointer; border-radius: 10px; padding: 4px 6px; margin: -4px -6px;
  transition: background 0.18s;
}
.user-info.user-info-clickable:hover { background: rgba(255,255,255,0.05); }
.user-info.is-scoped .user-avatar { box-shadow: 0 0 0 2px rgba(245,127,23,0.55), 0 2px 10px rgba(201,99,66,0.3); }
.dept-scope-line {
  display: flex; align-items: center; gap: 4px;
  margin-top: 4px; font-size: 11px; color: rgba(196,168,152,0.7);
  letter-spacing: 0.02em; white-space: nowrap;
}
.dept-scope-line.is-scoped { color: #f5b977; font-weight: 600; }
.dept-scope-line .dept-caret { opacity: 0.55; }

.user-avatar-sm.clickable { cursor: pointer; position: relative; }
.user-avatar-sm.is-scoped { box-shadow: 0 0 0 2px rgba(245,127,23,0.55); }
.user-avatar-sm .scope-dot {
  position: absolute; top: -2px; right: -2px; width: 8px; height: 8px;
  border-radius: 50%; background: #f57f17; border: 1.5px solid #2a140a;
}

.dept-pop {
  position: absolute; left: 11px; right: 11px; bottom: calc(100% - 8px);
  background: rgba(36, 18, 10, 0.96);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 12px;
  padding: 12px 12px 10px;
  box-shadow: 0 -8px 28px rgba(20,8,4,0.45);
  backdrop-filter: blur(20px);
  z-index: 200;
}
.dept-pop.pop-collapsed {
  left: calc(100% + 8px); right: auto; bottom: 14px;
  width: 240px;
}
.dept-pop-head {
  display: flex; align-items: center; justify-content: space-between; gap: 8px;
  margin-bottom: 4px;
}
.dept-pop-title { font-size: 13px; font-weight: 700; color: #fff; }
.dept-pop-tools { display: flex; gap: 4px; }
.dept-pop-hint {
  font-size: 11px; color: rgba(196,168,152,0.6); line-height: 1.5;
  margin-bottom: 8px;
}
.dept-pop-list {
  list-style: none; margin: 0; padding: 0;
  max-height: 250px; overflow-y: auto;
}
.dept-pop-item {
  display: flex; align-items: center; gap: 8px;
  padding: 7px 9px; border-radius: 8px;
  font-size: 12.5px; color: #e8d4c4; cursor: pointer;
  transition: background 0.14s;
}
.dept-pop-item:hover { background: rgba(255,255,255,0.05); }
.dept-pop-item.checked { background: rgba(245,127,23,0.12); color: #fff; }
.dept-check {
  width: 16px; height: 16px; border-radius: 4px;
  border: 1.5px solid rgba(196,168,152,0.4);
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.dept-pop-item.checked .dept-check {
  background: #c96342; border-color: #c96342; color: #fff;
}
.dept-pop-foot {
  display: flex; align-items: center; justify-content: space-between; gap: 8px;
  padding-top: 8px; margin-top: 6px;
  border-top: 1px solid rgba(255,255,255,0.07);
}
.dept-pop-count { font-size: 11.5px; color: rgba(196,168,152,0.65); }
.dept-pop-count b { color: #f5b977; font-weight: 700; }
.dept-mini-btn {
  padding: 4px 10px; border-radius: 7px;
  background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.08);
  color: rgba(196,168,152,0.85); font-size: 11.5px; cursor: pointer;
  transition: all 0.14s;
}
.dept-mini-btn:hover { background: rgba(255,255,255,0.1); color: #fff; }
.dept-mini-btn.primary { background: #c96342; color: #fff; border-color: #c96342; }
.dept-mini-btn.primary:hover { background: #d77252; }
.dept-mini-btn.ghost { background: transparent; }

.deptpop-fade-enter-active, .deptpop-fade-leave-active { transition: opacity 0.16s, transform 0.16s; }
.deptpop-fade-enter-from, .deptpop-fade-leave-to { opacity: 0; transform: translateY(4px); }

.collapse-btn {
  position: absolute; top: 50%; right: -11px;
  transform: translateY(-50%);
  width: 22px; height: 22px; border-radius: 50%;
  background: rgba(45, 24, 16, 0.92);
  border: 1px solid rgba(255,255,255,0.14);
  color: rgba(196, 168, 152, 0.7);
  display: flex; align-items: center; justify-content: center;
  transition: all 0.2s; z-index: 110;
  box-shadow: 2px 0 10px rgba(20,8,4,0.2);
}
.collapse-btn:hover { background: var(--primary); color: #fff; border-color: var(--primary); }

.label-fade-enter-active { transition: opacity 0.22s 0.14s, transform 0.22s 0.14s; }
.label-fade-leave-active { transition: opacity 0.18s, transform 0.18s; }
.label-fade-enter-from { opacity:0; transform:translateX(-6px); }
.label-fade-leave-to   { opacity:0; transform:translateX(-6px); }

/* ── mobile off-canvas drawer (kept scoped so it out-specifies base .sidebar) ── */
@media (max-width: 768px) {
  .sidebar {
    width: var(--nav-w);
    transform: translateX(-100%);
    transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    z-index: 300;
  }
  .sidebar.collapsed { width: var(--nav-w); }   /* always full width as a drawer */
  .sidebar.mobile-open { transform: translateX(0); }
  .collapse-btn { display: none; }              /* collapse toggle is desktop-only */
}
</style>
