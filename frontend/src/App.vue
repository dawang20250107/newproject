<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import AppNav from './components/AppNav.vue'
import WelcomeOverlay from './components/WelcomeOverlay.vue'
import { useAuthStore } from './stores/auth.js'

const route = useRoute()
const auth = useAuthStore()
const showNav = computed(() => auth.isLoggedIn && !route.meta.public)
const navCollapsed = ref(localStorage.getItem('nav_collapsed') === '1')

const showWelcome = ref(false)
// Show welcome on first login in this session
const _shownThisSession = ref(false)
watch(() => auth.isLoggedIn, (v) => {
  if (v && !_shownThisSession.value) {
    _shownThisSession.value = true
    showWelcome.value = true
  }
})

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
      <AppNav v-if="showNav" :collapsed="navCollapsed" @update:collapsed="onNavCollapse" />
      <main :class="showNav ? ['main-content', navCollapsed ? 'nav-collapsed' : ''] : ''">
        <router-view />
      </main>
    </div>

    <WelcomeOverlay v-if="showWelcome" :user="auth.user" @done="showWelcome = false" />
  </div>
</template>
