<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth.js'
import { ROLE_LABELS, JOB_LABELS } from '../constants.js'

const props = defineProps({
  collapsed: Boolean,
  mobileOpen: Boolean,
})
const emit = defineEmits(['toggle'])
const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const effectiveCollapsed = computed(() => props.mobileOpen ? false : props.collapsed)

const navItems = [
  { path: '/report',   icon: '📊', label: '财务报表', page: 'report' },
  { path: '/data',     icon: '📥', label: '数据加工', page: 'data' },
  { path: '/charts',   icon: '📈', label: '图表分析', page: 'charts' },
  { path: '/settings', icon: '⚙️', label: '系统设置', page: 'settings' },
]

function logout() {
  auth.logout()
  router.push('/login')
}
</script>

<template>
  <nav :class="['app-nav', { collapsed: effectiveCollapsed, 'mobile-open': mobileOpen }]">
    <!-- Logo / Toggle -->
    <div class="nav-header" @click="emit('toggle')">
      <div class="nav-logo">
        <span class="logo-icon">📑</span>
        <Transition name="label-fade">
          <span v-if="!effectiveCollapsed" class="logo-text">财务分析</span>
        </Transition>
      </div>
      <button class="collapse-btn" :title="collapsed ? '展开' : '收起'">
        {{ effectiveCollapsed ? '›' : '‹' }}
      </button>
    </div>

    <!-- Nav links -->
    <div class="nav-links">
      <router-link
        v-for="item in navItems"
        v-show="auth.canPage(item.page)"
        :key="item.path"
        :to="item.path"
        :class="['nav-item', { active: route.path === item.path }]"
        :title="effectiveCollapsed ? item.label : ''"
      >
        <span class="nav-icon">{{ item.icon }}</span>
        <Transition name="label-fade">
          <span v-if="!effectiveCollapsed" class="nav-label">{{ item.label }}</span>
        </Transition>
        <Transition name="label-fade">
          <span v-if="!effectiveCollapsed && route.path === item.path" class="nav-arrow">›</span>
        </Transition>
      </router-link>
    </div>

    <!-- User footer -->
    <div class="nav-footer">
      <div class="nav-user" :title="effectiveCollapsed ? (auth.user?.name || '') : ''">
        <div class="user-avatar">{{ auth.user?.name?.[0] || '?' }}</div>
        <Transition name="label-fade">
          <div v-if="!effectiveCollapsed" class="user-info">
            <div class="user-name">{{ auth.user?.name }}</div>
            <div class="user-role">
              <span v-if="auth.user?.job_title && JOB_LABELS[auth.user.job_title]">
                {{ JOB_LABELS[auth.user.job_title] }}
              </span>
              <span v-else-if="auth.user?.role === 'super_admin'" class="role-chip">超级管理员</span>
            </div>
          </div>
        </Transition>
      </div>
      <button class="logout-btn" @click="logout" :title="effectiveCollapsed ? '退出' : ''">
        <span>⏏</span>
        <Transition name="label-fade">
          <span v-if="!effectiveCollapsed">退出</span>
        </Transition>
      </button>
    </div>
  </nav>
</template>

<style scoped>
.app-nav {
  width: 220px; min-width: 220px;
  height: 100vh; display: flex; flex-direction: column;
  background: rgba(255,253,250,.92);
  backdrop-filter: blur(20px);
  border-right: 1px solid var(--border);
  transition: width .3s cubic-bezier(.4,0,.2,1), min-width .3s cubic-bezier(.4,0,.2,1);
  overflow: hidden; z-index: 100; position: relative;
}
.app-nav.collapsed { width: 64px; min-width: 64px; }

@media (max-width: 768px) {
  .app-nav {
    position: fixed; left: 0; top: 0;
    transform: translateX(-100%);
    transition: transform .28s cubic-bezier(.4,0,.2,1);
    width: 220px; min-width: 220px;
    box-shadow: 4px 0 24px rgba(100,60,30,.15);
  }
  .app-nav.mobile-open { transform: translateX(0); }
}

.nav-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 20px 16px 16px; cursor: pointer; user-select: none;
  border-bottom: 1px solid var(--border);
}
.nav-logo { display: flex; align-items: center; gap: 10px; overflow: hidden; }
.logo-icon { font-size: 22px; flex-shrink: 0; }
.logo-text { font-size: 15px; font-weight: 800; color: var(--text); white-space: nowrap; letter-spacing: -.02em; }

.collapse-btn {
  background: none; border: none; color: var(--muted); cursor: pointer;
  font-size: 18px; padding: 0 4px; flex-shrink: 0; line-height: 1;
  transition: color .16s;
}
.collapse-btn:hover { color: var(--primary); }

.nav-links { flex: 1; padding: 12px 10px; overflow-y: auto; overflow-x: hidden; display: flex; flex-direction: column; gap: 3px; }

.nav-item {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 12px; border-radius: 10px;
  text-decoration: none; color: var(--muted); font-size: 13px; font-weight: 500;
  transition: all .16s; white-space: nowrap; overflow: hidden;
  position: relative;
}
.nav-item:hover { background: rgba(201,99,66,.07); color: var(--primary); }
.nav-item.active {
  background: rgba(201,99,66,.12); color: var(--primary); font-weight: 700;
}
.nav-icon { font-size: 18px; flex-shrink: 0; }
.nav-label { flex: 1; }
.nav-arrow { font-size: 14px; color: var(--primary); }

.nav-footer {
  padding: 12px 10px;
  border-top: 1px solid var(--border);
  display: flex; flex-direction: column; gap: 6px;
}
.nav-user { display: flex; align-items: center; gap: 10px; padding: 6px 6px; overflow: hidden; }
.user-avatar {
  width: 32px; height: 32px; border-radius: 50%;
  background: var(--grad); color: #fff;
  display: flex; align-items: center; justify-content: center;
  font-weight: 700; font-size: 13px; flex-shrink: 0;
}
.user-info { overflow: hidden; }
.user-name { font-size: 13px; font-weight: 600; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.user-role { font-size: 11px; color: var(--muted); margin-top: 1px; }
.role-chip { background: rgba(201,99,66,.1); color: var(--primary); padding: 1px 7px; border-radius: 10px; font-size: 11px; font-weight: 600; }

.logout-btn {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 12px; border-radius: 9px; border: none;
  background: none; color: var(--muted); font-size: 12px; cursor: pointer;
  transition: all .16s; width: 100%;
}
.logout-btn:hover { background: rgba(198,40,40,.07); color: var(--danger); }

.label-fade-enter-active, .label-fade-leave-active { transition: opacity .18s, width .2s; overflow: hidden; }
.label-fade-enter-from, .label-fade-leave-to { opacity: 0; width: 0 !important; }
</style>
