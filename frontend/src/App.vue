<script setup>
import { computed, ref, watch, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import AppNav from './components/AppNav.vue'
import WelcomeOverlay from './components/WelcomeOverlay.vue'
import { useAuthStore } from './stores/auth.js'

const route = useRoute()
const auth = useAuthStore()
const showNav = computed(() => auth.isLoggedIn && !route.meta.public)
const navCollapsed = ref(localStorage.getItem('nav_collapsed') === '1')
const mobileNavOpen = ref(false)

// Keep permissions fresh (super_admin may have changed them since last login).
onMounted(() => { if (auth.isLoggedIn) auth.refresh() })

const showWelcome = ref(false)
// Show welcome on first login in this session
const _shownThisSession = ref(false)
watch(() => auth.isLoggedIn, (v) => {
  if (v && !_shownThisSession.value) {
    _shownThisSession.value = true
    showWelcome.value = true
  }
})

// Close the mobile drawer whenever the route changes.
watch(() => route.path, () => { mobileNavOpen.value = false })

function onNavCollapse(v) {
  navCollapsed.value = v
  localStorage.setItem('nav_collapsed', v ? '1' : '0')
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
      <!-- mobile hamburger + drawer backdrop (inside .layout to share the sidebar's stacking context) -->
      <button v-if="showNav" class="mobile-nav-toggle" @click="mobileNavOpen = true" aria-label="打开导航">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round">
          <line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/>
        </svg>
      </button>
      <Transition name="backdrop-fade">
        <div v-if="showNav && mobileNavOpen" class="mobile-nav-backdrop" @click="mobileNavOpen = false"></div>
      </Transition>

      <AppNav v-if="showNav" :collapsed="navCollapsed" :mobile-open="mobileNavOpen"
        @update:collapsed="onNavCollapse" @close-mobile="mobileNavOpen = false" />
      <main :class="showNav ? ['main-content', navCollapsed ? 'nav-collapsed' : ''] : 'main-public'">
        <router-view />
      </main>
    </div>

    <WelcomeOverlay v-if="showWelcome" :user="auth.user" @done="showWelcome = false" />
  </div>
</template>
