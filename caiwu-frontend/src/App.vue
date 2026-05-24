<script setup>
import { computed, ref, watch, onMounted, onBeforeUnmount } from 'vue'
import { useRoute } from 'vue-router'
import AppNav from './components/AppNav.vue'
import WelcomeOverlay from './components/WelcomeOverlay.vue'
import { useAuthStore } from './stores/auth.js'

const route = useRoute()
const auth = useAuthStore()
const showNav = computed(() => auth.isLoggedIn && !route.meta.public)

const AUTO_COLLAPSE_MS = 10000
const navPref = ref(localStorage.getItem('cw_nav_pref'))
const navCollapsed = ref(navPref.value === 'collapsed')
const mobileNavOpen = ref(false)

let autoTimer = null
function clearAutoTimer() {
  if (autoTimer) { clearTimeout(autoTimer); autoTimer = null }
}
function scheduleAutoCollapse() {
  clearAutoTimer()
  if (navPref.value || navCollapsed.value || !showNav.value) return
  autoTimer = setTimeout(() => { navCollapsed.value = true }, AUTO_COLLAPSE_MS)
}
function onNavHover(hovering) {
  if (navPref.value) return
  if (hovering) clearAutoTimer()
  else scheduleAutoCollapse()
}

onMounted(() => {
  if (auth.isLoggedIn) auth.refresh()
  scheduleAutoCollapse()
})
onBeforeUnmount(clearAutoTimer)

watch(showNav, (v) => { if (v) scheduleAutoCollapse(); else clearAutoTimer() })

const showWelcome = ref(false)
const _shownThisSession = ref(false)
watch(() => auth.isLoggedIn, (v) => {
  if (v && !_shownThisSession.value) {
    _shownThisSession.value = true
    showWelcome.value = true
  }
})

watch(() => route.path, () => { mobileNavOpen.value = false })

function onNavCollapse(v) {
  navCollapsed.value = v
  navPref.value = v ? 'collapsed' : 'expanded'
  localStorage.setItem('cw_nav_pref', navPref.value)
  clearAutoTimer()
}
</script>

<template>
  <div>
    <div class="bg-layer">
      <div class="bg-orb bg-orb-1"></div>
      <div class="bg-orb bg-orb-2"></div>
      <div class="bg-orb bg-orb-3"></div>
      <div class="bg-orb bg-orb-4"></div>
    </div>

    <div class="layout">
      <button v-if="showNav" class="mobile-nav-toggle" @click="mobileNavOpen = true" aria-label="打开导航">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round">
          <line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/>
        </svg>
      </button>
      <Transition name="backdrop-fade">
        <div v-if="showNav && mobileNavOpen" class="mobile-nav-backdrop" @click="mobileNavOpen = false"></div>
      </Transition>

      <AppNav v-if="showNav" :collapsed="navCollapsed" :mobile-open="mobileNavOpen"
        @update:collapsed="onNavCollapse" @close-mobile="mobileNavOpen = false" @hover="onNavHover" />
      <main :class="showNav ? ['main-content', navCollapsed ? 'nav-collapsed' : ''] : 'main-public'">
        <router-view />
      </main>
    </div>

    <WelcomeOverlay v-if="showWelcome" :user="auth.user" @done="showWelcome = false" />
  </div>
</template>
