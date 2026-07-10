<script setup>
// 附件块（四阶段共用）——文件列表 + 拖拽/点击上传区。上传与删除的 API
// 调用留在父级（ActivityPanel 需要同步 attachment_count 与全局附件数组），
// 本组件只负责展示与收集文件，通过 upload/del 事件上抛。
import { ref } from 'vue'

defineProps({
  atts:     { type: Array, default: () => [] },
  canWrite: { type: Boolean, default: false },
  label:    { type: String, default: '⬆ 上传附件' },
})
const emit = defineEmits(['upload', 'del'])
const ACCEPT = '.jpg,.jpeg,.png,.gif,.webp,.pdf,.xlsx,.xls,.docx,.doc,.txt,.csv'
const dragOver = ref(false)

function fileIcon(att) {
  const ext = (att.file_name || '').split('.').pop().toLowerCase()
  if (ext === 'pdf') return '📄'
  if (['xlsx', 'xls', 'csv'].includes(ext)) return '📊'
  if (['docx', 'doc'].includes(ext)) return '📝'
  return '📎'
}
function fmtSize(b) {
  if (b == null) return ''
  if (b < 1024)    return b + 'B'
  if (b < 1048576) return (b / 1024).toFixed(1) + 'KB'
  return (b / 1048576).toFixed(1) + 'MB'
}
function onDrop(e) {
  dragOver.value = false
  const f = e.dataTransfer?.files?.[0]
  if (f) emit('upload', f)
}
function onPick(e) {
  const f = e.target.files[0]
  if (f) emit('upload', f)
  e.target.value = ''
}
</script>

<template>
  <div class="nd-atts">
    <div v-for="att in atts.filter(a => !a.is_image)" :key="att.id" class="att-file">
      <span>{{ fileIcon(att) }}</span>
      <a :href="att.download_url" target="_blank" class="att-fname">{{ att.file_name }}</a>
      <span class="att-meta">{{ fmtSize(att.file_size) }}</span>
      <button v-if="canWrite" class="att-del" @click="emit('del', att)">✕</button>
    </div>
    <div v-if="canWrite" class="att-dz" :class="{ over: dragOver }"
      @dragover.prevent="dragOver = true" @dragleave="dragOver = false" @drop.prevent="onDrop">
      {{ label }}
      <input type="file" class="att-dz-inp" :accept="ACCEPT" @change="onPick" />
    </div>
  </div>
</template>

<style scoped>
.nd-atts { display: flex; flex-direction: column; gap: 5px; }
.att-file {
  display: flex; align-items: center; gap: 8px;
  background: #faf7f3; border: 1px solid rgba(160,120,80,.15);
  border-radius: 9px; padding: 5px 10px;
}
.att-fname { flex: 1; min-width: 0; font-size: 11.5px; color: var(--c-info); text-decoration: none; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 600; }
.att-fname:hover { text-decoration: underline; }
.att-meta { font-size: 10px; color: #a8917e; flex-shrink: 0; }
.att-del  { border: none; background: none; color: #c4b3a5; font-size: 11px; cursor: pointer; flex-shrink: 0; transition: color .12s; }
.att-del:hover { color: var(--c-danger); }
.att-dz {
  border: 2px dashed rgba(160,120,80,.28); border-radius: 10px;
  padding: 8px; text-align: center; font-size: 11px; color: #b0987e;
  cursor: pointer; position: relative; transition: all .16s;
}
.att-dz:hover, .att-dz.over {
  background: color-mix(in srgb, var(--ac, var(--primary)) 5%, transparent);
  border-color: var(--ac, var(--primary)); color: var(--ac, var(--primary));
}
.att-dz-inp { position: absolute; inset: 0; opacity: 0; cursor: pointer; }
</style>
