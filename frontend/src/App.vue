<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import AppNav from './components/AppNav.vue'
import { useAuthStore } from './stores/auth.js'

const route = useRoute()
const auth = useAuthStore()
const showNav = computed(() => auth.isLoggedIn && !route.meta.public)
</script>

<template>
  <div class="layout">
    <AppNav v-if="showNav" />
    <main :class="showNav ? 'main-content' : ''">
      <router-view />
    </main>
  </div>
</template>
