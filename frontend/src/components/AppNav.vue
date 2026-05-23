<script setup>
import { computed } from 'vue'
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

</script>

<template>
  <nav :class="['sidebar', collapsed ? 'collapsed' : '', mobileOpen ? 'mobile-open' : '']"
    @mouseenter="emit('hover', true)" @mouseleave="emit('hover', false)">
    <!-- Brand -->
    <div class="sidebar-brand">
      <div class="brand-mark">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
          <circle cx="12" cy="12" r="10" fill="url(#navgrad)" opacity="0.9"/>
          <path d="M8 12h8M12 8v8" stroke="white" stroke-width="2.2" stroke-linecap="round"/>
          <defs>
            <linearGradient id="navgrad" x1="0" y1="0" x2="24" y2="24">
              <stop offset="0%" stop-color="#e8855a"/>
              <stop offset="100%" stop-color="#c96342"/>
            </linearGradient>
          </defs>
        </svg>
      </div>
      <Transition name="label-fade">
        <span v-if="!effectiveCollapsed" class="brand-name">排款系统</span>
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
    <div class="sidebar-footer">
      <template v-if="!effectiveCollapsed">
        <div class="user-info">
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
        <div class="user-avatar-sm">{{ auth.user?.name?.[0] || '?' }}</div>
        <button class="logout-btn icon-only" @click="logout" title="退出登录">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9"/>
          </svg>
        </button>
      </template>
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
  background: rgba(201, 99, 66, 0.18);
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
  box-shadow: 0 0 18px rgba(201, 99, 66, 0.22);
}
.brand-name { font-size: 15px; font-weight: 700; color: #fff; white-space: nowrap; }

.nav-links { flex: 1; padding: 12px 9px; display: flex; flex-direction: column; gap: 2px; overflow: hidden; }

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
