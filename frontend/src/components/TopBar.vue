<template>
  <header class="top-bar">
    <!-- Left: hamburger + breadcrumb -->
    <div class="topbar-left">
      <button class="icon-btn" @click="$emit('toggle-sidebar')">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
          <line x1="3" y1="6" x2="21" y2="6"/>
          <line x1="3" y1="12" x2="21" y2="12"/>
          <line x1="3" y1="18" x2="21" y2="18"/>
        </svg>
      </button>
      <nav class="breadcrumb">
        <span class="bc-item">成为世界级物贸生态集团</span>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9,18 15,12 9,6"/></svg>
        <span class="bc-item active">{{ currentPageName }}</span>
      </nav>
    </div>

    <!-- Right: actions -->
    <div class="topbar-right">
      <!-- Date -->
      <div class="topbar-date">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
        {{ today }}
      </div>

      <!-- Notification bell -->
      <button class="icon-btn notif-btn">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>
        <span class="notif-dot"></span>
      </button>

      <!-- User avatar -->
      <div class="topbar-avatar" aria-hidden="true">
        <svg class="pet-mark" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
          <defs>
            <linearGradient id="topbarGrad" x1="4" y1="3" x2="28" y2="29" gradientUnits="userSpaceOnUse">
              <stop stop-color="#fff3b0"/>
              <stop offset="0.55" stop-color="#d4af37"/>
              <stop offset="1" stop-color="#a16207"/>
            </linearGradient>
          </defs>
          <circle cx="16" cy="16" r="14.5" fill="url(#topbarGrad)" />
          <circle cx="11.1" cy="11.3" r="2.1" fill="#ffffff" fill-opacity="0.96"/>
          <circle cx="16" cy="9.5" r="2.3" fill="#ffffff" fill-opacity="0.96"/>
          <circle cx="20.9" cy="11.3" r="2.1" fill="#ffffff" fill-opacity="0.96"/>
          <path d="M11.9 19.8c0-2.4 1.8-4.4 4.1-4.4s4.1 2 4.1 4.4c0 2.3-1.8 4.1-4.1 4.1s-4.1-1.8-4.1-4.1Z" fill="#ffffff" fill-opacity="0.96"/>
        </svg>
      </div>
    </div>
  </header>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'

defineEmits(['toggle-sidebar'])

const route = useRoute()
const pageNames = {
  '/dashboard':   '数据看板',
}
const currentPageName = computed(() => pageNames[route.path] || '未知')

const today = new Date().toLocaleDateString('zh-CN', {
  year: 'numeric', month: 'long', day: 'numeric', weekday: 'long'
})
</script>

<style scoped>
.top-bar {
  position: sticky;
  top: 0;
  z-index: 50;
  height: 60px;
  background: var(--bg-header);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--border-light);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  box-shadow: var(--shadow-xs);
}

.topbar-left  { display: flex; align-items: center; gap: 12px; }
.topbar-right { display: flex; align-items: center; gap: 12px; }

.breadcrumb {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
}
.bc-item { color: var(--text-secondary); font-weight: 500; max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bc-item.active { color: var(--text-primary); font-weight: 600; max-width: none; white-space: nowrap; }
.breadcrumb svg { color: var(--text-muted); }

.icon-btn {
  width: 36px; height: 36px;
  display: flex; align-items: center; justify-content: center;
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--radius-md);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all var(--transition-fast);
}
.icon-btn:hover {
  background: var(--bg-page);
  border-color: var(--border-light);
  color: var(--text-primary);
}

.topbar-date {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-secondary);
  padding: 5px 10px;
  background: var(--bg-page);
  border-radius: var(--radius-md);
  border: 1px solid var(--border-light);
  white-space: nowrap;
}

.notif-btn { position: relative; }
.notif-dot {
  position: absolute;
  top: 7px; right: 7px;
  width: 7px; height: 7px;
  border-radius: 50%;
  background: var(--color-danger);
  border: 2px solid var(--bg-card);
}

.topbar-avatar {
  width: 34px; height: 34px;
  border-radius: 50%;
  background: var(--gradient-avatar);
  display: flex; align-items: center; justify-content: center;
  cursor: pointer;
  box-shadow: 0 2px 10px rgba(212,175,55,0.42);
  transition: box-shadow var(--transition-fast);
}
.pet-mark {
  width: 18px;
  height: 18px;
  display: block;
}
.topbar-avatar:hover { box-shadow: 0 4px 14px rgba(212,175,55,0.5); }
</style>
