<script setup>
import { ref, computed, onMounted } from 'vue'
import api from '../api/index.js'

const loading = ref(true)
const saving = ref(false)
const saved = ref(false)
const error = ref('')
const fields = ref([])
const pages = ref([])
const jobs = ref([])          // [{job_title, label, config}]
const activeJob = ref('')

const current = computed(() => jobs.value.find(j => j.job_title === activeJob.value))

async function load() {
  loading.value = true
  error.value = ''
  try {
    const res = await api.get('/permissions')
    fields.value = res.data.fields
    pages.value = res.data.pages
    jobs.value = res.data.jobs
    if (!activeJob.value && jobs.value.length) activeJob.value = jobs.value[0].job_title
  } catch (e) {
    error.value = e?.error || '加载失败'
  } finally {
    loading.value = false
  }
}
onMounted(load)

function toggleViewAll(val) {
  const c = current.value.config
  for (const f of fields.value) c.view[f.key] = val
}

async function save() {
  saving.value = true
  saved.value = false
  error.value = ''
  try {
    await api.put(`/permissions/${activeJob.value}`, { config: current.value.config })
    saved.value = true
    setTimeout(() => { saved.value = false }, 2200)
  } catch (e) {
    error.value = e?.error || '保存失败'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div>
    <div class="topbar">
      <div>
        <h1>权限配置</h1>
        <div style="font-size:13px;color:var(--muted);margin-top:2px">
          按职务精确控制：页面访问 · 报表/图表可见项 · 数据操作
        </div>
      </div>
    </div>

    <div v-if="loading" class="empty"><div class="icon">⏳</div>加载中…</div>
    <div v-else-if="error && !jobs.length" class="empty" style="color:#c62828"><div class="icon">⚠️</div>{{ error }}</div>

    <template v-else>
      <div class="tabs">
        <button
          v-for="j in jobs" :key="j.job_title"
          :class="['tab', activeJob === j.job_title ? 'active' : '']"
          @click="activeJob = j.job_title"
        >{{ j.label }}</button>
      </div>

      <div v-if="current" class="card">
        <div v-if="error" class="alert alert-err">{{ error }}</div>

        <!-- pages -->
        <div class="section-title">页面访问权限</div>
        <div class="chip-row">
          <label v-for="p in pages" :key="p.key" class="perm-chip" :class="{ on: current.config.pages[p.key] }">
            <input type="checkbox" v-model="current.config.pages[p.key]" />
            <span class="dot"></span>{{ p.label }}
          </label>
        </div>

        <!-- data operations -->
        <div class="section-title" style="margin-top:20px">数据操作权限</div>
        <div class="chip-row">
          <label class="perm-chip" :class="{ on: current.config.can_upload }">
            <input type="checkbox" v-model="current.config.can_upload" />
            <span class="dot"></span>上传数据
          </label>
          <label class="perm-chip" :class="{ on: current.config.can_publish }">
            <input type="checkbox" v-model="current.config.can_publish" />
            <span class="dot"></span>发布批次
          </label>
          <label class="perm-chip danger" :class="{ on: current.config.can_delete }">
            <input type="checkbox" v-model="current.config.can_delete" />
            <span class="dot"></span>删除批次
          </label>
        </div>

        <!-- view fields -->
        <div class="section-title" style="margin-top:20px;display:flex;align-items:center;gap:12px">
          报表 / 图表可见项
          <span class="all-row" style="margin:0">
            <button class="mini" @click="toggleViewAll(true)">全选</button>
            <button class="mini" @click="toggleViewAll(false)">清空</button>
          </span>
        </div>
        <div class="chip-row">
          <label v-for="f in fields" :key="f.key" class="perm-chip" :class="{ on: current.config.view[f.key] }">
            <input type="checkbox" v-model="current.config.view[f.key]" />
            <span class="dot"></span>{{ f.label }}
          </label>
        </div>

        <div class="modal-footer" style="border:none;padding-top:18px">
          <Transition name="status-fade">
            <span v-if="saved" class="saved-tag">✓ 已保存</span>
          </Transition>
          <button class="btn btn-primary" :disabled="saving" @click="save">
            <span v-if="saving" class="save-spin"></span>
            {{ saving ? '保存中…' : `保存「${current.label}」权限` }}
          </button>
        </div>
      </div>

      <div class="hint-card">
        <strong>说明：</strong>超级管理员拥有全部权限，不受此处配置影响。
        关闭某页面访问后，该职务用户登录后将无法进入对应页面。用户重新登录后权限即时生效。
      </div>
    </template>
  </div>
</template>

<style scoped>
.chip-row { display: flex; flex-wrap: wrap; gap: 10px; }
.perm-chip {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 16px; border-radius: 22px;
  border: 1.5px solid var(--border); background: rgba(255,253,250,0.7);
  font-size: 13px; cursor: pointer; transition: all 0.18s; user-select: none;
}
.perm-chip input { display: none; }
.perm-chip .dot { width: 9px; height: 9px; border-radius: 50%; background: rgba(155,128,112,0.4); transition: all 0.18s; flex-shrink: 0; }
.perm-chip.on { border-color: var(--primary); background: rgba(201,99,66,0.1); color: var(--primary); font-weight: 600; }
.perm-chip.on .dot { background: var(--primary); box-shadow: 0 0 8px rgba(201,99,66,0.5); }
.perm-chip.danger.on { border-color: #c62828; background: rgba(198,40,40,0.08); color: #c62828; }
.perm-chip.danger.on .dot { background: #c62828; box-shadow: 0 0 8px rgba(198,40,40,0.5); }

.all-row { display: inline-flex; gap: 4px; }
.mini { font-size: 11px; padding: 1px 7px; border-radius: 5px; border: 1px solid var(--border); background: rgba(200,185,170,0.25); color: var(--muted); cursor: pointer; }
.mini:hover { border-color: var(--primary); color: var(--primary); }

.saved-tag { color: #2e7d32; font-size: 13px; font-weight: 600; }
.save-spin { width: 12px; height: 12px; border-radius: 50%; border: 2px solid rgba(255,255,255,0.4); border-top-color: white; animation: spin 0.7s linear infinite; display: inline-block; }
@keyframes spin { to { transform: rotate(360deg); } }
.status-fade-enter-active, .status-fade-leave-active { transition: opacity 0.2s; }
.status-fade-enter-from, .status-fade-leave-to { opacity: 0; }

.hint-card { margin-top: 16px; padding: 14px 18px; border-radius: 12px; background: rgba(21,101,192,0.06); border: 1px solid rgba(21,101,192,0.15); font-size: 12.5px; color: #1565c0; line-height: 1.7; }
</style>
