<script setup>
import { ref, onMounted, reactive } from 'vue'
import api from '../api/index.js'

const users = ref([])
const loading = ref(false)
const showModal = ref(false)
const editUser = ref(null)
const error = ref('')
const success = ref('')

const ROLES = [
  { v: 'super_admin', label: '超级管理员' },
  { v: 'manager', label: '经理' },
  { v: 'operator', label: '操作员' },
  { v: 'viewer', label: '查看员' },
]

const ROLE_LABELS = { super_admin: '超级管理员', manager: '经理', operator: '操作员', viewer: '查看员' }

const form = reactive({ phone: '', password: '', name: '', role: 'operator', departments: '', is_active: true })

async function load() {
  loading.value = true
  try {
    const res = await api.get('/users')
    users.value = res.data
  } finally { loading.value = false }
}

onMounted(load)

function openAdd() {
  editUser.value = null
  Object.assign(form, { phone: '', password: '', name: '', role: 'operator', departments: '', is_active: true })
  error.value = ''; success.value = ''
  showModal.value = true
}

function openEdit(u) {
  editUser.value = u
  Object.assign(form, {
    phone: u.phone, password: '', name: u.name,
    role: u.role, departments: (u.departments || []).join(','), is_active: u.is_active,
  })
  error.value = ''; success.value = ''
  showModal.value = true
}

function parseDepts(str) {
  return str.split(/[,，\s]+/).map(s => s.trim()).filter(Boolean)
}

async function saveUser() {
  error.value = ''
  try {
    const payload = {
      phone: form.phone,
      name: form.name,
      role: form.role,
      departments: parseDepts(form.departments),
      is_active: form.is_active,
    }
    if (form.password) payload.password = form.password
    if (editUser.value) {
      await api.put(`/users/${editUser.value.id}`, payload)
    } else {
      if (!form.password) { error.value = '新用户必须设置密码'; return }
      await api.post('/users', { ...payload })
    }
    showModal.value = false
    load()
  } catch (e) {
    error.value = e?.error || '操作失败'
  }
}

async function deactivate(u) {
  if (!confirm(`确定停用「${u.name}」的账号？`)) return
  try {
    await api.delete(`/users/${u.id}`)
    load()
  } catch (e) {
    alert(e?.error || '操作失败')
  }
}
</script>

<template>
  <div>
    <div class="topbar">
      <h1>用户管理</h1>
      <button class="btn btn-primary" @click="openAdd">+ 新增用户</button>
    </div>

    <div class="card">
      <div v-if="loading" class="empty"><div class="icon">⏳</div>加载中…</div>
      <div v-else-if="!users.length" class="empty"><div class="icon">👤</div>暂无用户</div>
      <div v-else class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>姓名</th>
              <th>手机号</th>
              <th>角色</th>
              <th>负责部门</th>
              <th>状态</th>
              <th>创建时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="u in users" :key="u.id">
              <td><strong>{{ u.name }}</strong></td>
              <td>{{ u.phone }}</td>
              <td><span :class="`badge badge-${u.role}`">{{ ROLE_LABELS[u.role] }}</span></td>
              <td>
                <span v-if="u.role==='super_admin'||u.role==='manager'" style="color:var(--muted);font-size:12px">全部</span>
                <span v-else-if="u.departments?.length">{{ u.departments.join('、') }}</span>
                <span v-else style="color:var(--muted)">未分配</span>
              </td>
              <td>
                <span :style="u.is_active?'color:#2e7d32':'color:#c62828'">
                  {{ u.is_active ? '● 启用' : '○ 停用' }}
                </span>
              </td>
              <td style="font-size:12px;color:var(--muted)">{{ u.created_at?.slice(0, 10) }}</td>
              <td>
                <div style="display:flex;gap:6px">
                  <button class="btn btn-ghost btn-sm" @click="openEdit(u)">编辑</button>
                  <button v-if="u.is_active" class="btn btn-danger btn-sm" @click="deactivate(u)">停用</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- modal -->
    <div v-if="showModal" class="overlay" @click.self="showModal=false">
      <div class="modal" style="width:480px">
        <div class="modal-header">
          <h3>{{ editUser ? '编辑用户' : '新增用户' }}</h3>
          <button class="modal-close" @click="showModal=false">×</button>
        </div>

        <div v-if="error" class="alert alert-err">{{ error }}</div>

        <div class="form-row">
          <div class="form-group">
            <label>手机号 *</label>
            <input v-model="form.phone" type="tel" :disabled="!!editUser" placeholder="手机号" />
          </div>
          <div class="form-group">
            <label>{{ editUser ? '新密码（留空不改）' : '密码 *' }}</label>
            <input v-model="form.password" type="password" placeholder="至少6位" />
          </div>
        </div>

        <div class="form-row">
          <div class="form-group">
            <label>姓名 *</label>
            <input v-model="form.name" placeholder="姓名" />
          </div>
          <div class="form-group">
            <label>角色 *</label>
            <select v-model="form.role">
              <option v-for="r in ROLES" :key="r.v" :value="r.v">{{ r.label }}</option>
            </select>
          </div>
        </div>

        <div class="form-row full">
          <div class="form-group">
            <label>负责部门（逗号分隔，经理/管理员留空即可）</label>
            <input v-model="form.departments" placeholder="如: 采购部,财务部" />
          </div>
        </div>

        <div class="form-group" style="margin-bottom:8px">
          <label style="display:flex;align-items:center;gap:8px;font-size:14px">
            <input type="checkbox" v-model="form.is_active" style="width:auto" />
            账号启用
          </label>
        </div>

        <div class="modal-footer">
          <button class="btn btn-ghost" @click="showModal=false">取消</button>
          <button class="btn btn-primary" @click="saveUser">保存</button>
        </div>
      </div>
    </div>
  </div>
</template>
