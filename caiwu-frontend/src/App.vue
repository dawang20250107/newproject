<script setup>
import { ref, watch, onMounted, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from './stores/auth.js'
import AppNav from './components/AppNav.vue'
import WelcomeOverlay from './components/WelcomeOverlay.vue'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const navCollapsed = ref(localStorage.getItem('cw_nav_pref') === '1')
const mobileNavOpen = ref(false)
const showWelcome = ref(false)

let autoCollapseTimer = null

function startAutoCollapse() {
  clearTimeout(autoCollapseTimer)
  autoCollapseTimer = setTimeout(() => {
    if (!navCollapsed.value) {
      navCollapsed.value = true
      localStorage.setItem('cw_nav_pref', '1')
    }
  }, 10000)
}

function pauseAutoCollapse() {
  clearTimeout(autoCollapseTimer)
}

function toggleNav() {
  navCollapsed.value = !navCollapsed.value
  localStorage.setItem('cw_nav_pref', navCollapsed.value ? '1' : '0')
  if (!navCollapsed.value) startAutoCollapse()
}

watch(route, () => { mobileNavOpen.value = false })

onMounted(async () => {
  if (auth.isLoggedIn) {
    await auth.refresh()
    const wasShown = sessionStorage.getItem('cw_welcome_shown')
    if (!wasShown) {
      showWelcome.value = true
      sessionStorage.setItem('cw_welcome_shown', '1')
    }
    startAutoCollapse()
  }
})

onUnmounted(() => clearTimeout(autoCollapseTimer))
</script>

<template>
  <template v-if="route.path === '/login' || !auth.isLoggedIn">
    <router-view />
  </template>
  <template v-else>
    <div class="layout">
      <button class="mobile-nav-toggle" @click="mobileNavOpen = !mobileNavOpen">
        <span>{{ mobileNavOpen ? '✕' : '☰' }}</span>
      </button>

      <Transition name="backdrop-fade">
        <div v-if="mobileNavOpen" class="mobile-backdrop" @click="mobileNavOpen = false" />
      </Transition>

      <AppNav
        :collapsed="navCollapsed"
        :mobile-open="mobileNavOpen"
        @toggle="toggleNav"
        @mouseover.native="pauseAutoCollapse"
        @mouseout.native="startAutoCollapse"
      />

      <main :class="{ 'nav-collapsed': navCollapsed }">
        <router-view />
      </main>
    </div>

    <WelcomeOverlay v-if="showWelcome" :user="auth.user" @done="showWelcome = false" />
  </template>
</template>

<style scoped>
.mobile-nav-toggle {
  display: none;
  position: fixed; top: 14px; left: 14px; z-index: 110;
  width: 38px; height: 38px; border-radius: 10px;
  background: var(--card); border: 1px solid var(--border);
  font-size: 16px; cursor: pointer; color: var(--text);
  box-shadow: 0 2px 8px rgba(100,60,30,.1);
}
@media (max-width: 768px) { .mobile-nav-toggle { display: flex; align-items: center; justify-content: center; } }

.mobile-backdrop {
  position: fixed; inset: 0; z-index: 99;
  background: rgba(20,10,5,.35); backdrop-filter: blur(3px);
}
.backdrop-fade-enter-active, .backdrop-fade-leave-active { transition: opacity .2s; }
.backdrop-fade-enter-from, .backdrop-fade-leave-to { opacity: 0; }
</style>
