<script setup>
import { ref, reactive, computed } from 'vue'
import api from '../api/index.js'
import { useToast } from '../composables/useToast.js'
import { confirmDlg } from '../composables/confirm.js'
import { resultDlg } from '../composables/bulkResult.js'
import { todayCST } from '../constants.js'

const emit = defineEmits(['synced'])
const toast = useToast()

// ── 连接自检（凭证/模板配置核对）────────────────────────────────────────────
const testing = ref(false)
const diag = ref(null)
async function testConnection() {
  testing.value = true
  try { diag.value = (await api.get('/dingtalk/test')).data }
  catch (e) { diag.value = { connected: false, error: e?.msg || e?.error || '请求失败' } }
  finally { testing.value = false }
}

// ── 查询条件 ──────────────────────────────────────────────────────────────
const personMode = ref('mobile')          // 'mobile' | 'name'
const personInput = ref('')
const resolving = ref(false)
const candidates = ref([])                 // 姓名命中的多个候选
const picked = ref(null)                   // { userid, name }
const status = ref('todo')                 // todo | done | originated
const STATUS = [
  { v: 'todo', l: '待处理' }, { v: 'done', l: '已处理' }, { v: 'originated', l: '该员工发起' },
]
function monthStart() { const d = todayCST(); return d.slice(0, 8) + '01' }
const range = reactive({ start: monthStart(), end: todayCST() })
const QUICK = [
  { k: 'month', l: '本月' }, { k: 'q', l: '本季度' }, { k: 'd30', l: '近30天' },
]
function setQuick(k) {
  const t = todayCST(); const [y, m] = t.split('-').map(Number)
  if (k === 'month') { range.start = `${t.slice(0, 8)}01`; range.end = t }
  else if (k === 'd30') { const d = new Date(t); d.setDate(d.getDate() - 30); range.start = d.toISOString().slice(0, 10); range.end = t }
  else if (k === 'q') { const qm = Math.floor((m - 1) / 3) * 3 + 1; range.start = `${y}-${String(qm).padStart(2, '0')}-01`; range.end = t }
}

// ── 结果 ──────────────────────────────────────────────────────────────────
const loading = ref(false)
const loadErr = ref('')
const items = ref([])
const capped = ref(false)
const sel = ref(new Set())
const selCount = computed(() => sel.value.size)
const DING = {
  approved: ['ok', '已通过'], rejected: ['bad', '已拒绝'],
  pending: ['run', '审批中'], canceled: ['cancel', '已撤销'],
}
const stats = computed(() => {
  const s = items.value
  return { total: s.length, unsynced: s.filter(i => !i.synced).length, synced: s.filter(i => i.synced).length }
})

async function resolvePerson() {
  const val = personInput.value.trim()
  if (!val) { toast.error('请输入手机号或姓名'); return null }
  resolving.value = true; candidates.value = []
  try {
    const body = personMode.value === 'mobile' ? { mobile: val } : { name: val }
    const r = await api.post('/dingtalk/resolve-user', body)
    const users = r.data?.users || []
    if (!users.length) { toast.error('钉钉通讯录未找到该人员'); return null }
    if (users.length === 1) { picked.value = users[0]; return users[0] }
    candidates.value = users; return null   // 多个同名 → 交用户选
  } catch (e) { toast.error(e?.msg || e?.error || '查询人员失败'); return null }
  finally { resolving.value = false }
}
function pickCandidate(u) { picked.value = u; candidates.value = []; runQuery() }

async function runQuery() {
  let user = picked.value
  if (!user) { user = await resolvePerson(); if (!user) return }
  loading.value = true; loadErr.value = ''; sel.value = new Set()
  try {
    const r = await api.post('/dingtalk/query', {
      userid: user.userid, start: range.start, end: range.end, status: status.value,
    })
    items.value = r.data?.items || []
    capped.value = !!r.data?.capped
  } catch (e) { loadErr.value = e?.msg || e?.error || '查询失败'; items.value = [] }
  finally { loading.value = false }
}
function onStatusTab(v) { status.value = v; if (picked.value) runQuery() }

// ── 勾选 ──────────────────────────────────────────────────────────────────
function toggle(id) { const s = new Set(sel.value); s.has(id) ? s.delete(id) : s.add(id); sel.value = s }
const pageAllSel = computed(() => items.value.length > 0 && items.value.every(i => sel.value.has(i.instance_id)))
function toggleAll() {
  const s = new Set()
  if (!pageAllSel.value) items.value.forEach(i => s.add(i.instance_id))
  sel.value = s
}
function selQuick(kind) {
  const s = new Set()
  items.value.forEach(i => {
    if (kind === 'unsync' && !i.synced) s.add(i.instance_id)
    else if (kind === 'stale' && i.sync_stale) s.add(i.instance_id)
    else if (kind === 'today' && (i.create_time || '').slice(0, 10) === todayCST()) s.add(i.instance_id)
  })
  sel.value = s
}
function clearSel() { sel.value = new Set() }

// ── 同步 / 刷新 ────────────────────────────────────────────────────────────
const selectedItems = computed(() => items.value.filter(i => sel.value.has(i.instance_id)))
const previewOpen = ref(false)
const syncing = ref(false)
const newCount = computed(() => selectedItems.value.filter(i => !i.synced).length)
const updCount = computed(() => selectedItems.value.filter(i => i.synced).length)

function openPreview() { if (selCount.value) previewOpen.value = true }
async function doSync() {
  syncing.value = true
  try {
    const r = await api.post('/dingtalk/sync', { instance_ids: [...sel.value] })
    const d = r.data || {}
    previewOpen.value = false
    if (d.skipped?.length) resultDlg({ title: '同步结果', okLine: d.message, skipped: d.skipped })
    else toast.success(d.message || '已同步')
    emit('synced')
    await runQuery()          // 刷新同步标记
  } catch (e) { toast.error(e?.msg || e?.error || '同步失败') }
  finally { syncing.value = false }
}
async function refreshStatus() {
  if (!selCount.value) return
  if (!(await confirmDlg(`对所选 ${selCount.value} 条已同步记录，从钉钉重新拉取最新状态并回写？未同步的会自动跳过。`))) return
  syncing.value = true
  try {
    const r = await api.post('/dingtalk/refresh', { instance_ids: [...sel.value] })
    const d = r.data || {}
    if (d.skipped?.length) resultDlg({ title: '刷新结果', okLine: d.message, skipped: d.skipped })
    else toast.success(d.message || '已刷新')
    emit('synced')
    await runQuery()
  } catch (e) { toast.error(e?.msg || e?.error || '刷新失败') }
  finally { syncing.value = false }
}
</script>

<template>
  <div class="dt card fh-fill">
    <!-- 连接自检 -->
    <div v-if="diag" class="diag" :class="{ bad: !diag.connected }">
      <div class="diag-line">
        <b>{{ diag.connected ? '✓ 钉钉已连通' : '✗ 连接失败' }}</b>
        <span v-if="diag.error" class="diag-err">{{ diag.error }}</span>
        <button class="diag-x" @click="diag = null">✕</button>
      </div>
      <div v-if="diag.config" class="diag-cfg">
        服务器读到：AppKey=<code>{{ diag.config.app_key }}</code> ·
        Secret 长度 <code>{{ diag.config.secret_len }}</code>（<code>{{ diag.config.secret_masked }}</code>） ·
        模板配置 <code>{{ diag.config.process_codes_set ? '已配' : '未配' }}</code>
      </div>
      <div v-if="diag.hint" class="diag-hint">💡 {{ diag.hint }}</div>
      <div v-if="diag.connected" class="diag-tpl">
        可同步模板：<template v-if="diag.templates && diag.templates.length"><code v-for="t in diag.templates" :key="t.process_code">{{ t.name || t.process_code }}</code></template>
        <span v-else class="diag-err">未列出 —— 请在 DINGTALK_PROCESS_CODES 配置模板 process_code<span v-if="diag.template_error">（{{ diag.template_error }}）</span></span>
      </div>
    </div>

    <!-- 查询条 -->
    <div class="dt-query">
      <div class="qf">
        <label>查询人员</label>
        <div class="person">
          <div class="seg">
            <button :class="{ on: personMode === 'mobile' }" @click="personMode = 'mobile'; picked = null">手机号</button>
            <button :class="{ on: personMode === 'name' }" @click="personMode = 'name'; picked = null">姓名</button>
          </div>
          <input v-model="personInput" class="inp" :placeholder="personMode === 'mobile' ? '钉钉手机号' : '姓名（可能多个同名）'"
                 @keyup.enter="picked = null; runQuery()" @input="picked = null" />
          <span v-if="picked" class="picked">✓ {{ picked.name }}</span>
        </div>
        <!-- 同名候选 -->
        <div v-if="candidates.length" class="cands">
          <span class="cands-lbl">多个同名，请选择：</span>
          <button v-for="u in candidates" :key="u.userid" class="cand" @click="pickCandidate(u)">{{ u.name }}</button>
        </div>
      </div>
      <div class="qf">
        <label>时间范围</label>
        <div class="daterow">
          <input v-model="range.start" type="date" class="inp inp-date" />
          <span class="sep">→</span>
          <input v-model="range.end" type="date" class="inp inp-date" />
          <button v-for="q in QUICK" :key="q.k" class="quick" @click="setQuick(q.k)">{{ q.l }}</button>
        </div>
      </div>
      <button class="go" :disabled="loading || resolving" @click="picked = null; runQuery()">
        {{ loading || resolving ? '查询中…' : '查询' }}
      </button>
      <button class="quick test" :disabled="testing" @click="testConnection">{{ testing ? '检测中…' : '测试连接' }}</button>
    </div>

    <!-- 状态页签 -->
    <div class="dt-tabs">
      <button v-for="s in STATUS" :key="s.v" :class="['dt-tab', { on: status === s.v }]" @click="onStatusTab(s.v)">{{ s.l }}</button>
    </div>

    <!-- 汇总条 + 快捷选 -->
    <div v-if="items.length" class="dt-summary">
      <span class="s">共 <b>{{ stats.total }}</b> 条</span>
      <span class="s acc">未同步 <b>{{ stats.unsynced }}</b></span>
      <span class="s ok">已同步 <b>{{ stats.synced }}</b></span>
      <span v-if="capped" class="s warn">结果较多已截断，请缩小时间范围</span>
      <span class="grow"></span>
      <span class="sellbl">快捷选：</span>
      <button class="selq" @click="selQuick('unsync')">全部未同步</button>
      <button class="selq" @click="selQuick('stale')">状态待刷新</button>
      <button class="selq" @click="selQuick('today')">今天</button>
    </div>

    <!-- 结果表 -->
    <div class="dt-body">
      <div v-if="loadErr" class="empty err">⚠️ {{ loadErr }}</div>
      <div v-else-if="loading" class="empty">⏳ 正在从钉钉拉取…</div>
      <div v-else-if="!picked && !items.length" class="empty hint">
        <div class="hint-i">🔗</div>
        <div class="hint-t">按人查询钉钉审批</div>
        <div class="hint-s">输入手机号或姓名、选时间范围，查出该员工在钉钉里的待处理 / 已处理审批，勾选后同步进「审批管理」。</div>
      </div>
      <div v-else-if="!items.length" class="empty">该员工在此范围内无「{{ STATUS.find(s => s.v === status).l }}」的审批</div>
      <div v-else class="tablewrap">
        <table>
          <thead>
            <tr>
              <th class="cbcol"><input type="checkbox" class="cbx" :checked="pageAllSel" @change="toggleAll" /></th>
              <th>审批标题 / 编号</th><th>发起人</th><th class="r">金额</th><th>收款方</th>
              <th>钉钉状态</th><th>发起时间</th><th>同步状态</th><th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="i in items" :key="i.instance_id" :class="{ sel: sel.has(i.instance_id) }">
              <td><input type="checkbox" class="cbx" :checked="sel.has(i.instance_id)" @change="toggle(i.instance_id)" /></td>
              <td class="ttlcell">
                <div class="ttl">{{ i.title }}</div>
                <div class="sub"><span class="tpl">{{ i.template }}</span> · {{ i.approval_number || '—' }}</div>
              </td>
              <td>{{ i.applicant }}<div class="sub">{{ i.department }}</div></td>
              <td class="r amt">¥{{ Number(i.amount).toLocaleString('zh-CN', { minimumFractionDigits: 2 }) }}</td>
              <td class="payee">{{ i.payee }}</td>
              <td><span class="pill" :class="'p-' + DING[i.ding_status][0]"><i></i>{{ DING[i.ding_status][1] }}</span></td>
              <td class="when">{{ (i.create_time || '').replace('T', ' ').slice(0, 16) }}</td>
              <td>
                <span v-if="!i.synced" class="sync no">● 未同步</span>
                <span v-else-if="i.sync_stale" class="sync upd">◑ 待刷新 <span class="rec">{{ i.sync_rec_no }}</span></span>
                <span v-else class="sync yes">✓ 已同步 <span class="rec">{{ i.sync_rec_no }}</span></span>
              </td>
              <td></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 批量条 -->
    <Transition name="bb">
      <div v-if="selCount" class="batchbar">
        <span class="n">已选 <b>{{ selCount }}</b> 条</span>
        <button class="bb primary" :disabled="syncing" @click="openPreview">同步至审批管理</button>
        <button class="bb ghost" :disabled="syncing" @click="refreshStatus">刷新选中状态</button>
        <button class="bb x" @click="clearSel">✕</button>
      </div>
    </Transition>

    <!-- 同步预览弹窗 -->
    <Teleport to="body">
      <div v-if="previewOpen" class="scrim" @click.self="previewOpen = false">
        <div class="modal">
          <div class="m-head">
            <h3>同步至审批管理 · 预览</h3>
            <p>按钉钉实例 ID 去重：已存在的更新状态/金额，其余新建。</p>
          </div>
          <div class="m-body">
            <div class="conflict">
              <span>ℹ</span>
              <span>共 <b>{{ selCount }}</b> 条：<b>{{ newCount }}</b> 条新建、<b>{{ updCount }}</b> 条更新。字段映射：申请人 / 部门 / 金额 / 收款方 / 摘要按通用规则从钉钉表单提取，原始表单整单留存。</span>
            </div>
            <table class="mtable">
              <thead><tr><th>钉钉审批</th><th class="r">金额</th><th>处理</th></tr></thead>
              <tbody>
                <tr v-for="i in selectedItems" :key="i.instance_id">
                  <td><div class="ttl">{{ i.title }}</div><div class="sub">{{ i.applicant }} · {{ i.department }}</div></td>
                  <td class="r amt">¥{{ Number(i.amount).toLocaleString('zh-CN', { minimumFractionDigits: 2 }) }}</td>
                  <td><span class="tag" :class="i.synced ? 'upd' : 'new'">{{ i.synced ? '更新' : '新建' }}</span></td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="m-foot">
            <button class="btn" @click="previewOpen = false">取消</button>
            <button class="btn primary" :disabled="syncing" @click="doSync">{{ syncing ? '同步中…' : `确认同步 ${selCount} 条` }}</button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.dt { display: flex; flex-direction: column; min-height: 0; padding: 0; }
.dt-query { display: flex; gap: 18px; align-items: flex-end; flex-wrap: wrap; padding: 16px 18px; border-bottom: 1px solid var(--border, #eadfd2); }
.qf { display: flex; flex-direction: column; gap: 7px; }
.qf > label { font-size: 11.5px; font-weight: 700; letter-spacing: .04em; color: var(--muted, #9b8070); text-transform: uppercase; }
.person { display: flex; align-items: center; gap: 9px; }
.seg { display: inline-flex; background: var(--surface-2, rgba(160,120,80,.08)); border-radius: 8px; padding: 3px; }
.seg button { border: none; background: none; padding: 6px 12px; border-radius: 6px; font-size: 13px; font-weight: 600; color: var(--muted, #9b8070); cursor: pointer; font-family: inherit; }
.seg button.on { background: var(--card-bg, #fff); color: var(--primary, #1565c0); box-shadow: 0 1px 3px rgba(0,0,0,.08); }
.inp { border: 1.5px solid var(--border, #d8c9b8); border-radius: 8px; padding: 8px 11px; font-size: 14px; color: var(--text, #4a3322); background: var(--card-bg, #fff); font-family: inherit; outline: none; transition: .14s; }
.inp:focus { border-color: var(--primary, #1565c0); box-shadow: 0 0 0 3px color-mix(in srgb, var(--primary, #1565c0) 15%, transparent); }
.inp-date { width: 140px; }
.person .inp { width: 210px; }
.picked { font-size: 12.5px; font-weight: 700; color: var(--success, #2e9e5b); }
.cands { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; margin-top: 2px; }
.cands-lbl { font-size: 12px; color: var(--muted, #9b8070); }
.cand { border: 1px solid var(--primary, #1565c0); background: color-mix(in srgb, var(--primary, #1565c0) 8%, transparent); color: var(--primary, #1565c0); font-size: 12.5px; padding: 5px 11px; border-radius: 7px; cursor: pointer; font-family: inherit; }
.daterow { display: flex; align-items: center; gap: 8px; }
.sep { color: var(--muted, #9b8070); }
.quick { border: 1px solid var(--border, #d8c9b8); background: var(--card-bg, #fff); color: var(--muted, #9b8070); font-size: 12px; padding: 6px 10px; border-radius: 7px; cursor: pointer; font-family: inherit; }
.quick:hover { border-color: var(--primary, #1565c0); color: var(--primary, #1565c0); }
.go { margin-left: auto; background: var(--primary, #1565c0); color: #fff; border: none; padding: 9px 24px; border-radius: 9px; font-size: 14px; font-weight: 700; cursor: pointer; font-family: inherit; }
.go:disabled { opacity: .6; cursor: default; }

.quick.test { border-color: var(--primary, #1565c0); color: var(--primary, #1565c0); }
.diag { margin: 12px 16px 0; padding: 11px 14px; border-radius: 10px; font-size: 12.5px; line-height: 1.7;
  background: color-mix(in srgb, var(--success, #2e9e5b) 8%, transparent); border: 1px solid color-mix(in srgb, var(--success, #2e9e5b) 25%, transparent); }
.diag.bad { background: color-mix(in srgb, var(--danger, #d64545) 8%, transparent); border-color: color-mix(in srgb, var(--danger, #d64545) 28%, transparent); }
.diag-line { display: flex; align-items: center; gap: 10px; } .diag-line b { font-size: 13.5px; }
.diag-err { color: var(--danger, #d64545); }
.diag-x { margin-left: auto; border: none; background: none; color: var(--muted, #9b8070); cursor: pointer; font-size: 15px; }
.diag code { background: var(--surface-2, rgba(160,120,80,.1)); padding: 1px 6px; border-radius: 5px; font-size: 12px; margin: 0 2px; }
.diag-hint { margin-top: 4px; color: var(--text-2, #6b5a49); }
.diag-tpl { margin-top: 4px; }
.dt-tabs { display: flex; gap: 2px; padding: 0 12px; border-bottom: 1px solid var(--border, #eadfd2); }
.dt-tab { border: none; background: none; padding: 11px 16px; font-size: 14px; font-weight: 650; color: var(--muted, #9b8070); cursor: pointer; font-family: inherit; border-bottom: 2.5px solid transparent; margin-bottom: -1px; }
.dt-tab.on { color: var(--primary, #1565c0); border-bottom-color: var(--primary, #1565c0); }

.dt-summary { display: flex; align-items: center; gap: 15px; padding: 10px 16px; border-bottom: 1px solid var(--border, #eadfd2); flex-wrap: wrap; }
.dt-summary .s { font-size: 13px; color: var(--text, #4a3322); }
.dt-summary .s b { font-weight: 750; } .dt-summary .acc b { color: var(--primary, #1565c0); } .dt-summary .ok b { color: var(--success, #2e9e5b); }
.dt-summary .warn { color: var(--warn, #c47d0a); font-size: 12px; }
.grow { flex: 1; } .sellbl { font-size: 12px; color: var(--muted, #9b8070); }
.selq { border: 1px dashed var(--border, #d8c9b8); background: none; color: var(--primary, #1565c0); font-size: 12px; padding: 5px 10px; border-radius: 7px; cursor: pointer; font-family: inherit; }
.selq:hover { border-color: var(--primary, #1565c0); background: color-mix(in srgb, var(--primary, #1565c0) 7%, transparent); }

.dt-body { flex: 1; min-height: 0; overflow: auto; }
.empty { padding: 46px 20px; text-align: center; color: var(--muted, #9b8070); font-size: 13.5px; }
.empty.err { color: var(--danger, #d64545); }
.empty.hint .hint-i { font-size: 40px; margin-bottom: 10px; }
.empty.hint .hint-t { font-size: 16px; font-weight: 700; color: var(--text, #4a3322); }
.empty.hint .hint-s { max-width: 460px; margin: 8px auto 0; line-height: 1.6; }
.tablewrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 13.5px; }
thead th { text-align: left; padding: 10px 12px; font-size: 11.5px; font-weight: 700; letter-spacing: .03em; text-transform: uppercase; color: var(--muted, #9b8070); background: var(--surface-2, rgba(160,120,80,.06)); white-space: nowrap; position: sticky; top: 0; z-index: 1; }
thead th.r, td.r { text-align: right; } .cbcol { width: 38px; }
tbody td { padding: 11px 12px; border-top: 1px solid var(--border, #eadfd2); white-space: nowrap; vertical-align: middle; }
tbody tr:hover { background: var(--surface-2, rgba(160,120,80,.05)); }
tbody tr.sel { background: color-mix(in srgb, var(--primary, #1565c0) 8%, transparent); }
.ttlcell { white-space: normal; min-width: 220px; } .ttl { font-weight: 650; color: var(--text, #4a3322); }
.sub { font-size: 12px; color: var(--muted, #9b8070); margin-top: 1px; }
.tpl { color: var(--primary, #1565c0); font-weight: 600; }
.amt { font-weight: 700; font-variant-numeric: tabular-nums; color: var(--text, #4a3322); }
.payee { color: var(--text-2, #6b5a49); } .when { color: var(--muted, #9b8070); font-variant-numeric: tabular-nums; font-size: 12.5px; }
.cbx { width: 17px; height: 17px; accent-color: var(--primary, #1565c0); cursor: pointer; }
.pill { display: inline-flex; align-items: center; gap: 5px; font-size: 12px; font-weight: 700; padding: 3px 9px; border-radius: 20px; }
.pill i { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.p-run { color: var(--warn, #c47d0a); background: color-mix(in srgb, var(--warn, #c47d0a) 12%, transparent); }
.p-ok { color: var(--success, #2e9e5b); background: color-mix(in srgb, var(--success, #2e9e5b) 12%, transparent); }
.p-bad { color: var(--danger, #d64545); background: color-mix(in srgb, var(--danger, #d64545) 12%, transparent); }
.p-cancel { color: #8a7a68; background: rgba(138,122,104,.12); }
.sync { font-size: 12.5px; font-weight: 650; } .sync.no { color: var(--primary, #1565c0); } .sync.yes { color: var(--muted, #9b8070); } .sync.upd { color: var(--warn, #c47d0a); }
.sync .rec { font-size: 11px; color: var(--muted, #9b8070); font-variant-numeric: tabular-nums; }

.batchbar { position: fixed; left: 50%; transform: translateX(-50%); bottom: 22px; z-index: 40; display: flex; align-items: center; gap: 12px; background: #2c241d; color: #f4efe8; padding: 10px 12px 10px 20px; border-radius: 13px; box-shadow: 0 16px 40px -12px rgba(0,0,0,.5); }
.batchbar .n { font-size: 14px; } .batchbar .n b { font-size: 16px; font-weight: 800; color: #fff; }
.bb { border: none; padding: 9px 16px; border-radius: 9px; font-size: 13.5px; font-weight: 700; cursor: pointer; font-family: inherit; }
.bb.primary { background: var(--primary, #1565c0); color: #fff; } .bb.ghost { background: rgba(255,255,255,.15); color: #fff; }
.bb.x { background: none; color: rgba(255,255,255,.6); font-size: 17px; padding: 0 4px; }
.bb-enter-active, .bb-leave-active { transition: transform .26s, opacity .26s; }
.bb-enter-from, .bb-leave-to { transform: translateX(-50%) translateY(140%); opacity: 0; }

.scrim { position: fixed; inset: 0; background: rgba(30,22,14,.5); z-index: 60; display: flex; align-items: center; justify-content: center; padding: 20px; }
.modal { background: var(--card-bg, #fff); border-radius: 15px; width: min(660px, 100%); max-height: 86vh; display: flex; flex-direction: column; overflow: hidden; box-shadow: 0 20px 50px -14px rgba(0,0,0,.4); }
.m-head { padding: 18px 22px 13px; border-bottom: 1px solid var(--border, #eadfd2); }
.m-head h3 { margin: 0; font-size: 17px; font-weight: 750; color: var(--text, #4a3322); } .m-head p { margin: 5px 0 0; font-size: 13px; color: var(--muted, #9b8070); }
.m-body { padding: 6px 22px; overflow: auto; }
.conflict { display: flex; gap: 9px; background: color-mix(in srgb, var(--primary, #1565c0) 8%, transparent); border-radius: 9px; padding: 10px 13px; font-size: 12.5px; color: var(--text, #4a3322); line-height: 1.55; margin: 12px 0; }
.mtable { width: 100%; border-collapse: collapse; font-size: 13px; }
.mtable th { text-align: left; padding: 8px 10px; font-size: 11px; text-transform: uppercase; color: var(--muted, #9b8070); border-bottom: 1px solid var(--border, #eadfd2); }
.mtable td { padding: 9px 10px; border-bottom: 1px solid var(--border, #eadfd2); }
.tag { font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 6px; }
.tag.new { background: color-mix(in srgb, var(--primary, #1565c0) 14%, transparent); color: var(--primary, #1565c0); }
.tag.upd { background: color-mix(in srgb, var(--warn, #c47d0a) 16%, transparent); color: var(--warn, #c47d0a); }
.m-foot { padding: 14px 22px; border-top: 1px solid var(--border, #eadfd2); display: flex; gap: 10px; justify-content: flex-end; }
.btn { padding: 9px 18px; border-radius: 9px; font-size: 13.5px; font-weight: 700; cursor: pointer; font-family: inherit; border: 1px solid var(--border, #d8c9b8); background: var(--card-bg, #fff); color: var(--text-2, #6b5a49); }
.btn.primary { background: var(--primary, #1565c0); color: #fff; border-color: var(--primary, #1565c0); }
.btn:disabled { opacity: .6; cursor: default; }
</style>
