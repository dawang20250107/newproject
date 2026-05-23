<script setup>
import { ref, onMounted, reactive } from 'vue'
import api from '../api/index.js'
import { useAuthStore } from '../stores/auth.js'
import StatusBadge from '../components/StatusBadge.vue'
import PaymentModal from '../components/PaymentModal.vue'

const auth = useAuthStore()
const items = ref([])
const total = ref(0)
const loading = ref(false)
const departments = ref([])
const showModal = ref(false)
const editItem = ref(null)

const filters = reactive({
  q: '', dept: '', status: '', start_date: '', end_date: '',
  page: 1, size: 50,
})

function fmt(n) {
  const v = parseFloat(n || 0)
  return v >= 10000 ? (v / 10000).toFixed(2) + ' 万' : v.toFixed(2)
}

async function load() {
  loading.value = true
  try {
    const params = Object.fromEntries(Object.entries(filters).filter(([, v]) => v !== ''))
    const res = await api.get('/payments', { params })
    items.value = res.data.items
    total.value = res.data.total
  } finally {
    loading.value = false
  }
}

async function loadDepts() {
  try {
    const res = await api.get('/departments')
    departments.value = res.data
  } catch {}
}

onMounted(() => { load(); loadDepts() })

function openAdd() { editItem.value = null; showModal.value = true }
function openEdit(p) { editItem.value = p; showModal.value = true }

function onSaved(p) {
  showModal.value = false
  load()
  loadDepts()
}

async function onDelete(p) {
  if (!confirm(`确定删除「${p.project_desc}」？此操作不可撤销。`)) return
  try {
    await api.delete(`/payments/${p.id}`)
    load()
  } catch (e) {
    alert(e?.error || '删除失败')
  }
}

function search() { filters.page = 1; load() }
function resetFilters() {
  Object.assign(filters, { q: '', dept: '', status: '', start_date: '', end_date: '', page: 1 })
  load()
}

const totalPages = ref(0)
function setPage(p) { filters.page = p; load() }
</script>

<template>
  <div>
    <div class="topbar">
      <h1>付款台账</h1>
      <button v-if="auth.canWrite" class="btn btn-primary" @click="openAdd">+ 新增排款</button>
    </div>

    <div class="card" style="margin-bottom:16px">
      <div class="filter-bar">
        <input v-model="filters.q" placeholder="搜索事项/收款方/单号…" style="min-width:200px" @keyup.enter="search" />
        <select v-model="filters.dept" @change="search">
          <option value="">全部部门</option>
          <option v-for="d in departments" :key="d" :value="d">{{ d }}</option>
        </select>
        <select v-model="filters.status" @change="search">
          <option value="">全部状态</option>
          <option value="pending">⏳ 待付款</option>
          <option value="partial">⚡ 部分付款</option>
          <option value="settled">✅ 已付清</option>
        </select>
        <input v-model="filters.start_date" type="date" style="min-width:130px" @change="search" />
        <input v-model="filters.end_date" type="date" style="min-width:130px" @change="search" />
        <button class="btn btn-ghost btn-sm" @click="search">筛选</button>
        <button class="btn btn-sm" style="background:var(--bg2);border:none" @click="resetFilters">重置</button>
      </div>

      <div style="font-size:13px;color:var(--muted);margin-bottom:8px">共 {{ total }} 条记录</div>

      <div v-if="loading" class="empty"><div class="icon">⏳</div>加载中…</div>

      <div v-else-if="!items.length" class="empty">
        <div class="icon">📭</div>暂无数据
      </div>

      <div v-else class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>部门</th>
              <th>审批单号</th>
              <th>付款事项</th>
              <th>收款方</th>
              <th>计划日期</th>
              <th>计划总额 (元)</th>
              <th>已付 (元)</th>
              <th>剩余 (元)</th>
              <th>状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="p in items" :key="p.id">
              <td>{{ p.department }}</td>
              <td>{{ p.approval_number || '—' }}</td>
              <td style="max-width:200px;white-space:normal;word-break:break-all">{{ p.project_desc }}</td>
              <td>{{ p.payee }}</td>
              <td>{{ p.planned_date }}</td>
              <td class="amt">{{ fmt(p.total_amount) }}</td>
              <td class="amt amt-green">{{ fmt(p.total_paid) }}</td>
              <td class="amt" :class="parseFloat(p.remaining) > 0 ? 'amt-red' : ''">{{ fmt(p.remaining) }}</td>
              <td><StatusBadge :status="p.status" /></td>
              <td>
                <div style="display:flex;gap:6px">
                  <button v-if="auth.canWrite" class="btn btn-ghost btn-sm" @click="openEdit(p)">编辑</button>
                  <button v-if="auth.isSuperAdmin" class="btn btn-danger btn-sm" @click="onDelete(p)">删除</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- pagination -->
      <div class="pagination">
        <span>第 {{ filters.page }} 页，共 {{ Math.ceil(total / filters.size) || 1 }} 页</span>
        <button :disabled="filters.page <= 1" @click="setPage(filters.page - 1)">上一页</button>
        <button :disabled="filters.page * filters.size >= total" @click="setPage(filters.page + 1)">下一页</button>
      </div>
    </div>

    <PaymentModal
      v-if="showModal"
      :payment="editItem"
      :departments="departments"
      @saved="onSaved"
      @close="showModal = false"
    />
  </div>
</template>
