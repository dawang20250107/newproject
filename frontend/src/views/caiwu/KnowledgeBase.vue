<script setup>
import { ref, computed, onMounted } from 'vue'
import { useCaiwuAuth } from '../../composables/useCaiwuAuth.js'
import { BUSINESS_UNITS } from '../../constants.js'
import api from '../../api/caiwu.js'
import EmptyState from '../../components/EmptyState.vue'

const auth = useCaiwuAuth()
const items = ref([])
const loading = ref(false)
const loadErr = ref('')

const accessibleBus = computed(() => {
  if (auth.isAdmin) return BUSINESS_UNITS
  return (auth.user?.departments || []).filter(d => BUSINESS_UNITS.includes(d))
})

const KIND_LABEL = { insight: '洞察', background: '背景', rule: '口径/规则' }

// 筛选
const q = ref('')
const fScope = ref('')
const fKind = ref('')
const fSource = ref('')

const filtered = computed(() => {
  const kw = q.value.trim().toLowerCase()
  return items.value.filter(k =>
    (!fScope.value || k.scope === fScope.value) &&
    (!fKind.value || k.kind === fKind.value) &&
    (!fSource.value || k.source === fSource.value) &&
    (!kw || (k.content + (k.title || '')).toLowerCase().includes(kw)))
})

async function load() {
  loading.value = true; loadErr.value = ''
  try {
    const res = await api.get('/cockpit/knowledge')
    items.value = res.data.items
  } catch (e) { loadErr.value = e?.msg || '加载失败' }
  finally { loading.value = false }
}

// 新增
const addContent = ref('')
const addScope = ref('')
const addKind = ref('background')
async function add() {
  const content = addContent.value.trim()
  if (!content) return
  try {
    await api.post('/cockpit/knowledge', { content, scope: addScope.value || '全集团', kind: addKind.value })
    addContent.value = ''
    await load()
  } catch (e) { alert(e?.msg || '添加失败') }
}

async function del(k) {
  if (!confirm('确定删除这条知识？')) return
  try { await api.delete(`/cockpit/knowledge/${k.id}`); items.value = items.value.filter(x => x.id !== k.id) }
  catch (e) { alert(e?.msg || '删除失败') }
}
async function togglePin(k) {
  try { const r = await api.put(`/cockpit/knowledge/${k.id}`, { pinned: !k.pinned }); Object.assign(k, r.data); await load() }
  catch (e) { alert(e?.msg || '操作失败') }
}

// 行内编辑
const editId = ref(null)
const editText = ref('')
function startEdit(k) { editId.value = k.id; editText.value = k.content }
async function saveEdit(k) {
  const content = editText.value.trim()
  if (!content) return
  try { const r = await api.put(`/cockpit/knowledge/${k.id}`, { content }); Object.assign(k, r.data); editId.value = null }
  catch (e) { alert(e?.msg || '保存失败') }
}

// 文件导入
const importing = ref(false)
const importScope = ref('')
const importMode = ref('distill')
const fileInput = ref(null)
async function onPickFile(e) {
  const file = e.target.files?.[0]
  if (!file || importing.value) { e.target.value = ''; return }
  importing.value = true
  try {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('scope', importScope.value || '全集团')
    fd.append('mode', importMode.value)
    const res = await api.post('/cockpit/knowledge/import', fd,
      { headers: { 'Content-Type': 'multipart/form-data' }, timeout: 180000 })
    alert(`✓ 已从「${res.data.file}」导入 ${res.data.created} 条知识（${importMode.value === 'distill' ? 'AI提炼' : '原文'}）`)
    await load()
  } catch (err) { alert(err?.msg || '导入失败') }
  finally { importing.value = false; e.target.value = '' }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="topbar">
      <div>
        <h1>经营知识库</h1>
        <div style="font-size:13px;color:var(--muted);margin-top:2px">
          业财融合助手的长期记忆 · 沉淀越多，助手越懂业务、判断越贴合经营
        </div>
      </div>
    </div>

    <!-- 导入 + 新增 -->
    <div class="kp-tools">
      <div class="kp-tool-card">
        <div class="kp-tool-title">📥 导入文件</div>
        <div class="kp-tool-sub">支持 txt / md / csv / json / Excel（PDF / Word 部署后支持）</div>
        <div class="kp-import-row">
          <select v-model="importScope" class="kp-sel">
            <option value="">全集团</option>
            <option v-for="b in accessibleBus" :key="b" :value="b">{{ b }}</option>
          </select>
          <select v-model="importMode" class="kp-sel">
            <option value="distill">AI 提炼为要点</option>
            <option value="raw">原文切块入库</option>
          </select>
          <label class="btn btn-primary btn-sm" :class="{ disabled: importing }" style="cursor:pointer">
            {{ importing ? '导入中…（AI提炼约需30秒）' : '选择文件' }}
            <input ref="fileInput" type="file"
              accept=".txt,.md,.markdown,.csv,.tsv,.json,.log,.xlsx,.xls,.pdf,.docx,.html"
              style="display:none" @change="onPickFile" />
          </label>
        </div>
      </div>

      <div class="kp-tool-card">
        <div class="kp-tool-title">✍ 手动新增</div>
        <textarea v-model="addContent" class="kp-textarea" rows="2"
          placeholder="补充一条经营背景 / 口径 / 洞察（助手会记住并在分析时延续）…"></textarea>
        <div class="kp-import-row">
          <select v-model="addScope" class="kp-sel">
            <option value="">全集团</option>
            <option v-for="b in accessibleBus" :key="b" :value="b">{{ b }}</option>
          </select>
          <select v-model="addKind" class="kp-sel">
            <option value="background">背景</option>
            <option value="rule">口径/规则</option>
            <option value="insight">洞察</option>
          </select>
          <button class="btn btn-primary btn-sm" :disabled="!addContent.trim()" @click="add">添加</button>
        </div>
      </div>
    </div>

    <!-- 筛选 -->
    <div class="kp-filterbar">
      <input v-model="q" class="kp-search" placeholder="🔍 搜索知识内容…" />
      <select v-model="fScope" class="kp-sel">
        <option value="">全部范围</option>
        <option value="全集团">全集团</option>
        <option v-for="b in accessibleBus" :key="b" :value="b">{{ b }}</option>
      </select>
      <select v-model="fKind" class="kp-sel">
        <option value="">全部类型</option>
        <option value="background">背景</option>
        <option value="rule">口径/规则</option>
        <option value="insight">洞察</option>
      </select>
      <select v-model="fSource" class="kp-sel">
        <option value="">全部来源</option>
        <option value="user">人工</option>
        <option value="ai">AI提炼</option>
      </select>
      <span class="kp-count">{{ filtered.length }} / {{ items.length }} 条</span>
    </div>

    <EmptyState v-if="loading && !items.length" loading />
    <EmptyState v-else-if="loadErr" :error="loadErr" />
    <div v-else-if="!items.length" class="kp-empty">
      <div style="font-size:38px">📚</div>
      <div style="font-weight:700;margin-top:6px">知识库还是空的</div>
      <div style="color:var(--muted);font-size:13px;margin-top:4px">
        导入文件、手动新增，或在驾驶舱对话里点「📌 提炼入库」，助手就会越用越聪明
      </div>
    </div>

    <div v-else class="kp-list">
      <div v-for="k in filtered" :key="k.id" class="kp-item" :class="{ pinned: k.pinned }">
        <div class="kp-meta">
          <span class="kp-kind" :class="k.kind">{{ KIND_LABEL[k.kind] || k.kind }}</span>
          <span class="kp-scope">{{ k.scope }}</span>
          <span class="kp-src" :class="k.source">{{ k.source === 'ai' ? 'AI提炼' : '人工' }}</span>
          <span v-if="k.created_at" class="kp-time">{{ k.created_at.slice(0, 10) }}</span>
          <span class="kp-spacer"></span>
          <button class="kp-btn" :title="k.pinned ? '取消置顶' : '置顶'" @click="togglePin(k)">{{ k.pinned ? '📌' : '📍' }}</button>
          <button v-if="editId !== k.id" class="kp-btn" title="编辑" @click="startEdit(k)">✎</button>
          <button class="kp-btn" title="删除" @click="del(k)">🗑</button>
        </div>
        <div v-if="k.title && editId !== k.id" class="kp-title">{{ k.title }}</div>
        <template v-if="editId === k.id">
          <textarea v-model="editText" class="kp-textarea" rows="3"></textarea>
          <div style="margin-top:6px;display:flex;gap:6px">
            <button class="btn btn-primary btn-sm" @click="saveEdit(k)">保存</button>
            <button class="btn btn-ghost btn-sm" @click="editId = null">取消</button>
          </div>
        </template>
        <div v-else class="kp-content">{{ k.content }}</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.kp-tools { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 16px; }
@media (max-width: 800px) { .kp-tools { grid-template-columns: 1fr; } }
.kp-tool-card { background: rgba(255,255,255,0.8); border: 1px solid rgba(0,0,0,0.07); border-radius: 14px; padding: 14px 16px; }
.kp-tool-title { font-size: 14px; font-weight: 700; color: var(--text); }
.kp-tool-sub { font-size: 11.5px; color: var(--muted); margin: 2px 0 10px; }
.kp-import-row { display: flex; gap: 8px; align-items: center; margin-top: 10px; flex-wrap: wrap; }
.kp-sel { height: 32px; border: 1px solid rgba(0,0,0,0.12); border-radius: 8px; background: #fff; font-size: 12.5px; color: var(--text); padding: 0 9px; }
.kp-textarea { width: 100%; resize: vertical; border: 1px solid rgba(0,0,0,0.12); border-radius: 9px; padding: 8px 11px; font-size: 13px; font-family: inherit; line-height: 1.5; outline: none; box-sizing: border-box; }
.kp-textarea:focus { border-color: var(--primary); }

.kp-filterbar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 14px; }
.kp-search { flex: 1; min-width: 180px; height: 34px; border: 1px solid rgba(0,0,0,0.12); border-radius: 9px; padding: 0 12px; font-size: 13px; outline: none; }
.kp-search:focus { border-color: var(--primary); }
.kp-count { font-size: 12px; color: var(--muted); margin-left: auto; }

.kp-empty { text-align: center; padding: 60px 20px; }
.kp-list { display: flex; flex-direction: column; gap: 10px; }
.kp-item { background: rgba(255,255,255,0.85); border: 1px solid rgba(0,0,0,0.07); border-radius: 12px; padding: 12px 14px; }
.kp-item.pinned { border-color: rgba(201,99,66,0.35); background: rgba(201,99,66,0.04); }
.kp-meta { display: flex; align-items: center; gap: 7px; margin-bottom: 6px; }
.kp-kind { font-size: 10.5px; font-weight: 700; padding: 1px 8px; border-radius: 6px; color: #fff; background: #7a9fd4; }
.kp-kind.insight { background: #2e7d32; }
.kp-kind.rule { background: #8a4b34; }
.kp-scope { font-size: 11.5px; color: var(--muted); font-weight: 600; }
.kp-src { font-size: 10px; padding: 0 6px; border-radius: 5px; border: 1px solid rgba(0,0,0,0.12); color: var(--muted); }
.kp-src.ai { color: var(--primary); border-color: rgba(201,99,66,0.3); }
.kp-time { font-size: 11px; color: var(--muted); }
.kp-spacer { flex: 1; }
.kp-btn { background: none; border: none; cursor: pointer; font-size: 14px; padding: 0 3px; opacity: .72; }
.kp-btn:hover { opacity: 1; }
.kp-title { font-size: 13.5px; font-weight: 700; color: var(--text); margin-bottom: 3px; }
.kp-content { font-size: 13px; color: var(--text); line-height: 1.65; white-space: pre-wrap; }
</style>
