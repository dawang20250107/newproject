<script setup>
import { ref, computed, onMounted } from 'vue'
import ar from '../../api/ar.js'
import { fmtCompact } from '../../utils/format.js'

const emit = defineEmits(['close', 'fixed'])

const loading = ref(false)
const groups = ref([])
const err = ref('')

// 当前展开改挂的项目（源）及其应收记录
const activeProj = ref(null)      // 源项目对象
const records = ref([])
const recLoading = ref(false)
const selected = ref(new Set())
const targetId = ref('')
const moving = ref(false)
const toast = ref('')
let toastTimer = null

const wan = v => (v == null) ? '—' : (Number(v) / 1e4).toFixed(1) + '万'
function showToast(m) { toast.value = m; clearTimeout(toastTimer); toastTimer = setTimeout(() => toast.value = '', 2400) }

async function load() {
  loading.value = true; err.value = ''
  try {
    const res = await ar.duplicateNames()
    groups.value = res.data.groups || []
  } catch (e) { err.value = e?.error || e?.msg || '加载失败' }
  finally { loading.value = false }
}

// 当前源项目所在组的「其它项目」（作为改挂目标候选）
const targetOptions = computed(() => {
  if (!activeProj.value) return []
  const g = groups.value.find(g => g.projects.some(p => p.id === activeProj.value.id))
  return g ? g.projects.filter(p => p.id !== activeProj.value.id) : []
})

async function openProjectRecords(p) {
  activeProj.value = p
  selected.value = new Set()
  targetId.value = ''
  recLoading.value = true
  records.value = []
  try {
    const res = await ar.listRecords({ project_id: p.id, size: 200 })
    records.value = res.data.items || []
  } catch (e) { showToast(e?.error || '加载应收失败') }
  finally { recLoading.value = false }
}
function closeRecords() { activeProj.value = null; records.value = []; selected.value = new Set() }

function toggle(id) {
  const s = new Set(selected.value)
  s.has(id) ? s.delete(id) : s.add(id)
  selected.value = s
}
const allSel = computed(() => records.value.length > 0 && records.value.every(r => selected.value.has(r.id)))
function toggleAll() {
  const s = new Set(selected.value)
  if (allSel.value) records.value.forEach(r => s.delete(r.id))
  else records.value.forEach(r => s.add(r.id))
  selected.value = s
}

async function doReassign() {
  if (!selected.value.size) return showToast('请先勾选要改挂的应收记录')
  if (!targetId.value) return showToast('请选择改挂到的目标项目')
  const tgt = targetOptions.value.find(p => p.id === targetId.value)
  if (!confirm(`确认将 ${selected.value.size} 条应收从「${activeProj.value.short_name}（${activeProj.value.delivery_dept}）」改挂到「${tgt.short_name}（${tgt.delivery_dept}）」？\n系统会按目标项目自动重算交付部门与账期。`)) return
  moving.value = true
  try {
    const res = await ar.reassignRecords({ ids: [...selected.value], target_project_id: targetId.value })
    showToast(res.data?.message || '改挂完成')
    closeRecords()
    await load()
    emit('fixed')
  } catch (e) { showToast(e?.error || e?.msg || '改挂失败') }
  finally { moving.value = false }
}

onMounted(load)
</script>

<template>
  <Teleport to="body">
    <div class="dnf-mask" @click.self="emit('close')">
      <div class="dnf-modal">
        <div class="dnf-head">
          <div>
            <div class="dnf-title">🔍 同名项目排查与改挂</div>
            <div class="dnf-sub">同一项目简称分布在多个事业部时，历史应收可能挂错。下方按组列出，点项目可把挂错的应收改挂到正确项目（自动重算账期，无需删了重导）。</div>
          </div>
          <button class="dnf-x" @click="emit('close')">✕</button>
        </div>

        <div v-if="loading" class="dnf-empty">排查中…</div>
        <div v-else-if="err" class="dnf-empty err">{{ err }}</div>
        <div v-else-if="!groups.length" class="dnf-empty ok">✓ 未发现同名跨部门项目，数据干净</div>

        <div v-else class="dnf-body">
          <div class="dnf-count">共 {{ groups.length }} 组同名跨部门项目</div>
          <div v-for="g in groups" :key="g.short_name" class="dnf-group">
            <div class="dnf-gname">「{{ g.short_name }}」<span class="dnf-gtag">{{ g.dept_count }} 个事业部</span></div>
            <table class="dnf-table">
              <thead>
                <tr><th class="l">交付部门</th><th>客户</th><th class="r">应收条数</th><th class="r">上账金额</th><th class="r">未收</th><th></th></tr>
              </thead>
              <tbody>
                <tr v-for="p in g.projects" :key="p.id" :class="{ hot: p.record_count > 0 }">
                  <td class="l"><b>{{ p.delivery_dept }}</b><span v-if="p.is_draft" class="draft-tag">草稿</span></td>
                  <td class="cust">{{ p.customer_name }}</td>
                  <td class="r" :class="{ many: p.record_count > 0 }">{{ p.record_count }}</td>
                  <td class="r">{{ wan(p.estimated) }}</td>
                  <td class="r">{{ wan(p.outstanding) }}</td>
                  <td class="r"><button v-if="p.record_count > 0" class="dnf-fix-btn" @click="openProjectRecords(p)">改挂应收 ›</button></td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>

    <!-- 改挂子弹窗 -->
    <div v-if="activeProj" class="dnf-mask dnf-mask2" @click.self="closeRecords">
      <div class="dnf-reassign">
        <div class="dnf-head">
          <div>
            <div class="dnf-title">改挂应收 · {{ activeProj.short_name }}（{{ activeProj.delivery_dept }}）</div>
            <div class="dnf-sub">勾选本该属于其它部门的应收 → 选目标项目 → 改挂</div>
          </div>
          <button class="dnf-x" @click="closeRecords">✕</button>
        </div>

        <div class="dnf-reassign-bar">
          <span class="rb-sel">已选 <b>{{ selected.size }}</b> 条</span>
          <span class="rb-arrow">改挂到 →</span>
          <select v-model="targetId" class="rb-sel-input">
            <option value="">选择目标项目…</option>
            <option v-for="t in targetOptions" :key="t.id" :value="t.id">{{ t.short_name }}（{{ t.delivery_dept }}）</option>
          </select>
          <button class="rb-go" :disabled="moving || !selected.size || !targetId" @click="doReassign">{{ moving ? '改挂中…' : '确认改挂' }}</button>
        </div>

        <div v-if="recLoading" class="dnf-empty">加载应收…</div>
        <div v-else-if="!records.length" class="dnf-empty">该项目暂无应收记录</div>
        <div v-else class="dnf-rec-wrap">
          <table class="dnf-table">
            <thead>
              <tr>
                <th class="c"><input type="checkbox" :checked="allSel" @change="toggleAll" /></th>
                <th>运作年月</th><th class="r">上账金额</th><th class="r">未收</th><th class="l">备注</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in records" :key="r.id" :class="{ sel: selected.has(r.id) }" @click="toggle(r.id)">
                <td class="c"><input type="checkbox" :checked="selected.has(r.id)" @change.stop="toggle(r.id)" /></td>
                <td>{{ r.operation_year }}年{{ r.operation_month }}月</td>
                <td class="r">{{ wan(r.estimated_amount) }}</td>
                <td class="r">{{ wan(r.outstanding_amount) }}</td>
                <td class="l notes">{{ r.notes || '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <div v-if="toast" class="dnf-toast">{{ toast }}</div>
  </Teleport>
</template>

<style scoped>
.dnf-mask { position: fixed; inset: 0; background: rgba(0,0,0,.4); z-index: 4000; display: flex; align-items: center; justify-content: center; }
.dnf-mask2 { z-index: 4100; background: rgba(0,0,0,.5); }
.dnf-modal, .dnf-reassign { background: #fdfbf8; border-radius: 14px; width: 860px; max-width: 95vw; max-height: 88vh; display: flex; flex-direction: column; box-shadow: 0 20px 60px rgba(0,0,0,.28); }
.dnf-reassign { width: 680px; }
.dnf-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; padding: 18px 22px; border-bottom: 1px solid #eee2d4; }
.dnf-title { font-size: 16px; font-weight: 800; color: #3a2c1d; }
.dnf-sub { font-size: 12px; color: #9b8070; margin-top: 4px; line-height: 1.5; max-width: 680px; }
.dnf-x { border: none; background: none; font-size: 18px; color: #9b8070; cursor: pointer; }
.dnf-empty { text-align: center; padding: 50px; color: #9e9e9e; }
.dnf-empty.err { color: #c62828; }
.dnf-empty.ok { color: #2e7d32; font-size: 15px; }
.dnf-body { overflow-y: auto; padding: 16px 22px; }
.dnf-count { font-size: 12px; color: #9b8070; margin-bottom: 10px; }
.dnf-group { margin-bottom: 18px; border: 1px solid #eee2d4; border-radius: 10px; overflow: hidden; }
.dnf-gname { background: #f5efe8; padding: 9px 14px; font-weight: 700; color: #4a3728; font-size: 13.5px; }
.dnf-gtag { font-size: 11px; font-weight: 600; color: #c0392b; background: rgba(192,57,43,.1); border-radius: 8px; padding: 1px 8px; margin-left: 8px; }
.dnf-table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.dnf-table th { background: #faf6f1; color: #6b5a4a; padding: 7px 12px; font-weight: 600; text-align: right; }
.dnf-table th.l { text-align: left; } .dnf-table th.c { text-align: center; width: 38px; }
.dnf-table td { padding: 7px 12px; border-top: 1px solid #f0e8de; text-align: right; color: #2d2010; }
.dnf-table td.l { text-align: left; } .dnf-table td.c { text-align: center; }
.dnf-table tr.hot td { background: #fffdf8; }
.dnf-table td.many { color: #c0392b; font-weight: 800; }
.draft-tag { font-size: 10px; background: #fce4e4; color: #c0392b; border-radius: 5px; padding: 0 5px; margin-left: 6px; }
.cust { color: #6b5a4a; max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dnf-fix-btn { font-size: 11.5px; padding: 2px 10px; border: 1px solid var(--primary); background: rgba(201,99,66,.06); color: var(--primary); border-radius: 7px; cursor: pointer; white-space: nowrap; }
.dnf-fix-btn:hover { background: rgba(201,99,66,.14); }

.dnf-reassign-bar { display: flex; align-items: center; gap: 10px; padding: 12px 22px; background: rgba(21,101,192,.05); border-bottom: 1px solid #eee2d4; }
.rb-sel { font-size: 13px; color: #3a2c1d; } .rb-sel b { color: #1565c0; }
.rb-arrow { font-size: 12px; color: #9b8070; }
.rb-sel-input { flex: 1; padding: 6px 10px; border: 1px solid #d4b896; border-radius: 7px; font-size: 13px; background: #fff; }
.rb-go { padding: 6px 16px; background: var(--primary); color: #fff; border: none; border-radius: 7px; font-size: 13px; cursor: pointer; }
.rb-go:disabled { opacity: .5; cursor: default; }
.dnf-rec-wrap { overflow-y: auto; padding: 8px 22px 18px; }
.dnf-rec-wrap tr { cursor: pointer; }
.dnf-rec-wrap tr.sel td { background: rgba(21,101,192,.07); }
.notes { color: #9b8070; max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dnf-toast { position: fixed; bottom: 28px; left: 50%; transform: translateX(-50%); background: #2e7d32; color: #fff; padding: 9px 22px; border-radius: 20px; font-size: 13px; z-index: 5000; }
</style>
