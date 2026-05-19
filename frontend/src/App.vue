<template>
  <div class="app-shell">
    <ClickEffect />
    <Sidebar :collapsed="sidebarCollapsed" @toggle="sidebarCollapsed = !sidebarCollapsed" />
    <div class="main-area" :class="{ 'sidebar-collapsed': sidebarCollapsed }">
      <TopBar @toggle-sidebar="sidebarCollapsed = !sidebarCollapsed" />
      <main class="page-content">
        <router-view v-slot="{ Component }">
          <transition name="page" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </main>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import Sidebar from '@/components/Sidebar.vue'
import TopBar  from '@/components/TopBar.vue'
import ClickEffect from '@/components/ClickEffect.vue'

const sidebarCollapsed = ref(false)
</script>

<style scoped>
.app-shell {
  display: flex;
  min-height: 100vh;
  background: var(--bg-page);
}
.main-area {
  flex: 1;
  margin-left: 260px;
  min-height: 100vh;
  transition: margin-left var(--transition-slow);
  display: flex;
  flex-direction: column;
}
.main-area.sidebar-collapsed { margin-left: 72px; }
.page-content {
  flex: 1;
  padding: 28px 32px;
  max-width: 1600px;
  width: 100%;
  margin: 0 auto;
}

/* Page transition */
.page-enter-active,
.page-leave-active { transition: opacity 0.2s ease, transform 0.2s ease; }
.page-enter-from   { opacity: 0; transform: translateY(8px); }
.page-leave-to     { opacity: 0; transform: translateY(-4px); }

@media (max-width: 768px) {
  .main-area       { margin-left: 0; }
  .main-area.sidebar-collapsed { margin-left: 0; }
  .page-content    { padding: 16px; }
}
</style>
