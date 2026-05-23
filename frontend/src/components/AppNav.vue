<script setup>
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth.js'

const router = useRouter()
const auth = useAuthStore()

function logout() {
  auth.logout()
  router.push('/login')
}

const ROLE_LABELS = {
  super_admin: '超级管理员',
  manager: '经理',
  operator: '操作员',
  viewer: '查看员',
}
</script>

<template>
  <nav class="sidebar">
    <div class="sidebar-brand">
      <span class="brand-icon">💸</span>
      <span class="brand-name">排款系统</span>
    </div>

    <div class="nav-links">
      <router-link to="/dashboard" class="nav-item" active-class="active">
        <span class="icon">📊</span> 今日工作台
      </router-link>
      <router-link to="/payments" class="nav-item" active-class="active">
        <span class="icon">📋</span> 付款台账
      </router-link>
      <router-link to="/stats" class="nav-item" active-class="active">
        <span class="icon">📈</span> 月度统计
      </router-link>
      <router-link v-if="auth.isSuperAdmin" to="/users" class="nav-item" active-class="active">
        <span class="icon">👥</span> 用户管理
      </router-link>
    </div>

    <div class="sidebar-footer">
      <div class="user-info">
        <div class="user-name">{{ auth.user?.name }}</div>
        <div class="user-role">
          <span :class="`badge badge-${auth.user?.role}`">{{ ROLE_LABELS[auth.user?.role] }}</span>
        </div>
      </div>
      <button class="logout-btn" @click="logout">退出</button>
    </div>
  </nav>
</template>

<style scoped>
.sidebar {
  width: var(--nav-w);
  background: linear-gradient(180deg, #2d1810 0%, #1a0e08 100%);
  color: #e8d4c4;
  display: flex;
  flex-direction: column;
  position: fixed;
  top: 0; left: 0; bottom: 0;
  z-index: 50;
}

.sidebar-brand {
  padding: 24px 20px 20px;
  display: flex; align-items: center; gap: 10px;
  border-bottom: 1px solid rgba(255,255,255,0.08);
}
.brand-icon { font-size: 22px; }
.brand-name { font-size: 17px; font-weight: 700; color: #fff; }

.nav-links { flex: 1; padding: 12px 10px; display: flex; flex-direction: column; gap: 4px; }

.nav-item {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 12px; border-radius: 8px;
  color: #c4a898; font-size: 14px; font-weight: 500;
  transition: all .2s;
}
.nav-item:hover { background: rgba(255,255,255,0.08); color: #fff; }
.nav-item.active { background: var(--grad); color: #fff; }
.icon { font-size: 16px; }

.sidebar-footer {
  padding: 16px;
  border-top: 1px solid rgba(255,255,255,0.08);
}
.user-name { font-weight: 600; color: #fff; font-size: 14px; margin-bottom: 4px; }
.user-role { margin-bottom: 10px; }
.logout-btn {
  width: 100%; padding: 8px; border-radius: 8px;
  background: rgba(255,255,255,0.1); border: none; color: #c4a898;
  font-size: 13px; transition: all .2s;
}
.logout-btn:hover { background: rgba(255,255,255,0.18); color: #fff; }
</style>
