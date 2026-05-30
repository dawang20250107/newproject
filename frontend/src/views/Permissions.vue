<script setup>
import { ref, computed, onMounted } from 'vue'
import api from '../api/index.js'
import EmptyState from '../components/EmptyState.vue'

const loading = ref(true)
const saving = ref(false)
const saved = ref(false)
const error = ref('')
const fields = ref([])
const arFields = ref([])
const caiwuFields = ref([])
const pages = ref([])
const jobs = ref([])          // [{job_title, label, config}]
const activeJob = ref('')

const current = computed(() => jobs.value.find(j => j.job_title === activeJob.value))
const arProjectFields = computed(() => arFields.value.filter(f => f.group === 'project'))
const arRecordFields = computed(() => arFields.value.filter(f => f.group === 'record'))
// Pages split: 应收应付 (paikuan + ar) vs 财务分析 (caiwu_*)
const pkPages = computed(() => pages.value.filter(p => !p.key.startsWith('caiwu_')))
const caiwuPages = computed(() => pages.value.filter(p => p.key.startsWith('caiwu_')))

async function load() {
  loading.value = true
  error.value = ''
  try {
    const res = await api.get('/permissions')
    fields.value = res.data.fields
    arFields.value = res.data.ar_fields || []
    caiwuFields.value = res.data.caiwu_fields || []
    pages.value = res.data.pages
    jobs.value = res.data.jobs
    // Ensure nested config objects exist on each job (older stored configs may lack them)
    for (const j of jobs.value) {
      if (!j.config.ar_view) j.config.ar_view = {}
      for (const f of arFields.value) {
        if (j.config.ar_view[f.key] === undefined) j.config.ar_view[f.key] = true
      }
      if (!j.config.caiwu_view) j.config.caiwu_view = {}
      for (const f of caiwuFields.value) {
        if (j.config.caiwu_view[f.key] === undefined) j.config.caiwu_view[f.key] = true
      }
      if (j.config.caiwu_upload === undefined) j.config.caiwu_upload = false
      if (j.config.caiwu_publish === undefined) j.config.caiwu_publish = false
      if (j.config.caiwu_delete === undefined) j.config.caiwu_delete = false
    }
    if (!activeJob.value && jobs.value.length) activeJob.value = jobs.value[0].job_title
  } catch (e) {
    error.value = e?.error || '加载失败'
  } finally {
    loading.value = false
  }
}
onMounted(load)

function toggleCaiwuViewAll(val) {
  const c = current.value.config
  for (const f of caiwuFields.value) c.caiwu_view[f.key] = val
}

function toggleArViewAll(group, val) {
  const c = current.value.config
  const list = group === 'project' ? arProjectFields.value : arRecordFields.value
  for (const f of list) c.ar_view[f.key] = val
}

function toggleViewAll(val) {
  const c = current.value.config
  for (const f of fields.value) c.view[f.key] = val
  // editing a hidden field makes no sense — clear edit when view is off
  if (!val) for (const f of fields.value) c.edit[f.key] = false
}
function toggleEditAll(val) {
  const c = current.value.config
  for (const f of fields.value) {
    c.edit[f.key] = val
    if (val) c.view[f.key] = true
  }
}
function onView(key, val) {
  const c = current.value.config
  c.view[key] = val
  if (!val) c.edit[key] = false
}
function onEdit(key, val) {
  const c = current.value.config
  c.edit[key] = val
  if (val) c.view[key] = true
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
          按职务精确控制：页面访问 · 字段查看 · 字段编辑 · 新增 / 删除
        </div>
      </div>
    </div>

    <EmptyState v-if="loading" loading />
    <EmptyState v-else-if="error && !jobs.length" :error="error" />

    <template v-else>
      <!-- job-title tabs -->
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
        <div class="section-title">页面访问权限 · 应收应付</div>
        <div class="chip-row">
          <label v-for="p in pkPages" :key="p.key" class="perm-chip" :class="{ on: current.config.pages[p.key] }">
            <input type="checkbox" v-model="current.config.pages[p.key]" />
            <span class="dot"></span>{{ p.label }}
          </label>
        </div>

        <div class="section-title" style="margin-top:20px">页面访问权限 · 财务分析</div>
        <div class="chip-row">
          <label v-for="p in caiwuPages" :key="p.key" class="perm-chip alt" :class="{ on: current.config.pages[p.key] }">
            <input type="checkbox" v-model="current.config.pages[p.key]" />
            <span class="dot"></span>{{ p.label }}
          </label>
        </div>

        <!-- record-level -->
        <div class="section-title" style="margin-top:20px">记录操作权限</div>
        <div class="chip-row">
          <label class="perm-chip" :class="{ on: current.config.can_create }">
            <input type="checkbox" v-model="current.config.can_create" />
            <span class="dot"></span>可新增排款
          </label>
          <label class="perm-chip danger" :class="{ on: current.config.can_delete }">
            <input type="checkbox" v-model="current.config.can_delete" />
            <span class="dot"></span>可删除记录
          </label>
          <label class="perm-chip" :class="{ on: current.config.ar_shared_only }">
            <input type="checkbox" v-model="current.config.ar_shared_only" />
            <span class="dot"></span>仅可见共享业务
          </label>
        </div>

        <!-- field matrix -->
        <div class="section-title" style="margin-top:20px">字段权限（精确到每个字段）</div>
        <div class="table-wrap">
          <table class="perm-table">
            <thead>
              <tr>
                <th>字段</th>
                <th class="ctr">
                  查看
                  <div class="all-row">
                    <button class="mini" @click="toggleViewAll(true)">全选</button>
                    <button class="mini" @click="toggleViewAll(false)">清空</button>
                  </div>
                </th>
                <th class="ctr">
                  编辑
                  <div class="all-row">
                    <button class="mini" @click="toggleEditAll(true)">全选</button>
                    <button class="mini" @click="toggleEditAll(false)">清空</button>
                  </div>
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="f in fields" :key="f.key">
                <td class="fname">{{ f.label }}</td>
                <td class="ctr">
                  <input type="checkbox" class="cb" :checked="current.config.view[f.key]"
                    @change="onView(f.key, $event.target.checked)" />
                </td>
                <td class="ctr">
                  <input type="checkbox" class="cb" :checked="current.config.edit[f.key]"
                    @change="onEdit(f.key, $event.target.checked)" />
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- AR field visibility -->
        <template v-if="arFields.length">
          <div class="section-title" style="margin-top:24px">应收-项目台账字段（显示 / 隐藏）
            <span class="all-inline">
              <button class="mini" @click="toggleArViewAll('project', true)">全显示</button>
              <button class="mini" @click="toggleArViewAll('project', false)">全隐藏</button>
            </span>
          </div>
          <div class="chip-row">
            <label v-for="f in arProjectFields" :key="f.key" class="perm-chip" :class="{ on: current.config.ar_view[f.key] }">
              <input type="checkbox" v-model="current.config.ar_view[f.key]" />
              <span class="dot"></span>{{ f.label }}
            </label>
          </div>

          <div class="section-title" style="margin-top:20px">应收-明细字段（显示 / 隐藏）
            <span class="all-inline">
              <button class="mini" @click="toggleArViewAll('record', true)">全显示</button>
              <button class="mini" @click="toggleArViewAll('record', false)">全隐藏</button>
            </span>
          </div>
          <div class="chip-row">
            <label v-for="f in arRecordFields" :key="f.key" class="perm-chip" :class="{ on: current.config.ar_view[f.key] }">
              <input type="checkbox" v-model="current.config.ar_view[f.key]" />
              <span class="dot"></span>{{ f.label }}
            </label>
          </div>
        </template>

        <!-- 财务分析 capabilities + field visibility -->
        <template v-if="caiwuFields.length">
          <div class="section-title" style="margin-top:24px">财务分析操作权限</div>
          <div class="chip-row">
            <label class="perm-chip alt" :class="{ on: current.config.caiwu_upload }">
              <input type="checkbox" v-model="current.config.caiwu_upload" />
              <span class="dot"></span>可上传数据
            </label>
            <label class="perm-chip alt" :class="{ on: current.config.caiwu_publish }">
              <input type="checkbox" v-model="current.config.caiwu_publish" />
              <span class="dot"></span>可发布批次
            </label>
            <label class="perm-chip danger" :class="{ on: current.config.caiwu_delete }">
              <input type="checkbox" v-model="current.config.caiwu_delete" />
              <span class="dot"></span>可删除批次
            </label>
          </div>

          <div class="section-title" style="margin-top:20px">财务分析字段（显示 / 隐藏）
            <span class="all-inline">
              <button class="mini" @click="toggleCaiwuViewAll(true)">全显示</button>
              <button class="mini" @click="toggleCaiwuViewAll(false)">全隐藏</button>
            </span>
          </div>
          <div class="chip-row">
            <label v-for="f in caiwuFields" :key="f.key" class="perm-chip alt" :class="{ on: current.config.caiwu_view[f.key] }">
              <input type="checkbox" v-model="current.config.caiwu_view[f.key]" />
              <span class="dot"></span>{{ f.label }}
            </label>
          </div>
        </template>

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
        关闭某字段的「查看」会自动关闭其「编辑」。用户重新登录后权限即时生效。
      </div>
    </template>
  </div>
</template>

<style scoped>
.chip-row { display: flex; flex-wrap: wrap; gap: 10px; }
.perm-chip {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 16px; border-radius: 22px;
  border: 1.5px solid var(--border);
  background: rgba(255,253,250,0.7);
  font-size: 13px; cursor: pointer; transition: all 0.18s; user-select: none;
}
.perm-chip input { display: none; }
.perm-chip .dot {
  width: 9px; height: 9px; border-radius: 50%;
  background: rgba(155,128,112,0.4); transition: all 0.18s; flex-shrink: 0;
}
.perm-chip.on {
  border-color: var(--primary); background: rgba(201,99,66,0.1);
  color: var(--primary); font-weight: 600;
}
.perm-chip.on .dot { background: var(--primary); box-shadow: 0 0 8px rgba(201,99,66,0.5); }
.perm-chip.danger.on { border-color: #c62828; background: rgba(198,40,40,0.08); color: #c62828; }
.perm-chip.danger.on .dot { background: #c62828; box-shadow: 0 0 8px rgba(198,40,40,0.5); }
.perm-chip.alt.on { border-color: #1565c0; background: rgba(21,101,192,0.08); color: #1565c0; }
.perm-chip.alt.on .dot { background: #1565c0; box-shadow: 0 0 8px rgba(21,101,192,0.5); }

.perm-table { width: 100%; }
.perm-table th.ctr, .perm-table td.ctr { text-align: center; width: 130px; }
.perm-table .fname { font-weight: 600; }
.all-row { display: flex; gap: 4px; justify-content: center; margin-top: 4px; }
.all-inline { display: inline-flex; gap: 4px; margin-left: 10px; }
.mini {
  font-size: 11px; padding: 1px 7px; border-radius: 5px;
  border: 1px solid var(--border); background: var(--bg2);
  color: var(--muted); cursor: pointer;
}
.mini:hover { border-color: var(--primary); color: var(--primary); }
.cb { width: 18px; height: 18px; accent-color: var(--primary); cursor: pointer; }

.saved-tag { color: #2e7d32; font-size: 13px; font-weight: 600; }
.save-spin {
  width: 12px; height: 12px; border-radius: 50%;
  border: 2px solid rgba(255,255,255,0.4); border-top-color: white;
  animation: spin 0.7s linear infinite; display: inline-block;
}
@keyframes spin { to { transform: rotate(360deg); } }
.status-fade-enter-active, .status-fade-leave-active { transition: opacity 0.2s; }
.status-fade-enter-from, .status-fade-leave-to { opacity: 0; }

.hint-card {
  margin-top: 16px; padding: 14px 18px; border-radius: 12px;
  background: rgba(21,101,192,0.06); border: 1px solid rgba(21,101,192,0.15);
  font-size: 12.5px; color: #1565c0; line-height: 1.7;
}
</style>
