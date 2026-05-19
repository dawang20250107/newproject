<template>
  <aside class="sidebar" :class="{ collapsed }">
    <!-- Brand -->
    <div class="sidebar-brand">
      <div class="brand-logo">
        <svg class="brand-mark" width="32" height="32" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
          <defs>
            <linearGradient id="logoGrad2" x1="4" y1="3" x2="28" y2="29" gradientUnits="userSpaceOnUse">
              <stop stop-color="#fff3b0"/>
              <stop offset="0.5" stop-color="#d4af37"/>
              <stop offset="1" stop-color="#a16207"/>
            </linearGradient>
          </defs>
          <circle cx="16" cy="16" r="14.5" fill="url(#logoGrad2)" />
          <circle cx="16" cy="16" r="11.2" fill="#ffffff" fill-opacity="0.14" stroke="#ffffff" stroke-opacity="0.28" stroke-width="0.9"/>
          <circle cx="11.1" cy="11.3" r="2.1" fill="#ffffff" fill-opacity="0.95"/>
          <circle cx="16" cy="9.5" r="2.3" fill="#ffffff" fill-opacity="0.95"/>
          <circle cx="20.9" cy="11.3" r="2.1" fill="#ffffff" fill-opacity="0.95"/>
          <path d="M11.9 19.8c0-2.4 1.8-4.4 4.1-4.4s4.1 2 4.1 4.4c0 2.3-1.8 4.1-4.1 4.1s-4.1-1.8-4.1-4.1Z" fill="#ffffff" fill-opacity="0.95"/>
        </svg>
        <!-- Logo glow ring -->
        <div class="brand-glow"></div>
      </div>
      <transition name="fade-text">
        <div v-if="!collapsed" class="brand-text">
          <span class="brand-name">KXT</span>
          <span class="brand-sub">成为世界级物贸生态集团</span>
        </div>
      </transition>
      <button class="collapse-btn" @click="$emit('toggle')" :title="collapsed ? '展开' : '收起'">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
          <path v-if="!collapsed" d="M15 18l-6-6 6-6"/>
          <path v-else d="M9 18l6-6-6-6"/>
        </svg>
      </button>
    </div>

    <!-- Nav Section -->
    <div class="nav-section">
      <span v-if="!collapsed" class="nav-label">业务中心</span>
      <nav class="nav-list">
        <router-link
          v-for="item in navItems"
          :key="item.path"
          :to="item.path"
          class="nav-item"
          :class="{ active: isActive(item.path) }"
          :title="collapsed ? item.label : ''"
        >
          <!-- Active indicator bar -->
          <span class="active-bar"></span>
          <!-- Active glow dot -->
          <span class="active-dot"></span>
          <span class="nav-icon" v-html="item.icon"></span>
          <transition name="fade-text">
            <span v-if="!collapsed" class="nav-text">{{ item.label }}</span>
          </transition>
          <transition name="fade-text">
            <span v-if="!collapsed && item.badge" class="nav-badge" :class="item.badgeType">{{ item.badge }}</span>
          </transition>
        </router-link>
      </nav>
    </div>

    <!-- Footer user area -->
    <div class="sidebar-footer">
      <div class="user-card" :class="{ compact: collapsed }">
        <div class="user-avatar" aria-hidden="true">
          <svg class="pet-mark" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
            <defs>
              <linearGradient id="userGrad" x1="4" y1="3" x2="28" y2="29" gradientUnits="userSpaceOnUse">
                <stop stop-color="#fff3b0"/>
                <stop offset="0.55" stop-color="#d4af37"/>
                <stop offset="1" stop-color="#a16207"/>
              </linearGradient>
            </defs>
            <circle cx="16" cy="16" r="14.5" fill="url(#userGrad)" />
            <circle cx="11.1" cy="11.3" r="2.1" fill="#ffffff" fill-opacity="0.96"/>
            <circle cx="16" cy="9.5" r="2.3" fill="#ffffff" fill-opacity="0.96"/>
            <circle cx="20.9" cy="11.3" r="2.1" fill="#ffffff" fill-opacity="0.96"/>
            <path d="M11.9 19.8c0-2.4 1.8-4.4 4.1-4.4s4.1 2 4.1 4.4c0 2.3-1.8 4.1-4.1 4.1s-4.1-1.8-4.1-4.1Z" fill="#ffffff" fill-opacity="0.96"/>
          </svg>
        </div>
        <transition name="fade-text">
          <div v-if="!collapsed" class="user-info">
            <span class="user-name">{{ username }}</span>
            <span class="user-role">已登录</span>
          </div>
        </transition>
      </div>
      <button v-if="!collapsed" class="logout-btn" @click="handleLogout" title="退出登录">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
      </button>
    </div>
  </aside>
</template>

<script setup>
import { useRoute } from 'vue-router'

const props = defineProps({ collapsed: Boolean })
defineEmits(['toggle'])
const route = useRoute()

const navItems = [
  {
    path: '/dashboard',
    label: '数据看板',
    icon: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/></svg>`,
  },
  {
    path: '/daily-report',
    label: '每日日报',
    icon: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/><line x1="8" y1="14" x2="16" y2="14"/><line x1="8" y1="18" x2="12" y2="18"/></svg>`,
  },
]

const isActive = (path) => route.path === path

const userData = JSON.parse(localStorage.getItem('kxt_user') || '{}')
const username = userData.username || '用户'

async function handleLogout() {
  if (!confirm('确定退出登录？')) return
  try {
    const { auth } = await import('@/api/index.js')
    await auth.logout()
  } catch {}
  localStorage.removeItem('kxt_token')
  localStorage.removeItem('kxt_user')
  window.location.hash = '#/login'
  window.location.reload()
}
</script>

<style scoped>
.sidebar {
  position: fixed; top: 0; left: 0; bottom: 0;
  width: 260px;
  background: var(--sidebar-bg);
  display: flex; flex-direction: column;
  z-index: 100;
  transition: width var(--transition-slow);
  overflow: hidden;
  border-right: 1px solid var(--sidebar-border);
  box-shadow: 4px 0 24px rgba(0,0,0,0.3);
}
.sidebar.collapsed { width: 72px; }

/* Brand area */
.sidebar-brand {
  display: flex; align-items: center; gap: 12px;
  padding: 20px 16px 18px;
  border-bottom: 1px solid var(--sidebar-border);
  min-height: 72px;
  position: relative;
}
.brand-logo {
  flex-shrink: 0;
  position: relative;
  filter: drop-shadow(0 2px 10px rgba(212,175,55,0.45));
}
.brand-glow {
  position: absolute;
  inset: -4px;
  border-radius: 12px;
  background: radial-gradient(circle, rgba(212,175,55,0.34), transparent 70%);
  opacity: 0.6;
  pointer-events: none;
  animation: pulse-glow 3s ease-in-out infinite;
}
.brand-mark {
  display: block;
}
.brand-text { display: flex; flex-direction: column; overflow: hidden; white-space: nowrap; }
.brand-name {
  font-size: 18px; font-weight: 800;
  background: linear-gradient(135deg, #fff3b0, #f5d36c, #d4af37);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  background-clip: text;
  line-height: 1.2;
  letter-spacing: 0.04em;
}
.brand-sub {
  font-size: 10px; color: var(--sidebar-text);
  letter-spacing: 0.1em; text-transform: uppercase;
  font-weight: 500; margin-top: 1px;
}

.collapse-btn {
  margin-left: auto; flex-shrink: 0;
  width: 28px; height: 28px;
  display: flex; align-items: center; justify-content: center;
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: var(--radius-sm);
  color: var(--sidebar-text);
  cursor: pointer;
  transition: all var(--transition-fast);
}
.collapse-btn:hover { background: rgba(255,255,255,0.1); color: var(--sidebar-text-active); }

/* Navigation */
.nav-section { flex: 1; padding: 16px 10px; overflow-y: auto; overflow-x: hidden; }
.nav-section::-webkit-scrollbar { width: 3px; }
.nav-section::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.08); border-radius: 2px; }
.nav-label {
  font-size: 10px; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.1em;
  color: rgba(148,163,184,0.4);
  padding: 0 8px 8px;
  display: block;
}
.nav-list { display: flex; flex-direction: column; gap: 2px; }

.nav-item {
  position: relative;
  display: flex; align-items: center; gap: 12px;
  padding: 10px 12px;
  border-radius: var(--radius-md);
  color: var(--sidebar-text);
  text-decoration: none;
  transition: all var(--transition-fast);
  overflow: hidden; white-space: nowrap;
}
.nav-item:hover {
  background: var(--sidebar-hover);
  color: rgba(255,255,255,0.9);
}
.nav-item.active {
  background: var(--sidebar-active);
  color: #fff;
}
.nav-item.active .nav-icon { color: var(--sidebar-icon-active); }

/* Active bar - left accent line */
.active-bar {
  display: none;
  position: absolute;
  left: 0; top: 50%; transform: translateY(-50%);
  width: 3px; height: 20px;
  background: linear-gradient(180deg, #fff3b0, #d4af37);
  border-radius: 0 3px 3px 0;
  box-shadow: 0 0 10px rgba(212,175,55,0.55);
}
.nav-item.active .active-bar { display: block; }

/* Active dot - subtle pulsing indicator */
.active-dot {
  position: absolute;
  right: 12px; top: 50%; transform: translateY(-50%);
  width: 6px; height: 6px;
  border-radius: 50%;
  background: var(--sidebar-icon-active);
  opacity: 0;
  transition: opacity var(--transition-fast);
  box-shadow: 0 0 6px rgba(212,175,55,0.8);
}
.nav-item.active .active-dot { opacity: 1; }

.nav-icon {
  flex-shrink: 0; width: 20px; height: 20px;
  display: flex; align-items: center; justify-content: center;
  transition: color var(--transition-fast);
}
.nav-text { font-size: 13.5px; font-weight: 500; flex: 1; }
.nav-badge {
  font-size: 10px; font-weight: 700;
  padding: 2px 6px; border-radius: 100px;
  min-width: 20px; text-align: center;
}
.badge-danger  { background: rgba(239,68,68,0.2); color: #fca5a5; }
.badge-warning { background: rgba(245,158,11,0.2); color: #fcd34d; }
.badge-info    { background: rgba(212,175,55,0.2); color: #f5d36c; }

/* Footer */
.sidebar-footer {
  padding: 12px 10px;
  border-top: 1px solid var(--sidebar-border);
  display: flex;
  align-items: center;
  gap: 8px;
}
.logout-btn {
  flex-shrink: 0;
  width: 28px; height: 28px;
  border-radius: 6px;
  display: flex; align-items: center; justify-content: center;
  background: transparent; border: 1px solid transparent;
  color: var(--text-muted); cursor: pointer;
  transition: all 0.15s;
}
.logout-btn:hover { background: rgba(239,68,68,0.1); color: #ef4444; border-color: rgba(239,68,68,0.2); }
.user-card {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 12px; border-radius: var(--radius-md);
  transition: background var(--transition-fast);
  cursor: pointer;
}
.user-card:hover { background: var(--sidebar-hover); }
.user-avatar {
  flex-shrink: 0; width: 34px; height: 34px; border-radius: 50%;
  background: linear-gradient(135deg, #fff3b0, #d4af37);
  display: flex; align-items: center; justify-content: center;
  box-shadow: 0 2px 10px rgba(212,175,55,0.42);
  overflow: hidden;
}
.pet-mark {
  width: 20px;
  height: 20px;
  display: block;
}
.user-info { display: flex; flex-direction: column; overflow: hidden; white-space: nowrap; }
.user-name { font-size: 13px; font-weight: 600; color: var(--sidebar-text-active); }
.user-role { font-size: 10px; color: var(--sidebar-text); }

.fade-text-enter-active { transition: opacity 0.2s, transform 0.2s; }
.fade-text-leave-active { transition: opacity 0.15s; }
.fade-text-enter-from   { opacity: 0; transform: translateX(-6px); }
.fade-text-leave-to    { opacity: 0; }
</style>
