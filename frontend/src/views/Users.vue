<script setup>
import { ref, reactive, onMounted, computed } from 'vue'
import api from '../api/index.js'
import { DEPARTMENTS, ROLE_LABELS, JOB_LABELS, JOB_OPTIONS } from '../constants.js'
import EmptyState from '../components/EmptyState.vue'
import ColumnFilter from '../components/ColumnFilter.vue'
import SkeletonRow from '../components/SkeletonRow.vue'
import SchemePicker from '../components/SchemePicker.vue'
import { useToast } from '../composables/useToast.js'
import { useTableSchemes } from '../composables/useTableSchemes.js'
import { useAuthStore } from '../stores/auth.js'

const toast = useToast()
const auth = useAuthStore()

// ── 列头筛选 + 排序（客户端，全部用户已一次性加载，无服务端分页）──────────────
const colFilters = reactive({})
const sortField = ref('')
const sortOrder = ref('')

const ROLE_OPTIONS = Object.entries(ROLE_LABELS).map(([value, label]) => ({ value, label }))
const JOBTITLE_OPTIONS = JOB_OPTIONS.map(jt => ({ value: jt.v, label: jt.label }))
const STATUS_OPTIONS = [{ value: 'active', label: '在用' }, { value: 'inactive', label: '停用' }]

const USER_COL_META = {
  name:        { type: 'text', get: u => u.name },
  phone:       { type: 'text', get: u => u.phone },
  role:        { type: 'enum', get: u => u.role },
  job_title:   { type: 'enum', get: u => u.job_title },
  departments: { type: 'enum', get: u => u.departments || [] },
  status:      { type: 'enum', get: u => (u.is_active ? 'active' : 'inactive') },
  created_at:  { type: 'date', get: u => u.created_at },
}

function clauseMatch(val, clause, type) {
  if (!clause || !clause.op) return true
  const v = clause.value
  if (type === 'enum') { // v is array of selected
    if (!Array.isArray(v) || !v.length) return true
    return Array.isArray(val) ? val.some(x => v.includes(x)) : v.includes(val)
  }
  if (type === 'date') {
    const d = String(val || '').slice(0, 10); const [s, e] = Array.isArray(v) ? v : []
    if (s && d < s) return false; if (e && d > e) return false; return true
  }
  if (type === 'number') {
    const n = parseFloat(val); if (isNaN(n)) return false
    if (clause.op === 'between') { const [a, b] = Array.isArray(v) ? v : []; if (a !== '' && a != null && n < parseFloat(a)) return false; if (b !== '' && b != null && n > parseFloat(b)) return false; return true }
    const t = parseFloat(v); if (isNaN(t)) return true
    return { eq: n === t, gt: n > t, lt: n < t, gte: n >= t, lte: n <= t }[clause.op] ?? true
  }
  const s = String(val ?? '').toLowerCase(); const q = String(v ?? '').toLowerCase()
  return clause.op === 'eq' ? s === q : s.includes(q)
}

function setColFilter(field, val) {
  if (val && val.op) colFilters[field] = val
  else delete colFilters[field]
}

function setSort(field, order) {
  sortField.value = order ? field : ''
  sortOrder.value = order || ''
}

// 通用筛选方案（表格方案基座）：列头筛选 + 排序存成命名方案。
// 本页为客户端筛选（displayActiveUsers 计算属性自动响应 colFilters/sort），
// 套用方案直接改这些响应式状态即可，无需重新拉取数据。
const schemes = useTableSchemes('pk_users', {
  colFilters, sortField, sortOrder,
  onApply: () => {},
})

function clearColFilters() {
  for (const k of Object.keys(colFilters)) delete colFilters[k]
  sortField.value = ''
  sortOrder.value = ''
}

const hasColFilters = computed(() => Object.keys(colFilters).length > 0 || !!sortField.value)

const users = ref([])
const loading = ref(false)
const tab = ref('all')  // 'pending' | 'all'
const showEditModal = ref(false)
const editUser = ref(null)
const error = ref('')
const approveLoading = ref({})


// per-pending-user approval edits
const approveJob = ref({})
const approveDepts = ref({})

const editForm = ref({ name: '', job_title: '', departments: [], is_active: true, password: '' })

// IDs deleted in this session — guard against any cache/proxy layer resurrecting
// a hard-deleted user on a subsequent reload. IDs are autoincrement, never reused.
const deletedIds = new Set()


const pendingUsers = computed(() => users.value.filter(u => !u.is_approved && u.role !== 'super_admin'))
const activeUsers  = computed(() => users.value.filter(u => u.is_approved || u.role === 'super_admin'))
const displayUsers = computed(() => tab.value === 'pending' ? pendingUsers.value : activeUsers.value)

const displayActiveUsers = computed(() => {
  let arr = activeUsers.value.filter(u =>
    Object.entries(colFilters).every(([f, c]) => clauseMatch(USER_COL_META[f].get(u), c, USER_COL_META[f].type)))
  if (sortField.value) {
    const meta = USER_COL_META[sortField.value]
    arr = [...arr].sort((a, b) => {
      let x = meta.get(a), y = meta.get(b)
      if (Array.isArray(x)) x = x.join(','); if (Array.isArray(y)) y = y.join(',')
      x = x ?? ''; y = y ?? ''
      return (x > y ? 1 : x < y ? -1 : 0) * (sortOrder.value === 'desc' ? -1 : 1)
    })
  }
  return arr
})

async function load() {
  loading.value = true
  try {
    // cache-bust so a freshly deleted/approved user can't be served from cache
    const res = await api.get('/users', { params: { _t: Date.now() } })
    users.value = res.data.filter(u => !deletedIds.has(u.id))
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

onMounted(async () => {
  const applied = await schemes.loadAndApplyDefault()
  if (!applied) load()
})

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
  if (!editForm.value.name.trim()) { error.value = '姓名不能为空'; return }
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
  if (!confirm(`确认删除用户「${u.name}」？此操作不可撤销。`)) return
  const typed = window.prompt(`请输入用户名「${u.name}」以确认删除：`)
  if (typed !== u.name) { toast.warn('输入不匹配，已取消'); return }
  try {
    await api.delete(`/users/${u.id}`)
    deletedIds.add(u.id)                                    // never let it reappear
    users.value = users.value.filter(x => x.id !== u.id)  // instant feedback
    await load()                                            // reconcile with server truth
  } catch (e) {
    toast.warn(e?.error || '操作失败')
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
    toast.warn(e?.error || '审批失败')
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
    toast.warn(e?.error || '操作失败')
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
      <button v-if="tab === 'all' && hasColFilters" class="btn btn-ghost btn-sm clear-filters-btn" @click="clearColFilters">
        清除全部筛选
      </button>
      <SchemePicker v-if="tab === 'all'" :ctl="schemes" :can-public="true" :is-super-admin="true" :class="{ 'scheme-picker-push': !hasColFilters }" />
    </div>

    <div class="card fh-fill">
      <EmptyState v-if="loading" loading />

      <!-- PENDING TAB -->
      <template v-else-if="tab === 'pending'">
        <EmptyState v-if="!pendingUsers.length" icon="✅" text="暂无待审批申请" />
        <div v-else class="pending-list">
          <div v-for="u in pendingUsers" :key="u.id" class="pending-card">
            <div class="pending-info">
              <div class="pa-avatar">{{ u.name?.[0] || '?' }}</div>
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
        <EmptyState v-if="!activeUsers.length" icon="👤" text="暂无用户" />
        <div v-else class="table-wrap page-scroll">
          <table>
            <thead>
              <tr>
                <th><ColumnFilter label="用户" field="name" type="text" :model-value="colFilters.name" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('name',v)" @sort="o=>setSort('name',o)" /></th>
                <th><ColumnFilter label="手机号" field="phone" type="text" :model-value="colFilters.phone" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('phone',v)" @sort="o=>setSort('phone',o)" /></th>
                <th><ColumnFilter label="角色" field="role" type="enum" :options="ROLE_OPTIONS" :model-value="colFilters.role" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('role',v)" @sort="o=>setSort('role',o)" /></th>
                <th><ColumnFilter label="职务" field="job_title" type="enum" :options="JOBTITLE_OPTIONS" :model-value="colFilters.job_title" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('job_title',v)" @sort="o=>setSort('job_title',o)" /></th>
                <th><ColumnFilter label="负责部门" field="departments" type="enum" :options="DEPARTMENTS" :model-value="colFilters.departments" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('departments',v)" @sort="o=>setSort('departments',o)" /></th>
                <th><ColumnFilter label="状态" field="status" type="enum" :options="STATUS_OPTIONS" :model-value="colFilters.status" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('status',v)" @sort="o=>setSort('status',o)" /></th>
                <th><ColumnFilter label="创建时间" field="created_at" type="date" :model-value="colFilters.created_at" :sort-field="sortField" :sort-order="sortOrder" @update:model-value="v=>setColFilter('created_at',v)" @sort="o=>setSort('created_at',o)" /></th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <template v-if="loading">
                <SkeletonRow v-for="n in 8" :key="n" :cols="7" />
              </template>
              <template v-else>
              <tr v-for="u in displayActiveUsers" :key="u.id">
                <td>
                  <div style="display:flex;align-items:center;gap:8px">
                    <div class="table-avatar">{{ u.name?.[0] || '?' }}</div>
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
                    <button v-if="u.role !== 'super_admin'" class="btn btn-danger btn-sm" @click="deactivate(u)">删除</button>
                  </div>
                </td>
              </tr>
              </template>
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
  transition: all 0.16s; user-select: none; margin-bottom: 4px;
}
.dept-mini.on {
  border-color: var(--primary); background: rgba(201,99,66,0.1);
  color: var(--primary); font-weight: 600;
}

/* 列头筛选漏斗不被裁剪 */
.table-wrap thead th { overflow: visible; }
/* sticky header while body scrolls (fixed-viewport layout) */
.table-wrap thead th { position: sticky; top: 0; z-index: 5; background: #f4f1ef; }
.clear-filters-btn { margin-left: auto; align-self: center; }
.scheme-picker-push { margin-left: auto; }

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
