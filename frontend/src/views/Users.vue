<script setup>
import { ref, onMounted, computed } from 'vue'
import api from '../api/index.js'

const users = ref([])
const loading = ref(false)
const tab = ref('all')  // 'pending' | 'all'
const showEditModal = ref(false)
const editUser = ref(null)
const error = ref('')
const approveLoading = ref({})

const JOB_LABELS = {
  finance_director: '财务总监', finance_bp: '财务BP', chief_cashier: '总出纳', cashier: '出纳',
}
const ROLE_LABELS = {
  super_admin: '超级管理员', manager: '财务经理', operator: '成员', viewer: '查看员',
}
const JOB_OPTIONS = [
  { v: 'finance_director', label: '财务总监' },
  { v: 'finance_bp', label: '财务BP' },
  { v: 'chief_cashier', label: '总出纳' },
  { v: 'cashier', label: '出纳' },
]

// per-pending-user approval edits
const approveJob = ref({})
const approveDepts = ref({})

const editForm = ref({ name: '', job_title: '', departments: [], is_active: true, password: '' })

const DEPARTMENTS = [
  '集团总部', '劳务事业部', '运输事业部', '自营事业部',
  '阔展事业部', '多式联运事业部', '供应链事业部',
]

const pendingUsers = computed(() => users.value.filter(u => !u.is_approved && u.role !== 'super_admin'))
const activeUsers  = computed(() => users.value.filter(u => u.is_approved || u.role === 'super_admin'))
const displayUsers = computed(() => tab.value === 'pending' ? pendingUsers.value : activeUsers.value)

async function load() {
  loading.value = true
  try {
    const res = await api.get('/users')
    users.value = res.data
    for (const u of users.value) {
      if (!u.is_approved && u.role !== 'super_admin') {
        if (!(u.id in approveJob.value)) approveJob.value[u.id] = u.job_title || 'cashier'
        if (!(u.id in approveDepts.value)) approveDepts.value[u.id] = [...(u.departments || [])]
      }
    }
  } finally { loading.value = false }
}

function toggleApproveDept(uid, d) {
  const arr = approveDepts.value[uid] || (approveDepts.value[uid] = [])
  const i = arr.indexOf(d)
  if (i === -1) arr.push(d)
  else arr.splice(i, 1)
}

onMounted(load)

function openEdit(u) {
  editUser.value = u
  editForm.value = {
    name: u.name,
    job_title: u.job_title || '',
    departments: [...(u.departments || [])],
    is_active: u.is_active,
    password: '',
  }
  error.value = ''
  showEditModal.value = true
}

function toggleEditDept(d) {
  const idx = editForm.value.departments.indexOf(d)
  if (idx === -1) editForm.value.departments.push(d)
  else editForm.value.departments.splice(idx, 1)
}

async function saveEdit() {
  error.value = ''
  try {
    const payload = {
      name: editForm.value.name,
      job_title: editForm.value.job_title,
      departments: editForm.value.departments,
      is_active: editForm.value.is_active,
    }
    if (editForm.value.password) payload.password = editForm.value.password
    await api.put(`/users/${editUser.value.id}`, payload)
    showEditModal.value = false
    load()
  } catch (e) {
    error.value = e?.error || '操作失败'
  }
}

async function deactivate(u) {
  if (!confirm(`确定停用「${u.name}」的账号？停用后该用户将无法登录。`)) return
  try {
    await api.delete(`/users/${u.id}`)
    load()
  } catch (e) {
    alert(e?.error || '操作失败')
  }
}

async function approve(u) {
  approveLoading.value[u.id] = true
  try {
    await api.post(`/users/${u.id}/approve`, {
      job_title: approveJob.value[u.id] || u.job_title,
      departments: approveDepts.value[u.id] || u.departments || [],
    })
    load()
  } catch (e) {
    alert(e?.error || '审批失败')
  } finally {
    approveLoading.value[u.id] = false
  }
}

async function reject(u) {
  if (!confirm(`确定拒绝「${u.name}」的注册申请？拒绝后该申请将被删除。`)) return
  try {
    await api.post(`/users/${u.id}/reject`, {})
    load()
  } catch (e) {
    alert(e?.error || '操作失败')
  }
}
</script>

<template>
  <div>
    <div class="topbar">
      <div>
        <h1>用户管理</h1>
        <div style="font-size:13px;color:var(--muted);margin-top:2px">
          审批注册申请 · 编辑用户信息 · 停用账号
        </div>
      </div>
      <div v-if="pendingUsers.length" class="pending-badge">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
        </svg>
        {{ pendingUsers.length }} 人待审批
      </div>
    </div>

    <!-- tabs -->
    <div class="tabs">
      <button :class="['tab', tab === 'pending' ? 'active' : '']" @click="tab = 'pending'">
        待审批
        <span v-if="pendingUsers.length" class="tab-count">{{ pendingUsers.length }}</span>
      </button>
      <button :class="['tab', tab === 'all' ? 'active' : '']" @click="tab = 'all'">
        已审批用户
      </button>
    </div>

    <div class="card">
      <div v-if="loading" class="empty"><div class="icon">⏳</div>加载中…</div>

      <!-- PENDING TAB -->
      <template v-else-if="tab === 'pending'">
        <div v-if="!pendingUsers.length" class="empty">
          <div class="icon">✅</div>暂无待审批申请
        </div>
        <div v-else class="pending-list">
          <div v-for="u in pendingUsers" :key="u.id" class="pending-card">
            <div class="pending-info">
              <div class="pa-avatar">{{ u.name[0] }}</div>
              <div style="flex:1;min-width:0">
                <div class="pa-name">{{ u.name }}</div>
                <div class="pa-sub">
                  {{ u.phone }}
                  <span v-if="u.job_title" class="pa-chip">申请职务：{{ JOB_LABELS[u.job_title] || u.job_title }}</span>
                </div>
                <div class="pa-time">申请时间 {{ u.created_at?.slice(0, 10) }}</div>

                <!-- approval config -->
                <div class="approve-cfg">
                  <div class="cfg-line">
                    <span class="cfg-label">职务</span>
                    <select class="role-select" v-model="approveJob[u.id]">
                      <option v-for="j in JOB_OPTIONS" :key="j.v" :value="j.v">{{ j.label }}</option>
                    </select>
                  </div>
                  <div class="cfg-line" style="align-items:flex-start">
                    <span class="cfg-label" style="margin-top:5px">负责部门</span>
                    <div class="dept-pick">
                      <label v-for="d in DEPARTMENTS" :key="d"
                        class="dept-mini" :class="{ on: (approveDepts[u.id] || []).includes(d) }"
                        @click="toggleApproveDept(u.id, d)">{{ d }}</label>
                    </div>
                  </div>
                </div>
              </div>
            </div>
            <div class="pending-actions">
              <button
                class="btn btn-success btn-sm"
                :disabled="approveLoading[u.id]"
                @click="approve(u)"
              >
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                  <polyline points="20 6 9 17 4 12"/>
                </svg>
                通过
              </button>
              <button class="btn btn-danger btn-sm" :disabled="approveLoading[u.id]" @click="reject(u)">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                  <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
                </svg>
                拒绝
              </button>
            </div>
          </div>
        </div>
      </template>

      <!-- ALL APPROVED TAB -->
      <template v-else>
        <div v-if="!activeUsers.length" class="empty"><div class="icon">👤</div>暂无用户</div>
        <div v-else class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>用户</th>
                <th>手机号</th>
                <th>角色</th>
                <th>职务</th>
                <th>负责部门</th>
                <th>状态</th>
                <th>创建时间</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="u in activeUsers" :key="u.id">
                <td>
                  <div style="display:flex;align-items:center;gap:8px">
                    <div class="table-avatar">{{ u.name[0] }}</div>
                    <strong>{{ u.name }}</strong>
                  </div>
                </td>
                <td style="color:var(--muted)">{{ u.phone }}</td>
                <td><span :class="`badge badge-${u.role}`">{{ ROLE_LABELS[u.role] }}</span></td>
                <td>{{ JOB_LABELS[u.job_title] || '—' }}</td>
                <td>
                  <span v-if="u.role==='super_admin'||u.role==='manager'" style="color:var(--muted);font-size:12px">全部</span>
                  <span v-else-if="u.departments?.length" style="font-size:12px">{{ u.departments.join('、') }}</span>
                  <span v-else style="color:var(--muted)">—</span>
                </td>
                <td>
                  <span :style="u.is_active?'color:#2e7d32;font-weight:600':'color:#c62828'">
                    {{ u.is_active ? '● 启用' : '○ 停用' }}
                  </span>
                </td>
                <td style="font-size:12px;color:var(--muted)">{{ u.created_at?.slice(0, 10) }}</td>
                <td>
                  <div style="display:flex;gap:6px">
                    <button class="btn btn-ghost btn-sm" @click="openEdit(u)">编辑</button>
                    <button v-if="u.is_active && u.role !== 'super_admin'" class="btn btn-danger btn-sm" @click="deactivate(u)">停用</button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
    </div>

    <!-- Edit modal -->
    <div v-if="showEditModal" class="overlay" @click.self="showEditModal=false">
      <div class="modal" style="width:520px">
        <div class="modal-header">
          <h3>编辑用户 — {{ editUser?.name }}</h3>
          <button class="modal-close" @click="showEditModal=false">×</button>
        </div>

        <div v-if="error" class="alert alert-err">{{ error }}</div>

        <div class="form-row">
          <div class="form-group">
            <label>手机号</label>
            <input :value="editUser?.phone" disabled style="opacity:0.5" />
          </div>
          <div class="form-group">
            <label>新密码（留空不修改）</label>
            <input v-model="editForm.password" type="password" placeholder="至少6位" />
          </div>
        </div>

        <div class="form-row">
          <div class="form-group">
            <label>姓名 *</label>
            <input v-model="editForm.name" />
          </div>
          <div class="form-group">
            <label>账号角色</label>
            <input :value="ROLE_LABELS[editUser?.role] || '成员'" disabled style="opacity:0.6" />
          </div>
        </div>

        <div class="form-group" style="margin-bottom:14px">
          <label>职务（决定该用户的权限）</label>
          <div class="radio-group">
            <label v-for="jt in JOB_OPTIONS" :key="jt.v"
              class="radio-item" :class="{ selected: editForm.job_title === jt.v }">
              <input type="radio" v-model="editForm.job_title" :value="jt.v" style="display:none" />
              {{ jt.label }}
            </label>
          </div>
        </div>

        <div class="form-group" style="margin-bottom:14px">
          <label>负责部门</label>
          <div class="check-group">
            <label v-for="d in DEPARTMENTS" :key="d"
              class="check-item" :class="{ selected: editForm.departments.includes(d) }"
              @click="toggleEditDept(d)">
              <span class="check-box">
                <svg v-if="editForm.departments.includes(d)" width="10" height="10" viewBox="0 0 12 12" fill="none">
                  <path d="M2 6l3 3 5-5" stroke="white" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
              </span>
              {{ d }}
            </label>
          </div>
        </div>

        <div class="form-group" style="margin-bottom:8px">
          <label style="display:flex;align-items:center;gap:8px;font-size:14px;cursor:pointer">
            <input type="checkbox" v-model="editForm.is_active" style="width:auto;accent-color:var(--primary)" />
            账号启用
          </label>
        </div>

        <div class="modal-footer">
          <button class="btn btn-ghost" @click="showEditModal=false">取消</button>
          <button class="btn btn-primary" @click="saveEdit">保存</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.pending-badge {
  display: flex; align-items: center; gap: 6px;
  padding: 7px 14px; border-radius: 20px;
  background: rgba(245,127,23,0.12); color: #e65100;
  font-size: 13px; font-weight: 600;
  border: 1px solid rgba(245,127,23,0.25);
  animation: pulse 2s ease-in-out infinite;
}
@keyframes pulse { 0%,100%{box-shadow:0 0 0 0 rgba(245,127,23,0.2)} 50%{box-shadow:0 0 0 6px rgba(245,127,23,0)} }

.tab-count {
  display: inline-flex; align-items: center; justify-content: center;
  width: 18px; height: 18px; border-radius: 50%;
  background: rgba(245,127,23,0.2); color: #e65100;
  font-size: 10px; font-weight: 700; margin-left: 4px;
}

.pending-list { display: flex; flex-direction: column; gap: 12px; }
.pending-card {
  display: flex; align-items: center; justify-content: space-between; gap: 16px;
  padding: 16px 18px; border-radius: 12px;
  background: rgba(245,127,23,0.05);
  border: 1px solid rgba(245,127,23,0.15);
  transition: all 0.2s;
}
.pending-card:hover { background: rgba(245,127,23,0.08); }
.pending-info { display: flex; align-items: flex-start; gap: 12px; flex: 1; min-width: 0; }
.pa-avatar {
  width: 40px; height: 40px; border-radius: 12px; flex-shrink: 0;
  background: linear-gradient(135deg, #e8a84a, #c96342);
  display: flex; align-items: center; justify-content: center;
  color: #fff; font-weight: 700; font-size: 17px;
}
.pa-name { font-weight: 700; font-size: 14px; }
.pa-sub { font-size: 12px; color: var(--muted); display: flex; align-items: center; gap: 6px; margin-top: 2px; }
.pa-chip {
  background: rgba(21,101,192,0.1); color: #1565c0;
  border-radius: 10px; padding: 1px 7px; font-size: 11px; font-weight: 600;
}
.pa-depts { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px; }
.dept-chip {
  background: rgba(201,99,66,0.1); color: var(--primary);
  border-radius: 10px; padding: 2px 8px; font-size: 11px;
}
.pa-time { font-size: 11px; color: rgba(155,128,112,0.65); margin-top: 4px; }

.pending-actions {
  display: flex; flex-direction: column; align-items: stretch; gap: 8px; flex-shrink: 0;
  min-width: 96px;
}
.role-select {
  width: auto; min-width: 110px; padding: 5px 8px;
  font-size: 12px; border-radius: 7px;
}

.approve-cfg {
  margin-top: 10px; padding-top: 10px;
  border-top: 1px dashed rgba(245,127,23,0.25);
  display: flex; flex-direction: column; gap: 8px;
}
.cfg-line { display: flex; align-items: center; gap: 10px; }
.cfg-label { font-size: 12px; color: var(--muted); width: 56px; flex-shrink: 0; }
.dept-pick { display: flex; flex-wrap: wrap; gap: 5px; }
.dept-mini {
  padding: 3px 9px; border-radius: 14px; font-size: 11px; cursor: pointer;
  border: 1.5px solid var(--border); background: rgba(255,253,250,0.7);
  transition: all 0.16s; user-select: none;
}
.dept-mini.on {
  border-color: var(--primary); background: rgba(201,99,66,0.1);
  color: var(--primary); font-weight: 600;
}

.table-avatar {
  width: 28px; height: 28px; border-radius: 8px; flex-shrink: 0;
  background: linear-gradient(135deg, #c96342, #a84e32);
  display: flex; align-items: center; justify-content: center;
  color: #fff; font-weight: 700; font-size: 12px;
}

.radio-group { display: flex; gap: 8px; flex-wrap: wrap; }
.radio-item {
  display: flex; align-items: center; gap: 6px;
  padding: 6px 13px; border-radius: 20px;
  border: 1.5px solid var(--border);
  background: rgba(255,253,250,0.7);
  font-size: 13px; cursor: pointer; transition: all 0.18s;
}
.radio-item.selected {
  border-color: var(--primary);
  background: rgba(201,99,66,0.08);
  color: var(--primary); font-weight: 600;
}

.check-group { display: flex; flex-wrap: wrap; gap: 7px; }
.check-item {
  display: flex; align-items: center; gap: 6px;
  padding: 5px 11px; border-radius: 20px;
  border: 1.5px solid var(--border);
  background: rgba(255,253,250,0.7);
  font-size: 12px; cursor: pointer; transition: all 0.18s; user-select: none;
}
.check-item.selected {
  border-color: var(--primary);
  background: rgba(201,99,66,0.1);
  color: var(--primary); font-weight: 600;
}
.check-box {
  width: 14px; height: 14px; border-radius: 4px;
  border: 1.5px solid currentColor;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0; transition: background 0.15s;
}
.check-item.selected .check-box { background: var(--primary); border-color: var(--primary); }
</style>
