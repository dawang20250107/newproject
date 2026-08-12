<script setup>
import { computed, ref, watch, onMounted, onBeforeUnmount } from 'vue'
import { useRoute } from 'vue-router'
import AppNav from './components/AppNav.vue'
import WelcomeOverlay from './components/WelcomeOverlay.vue'
import ChangePasswordModal from './components/ChangePasswordModal.vue'
import Toast from './components/Toast.vue'
import ConfirmHost from './components/ConfirmHost.vue'
import ResultHost from './components/ResultHost.vue'
import ErrorBoundary from './components/ErrorBoundary.vue'
import { useAuthStore } from './stores/auth.js'
import { useRouter } from 'vue-router'
import { useInteractionFeel } from './composables/useInteractionFeel.js'

const route = useRoute()
const auth = useAuthStore()
const showNav = computed(() => auth.isLoggedIn && !route.meta.public)

// 全局操作手感：/ 聚焦搜索、搜索框 Esc 清空、勾选列整格热区、数字框聚焦全选
useInteractionFeel()

const AUTO_COLLAPSE_MS = 10000
// User's explicit choice, if any: 'collapsed' | 'expanded' | null (never toggled).
const navPref = ref(localStorage.getItem('nav_pref'))
const navCollapsed = ref(navPref.value === 'collapsed')
const mobileNavOpen = ref(false)

// ── smart auto-collapse: 10s after entering, paused while hovering the nav,
// and skipped entirely once the user has set a manual preference. ──
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
  if (hovering) clearAutoTimer()    // pause countdown while pointer rests on nav
  else scheduleAutoCollapse()       // restart a fresh countdown when it leaves
}

const _router = useRouter()
function exitPreview() { auth.stopPreview(); _router.push('/permissions') }

// Keep permissions fresh (super_admin may have changed them since last login).
onMounted(() => {
  if (auth.isLoggedIn) auth.refresh()
  scheduleAutoCollapse()
})
onBeforeUnmount(clearAutoTimer)

// Restart the countdown whenever the nav (re)appears, e.g. right after login.
watch(showNav, (v) => { if (v) scheduleAutoCollapse(); else clearAutoTimer() })

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

// Notify all open views to refetch when global dept scope changes.
watch(() => auth.activeDepts, () => {
  window.dispatchEvent(new CustomEvent('pk:depts-changed'))
}, { deep: true })

// Sync nav-collapsed state to body class so teleported .bottom-bar elements
// can respond to nav width changes via CSS (body.nav-collapsed .bottom-bar).
watch(navCollapsed, (v) => {
  document.body.classList.toggle('nav-collapsed', v)
}, { immediate: true })

function onNavCollapse(v) {
  // Manual toggle → remember the preference and disable auto behaviour.
  navCollapsed.value = v
  navPref.value = v ? 'collapsed' : 'expanded'
  localStorage.setItem('nav_pref', navPref.value)
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
        @update:collapsed="onNavCollapse" @close-mobile="mobileNavOpen = false" @hover="onNavHover" />
      <main :class="showNav ? ['main-content', navCollapsed ? 'nav-collapsed' : '', route.meta.fullHeight ? 'full-height-view' : ''] : 'main-public'">
        <router-view v-slot="{ Component }">
          <ErrorBoundary :key="route.path">
            <!-- 高频台账页 keep-alive:返回秒开(DOM 缓存),数据由各页面 onActivated 后台刷新 -->
            <KeepAlive
              :include="['PaymentsPage', 'ARRecordsPage', 'ApprovalRecordsPage', 'DailyReceiptsPage', 'AdvancesPage', 'ARProjectsPage', 'CustomerListPage', 'BudgetPage']"
              :max="8">
              <component :is="Component" />
            </KeepAlive>
          </ErrorBoundary>
        </router-view>
      </main>
    </div>

    <WelcomeOverlay v-if="showWelcome" :user="auth.user" @done="showWelcome = false" />

    <!-- 超管重置临时密码后：强制改密，覆盖全屏不可跳过 -->
    <ChangePasswordModal v-if="auth.isLoggedIn && auth.mustChangePassword" forced />
    <!-- 权限预览横幅：超管以某职务视角浏览时常驻置顶，可一键退出 -->
    <div v-if="auth.previewJob" class="preview-banner">
      👁 正在预览「{{ auth.previewJob }}」的界面视角（数据仍按您本人权限返回）
      <button class="pv-exit" @click="exitPreview">退出预览</button>
    </div>
    <Toast />
    <ConfirmHost />
    <ResultHost />
  </div>
</template>
