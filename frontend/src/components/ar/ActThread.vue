<script setup>
// 活动时间线（对账/开票/回款/催款四阶段共用）——从 ActivityPanel 抽出，
// 消灭原先四段几乎相同的模板拷贝。展示 + 行内编辑/删除/状态轮换的 API
// 调用在本组件内完成，结果通过 updated/deleted 事件回传父级，父级仍是
// allActivities 的唯一数据源（并负责 activity_count 计数同步）。
import { ref, reactive } from 'vue'
import ar from '../../api/ar.js'
import { useToast } from '../../composables/useToast.js'
import { confirmDlg } from '../../composables/confirm.js'

const props = defineProps({
  recId: { type: Number, required: true },
  acts:  { type: Array, default: () => [] },
})
const emit = defineEmits(['updated', 'deleted'])
const toast = useToast()
const errMsg = e => e?.msg || e?.error || '操作失败'

const ACT_ICON = { call: '📞', email: '📧', visit: '🚶', meeting: '💬', system: '⚙️', note: '📝', other: '💡' }
const STATUS_COLOR = { in_progress: '#1565c0', pending: '#e8830c', resolved: '#2e7d32', no_response: '#9e9e9e' }
const STATUSES = [
  { v: 'in_progress', l: '跟进中' }, { v: 'pending', l: '待回复' },
  { v: 'resolved',    l: '已解决' }, { v: 'no_response', l: '无响应' },
]

const editId = ref(null)
const buf = reactive({ note: '', status: 'in_progress', follow_up_date: '' })

function startEdit(act) {
  editId.value = act.id
  buf.note = act.note || ''
  buf.status = act.status || 'in_progress'
  buf.follow_up_date = act.follow_up_date || ''
}
async function commitEdit(act) {
  if (!buf.note.trim()) return
  try {
    const res = await ar.updateActivity(props.recId, act.id, {
      note: buf.note, status: buf.status, follow_up_date: buf.follow_up_date || null,
    })
    emit('updated', res.data)
    editId.value = null
    toast.success('已更新')
  } catch (e) { toast.error(errMsg(e)) }
}
async function del(act) {
  if (!(await confirmDlg(`删除这条${act.act_type_display || ''}记录？`))) return
  try {
    await ar.deleteActivity(props.recId, act.id)
    emit('deleted', act)
    toast.success('已删除')
  } catch (e) { toast.error(errMsg(e)) }
}
async function cycleStatus(act) {
  if (!act.can_edit) return
  const order = ['in_progress', 'pending', 'resolved', 'no_response']
  const next = order[(order.indexOf(act.status) + 1) % order.length]
  try {
    const res = await ar.updateActivity(props.recId, act.id, { note: act.note, status: next })
    emit('updated', res.data)
  } catch (e) { toast.error(errMsg(e)) }
}
const fmtTime = iso => (iso ? iso.replace('T', ' ').slice(0, 16) : '')
</script>

<template>
  <div class="nd-acts">
    <div v-for="act in acts" :key="act.id" class="act-item"
      :style="`--sc:${STATUS_COLOR[act.status] || '#888'}`">
      <span class="act-dot">{{ ACT_ICON[act.act_type] || '💬' }}</span>
      <div class="act-main">
        <div class="act-top">
          <span class="act-who">{{ act.created_by_name || '—' }}</span>
          <button class="act-st" @click="cycleStatus(act)">{{ act.status_display }}</button>
          <span class="act-time">{{ fmtTime(act.created_at) }}</span>
          <template v-if="act.can_edit && editId !== act.id">
            <button class="act-ico" @click="startEdit(act)">✏️</button>
            <button class="act-ico act-ico-del" @click="del(act)">🗑</button>
          </template>
        </div>
        <template v-if="editId === act.id">
          <!-- Esc 取消编辑并阻断冒泡，避免触发面板级 Esc 关闭 -->
          <textarea v-model="buf.note" class="act-edit-ta" rows="2"
                    @keydown.esc.stop="editId = null"></textarea>
          <div class="act-edit-foot">
            <select v-model="buf.status" class="act-sel"><option v-for="s in STATUSES" :key="s.v" :value="s.v">{{ s.l }}</option></select>
            <input v-model="buf.follow_up_date" type="date" class="act-sel" />
            <button class="act-save" @click="commitEdit(act)">保存</button>
            <button class="act-cancel" @click="editId = null">取消</button>
          </div>
        </template>
        <template v-else>
          <div class="act-note">{{ act.note }}</div>
          <div v-if="act.follow_up_date" class="act-fu">📅 计划跟进 {{ act.follow_up_date }}</div>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.nd-acts { display: flex; flex-direction: column; gap: 0; position: relative; }
.nd-acts::before {
  content: ''; position: absolute;
  left: 13px; top: 14px; bottom: 14px; width: 2px;
  background: linear-gradient(180deg, rgba(160,120,80,.2) 0%, rgba(160,120,80,.05) 100%);
  border-radius: 2px;
}
.act-item { display: flex; gap: 10px; padding-bottom: 9px; position: relative; }
.act-item:last-child { padding-bottom: 0; }
.act-dot {
  width: 28px; height: 28px; flex-shrink: 0; border-radius: 50%;
  display: flex; align-items: center; justify-content: center; font-size: 13px;
  background: var(--row-bg);
  border: 2px solid var(--sc, #888);
  box-shadow: 0 0 0 3px #fff, 0 2px 8px rgba(0,0,0,.1);
  z-index: 1; position: relative;
}
.act-main {
  flex: 1; min-width: 0;
  background: #faf7f3;
  border: 1px solid rgba(160,120,80,.14);
  border-left: 3px solid var(--sc, #888);
  border-radius: 10px;
  padding: 7px 11px;
  box-shadow: 0 1px 4px rgba(40,20,8,.05);
  transition: box-shadow .14s;
}
.act-main:hover { box-shadow: 0 3px 10px rgba(40,20,8,.08); }
.act-top { display: flex; align-items: center; gap: 5px; flex-wrap: wrap; }
.act-who { font-size: 11.5px; font-weight: 800; color: #4a3322; }
.act-st {
  border: none; font-size: 9.5px; font-weight: 700; cursor: pointer;
  padding: 2px 8px; border-radius: 20px;
  color: var(--sc); background: color-mix(in srgb, var(--sc) 12%, transparent);
  transition: opacity .12s;
}
.act-st:hover { opacity: .8; }
.act-time { font-size: 10px; color: #c4b3a5; margin-left: auto; font-variant-numeric: tabular-nums; }
.act-ico  { border: none; background: none; font-size: 11px; cursor: pointer; padding: 2px 3px; border-radius: 4px; opacity: .6; transition: opacity .12s; }
.act-ico:hover { opacity: 1; background: rgba(0,0,0,.05); }
.act-note { font-size: 12.5px; color: #4a3322; white-space: pre-wrap; word-break: break-word; line-height: 1.55; margin-top: 4px; }
.act-fu   { font-size: 10.5px; color: #a8917e; margin-top: 3px; font-weight: 600; }
.act-edit-ta { width: 100%; border: 1.5px solid rgba(201,99,66,.4); border-radius: 7px; padding: 5px 8px; font-size: 12.5px; color: #4a3322; resize: vertical; font-family: inherit; box-sizing: border-box; outline: none; margin-top: 5px; }
.act-edit-foot { display: flex; gap: 5px; align-items: center; flex-wrap: wrap; margin-top: 6px; }
.act-sel  { border: 1.5px solid rgba(160,120,80,.28); border-radius: 7px; font-size: 11.5px; padding: 3px 7px; color: #4a3322; background: var(--row-bg); outline: none; font-family: inherit; }
.act-save { padding: 3px 13px; border: none; border-radius: 7px; background: var(--ac, var(--primary)); color: #fff; font-size: 11.5px; font-weight: 700; cursor: pointer; margin-left: auto; }
.act-cancel { padding: 3px 10px; border: 1.5px solid rgba(160,120,80,.28); border-radius: 7px; background: var(--row-bg); font-size: 11.5px; cursor: pointer; color: #9b8070; }
</style>
