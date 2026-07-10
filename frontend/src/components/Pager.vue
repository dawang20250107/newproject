<script setup>
// 统一分页器（系统级复用）：上一页/下一页 + 页码/总数 + 跳页 + 每页条数（可选持久化）。
// 用法：<Pager v-model:page="page" :total="total" v-model:size="size" storage-key="ar_advances"
//             @change="load" />
// 传 storage-key 时每页条数记忆到 localStorage（pk_pager_size:<key>），跨会话生效。
import { ref, computed, watch, onMounted } from 'vue'

const props = defineProps({
  page: { type: Number, default: 1 },
  total: { type: Number, default: 0 },          // 总条数
  size: { type: Number, default: 50 },
  sizes: { type: Array, default: () => [20, 50, 100] },
  storageKey: { type: String, default: '' },
})
const emit = defineEmits(['update:page', 'update:size', 'change'])

const totalPages = computed(() => Math.max(1, Math.ceil((props.total || 0) / (props.size || 1))))
const jump = ref(null)

function go(p) {
  const n = Math.min(Math.max(1, p), totalPages.value)
  if (n === props.page) return
  emit('update:page', n)
  emit('change')
}
function doJump() {
  if (jump.value == null || jump.value === '') return
  go(Number(jump.value))
  jump.value = null
}
function setSize(e) {
  const n = Number(e.target.value)
  if (props.storageKey) {
    try { localStorage.setItem(`pk_pager_size:${props.storageKey}`, String(n)) } catch { /* 隐私模式等 */ }
  }
  emit('update:size', n)
  emit('update:page', 1)   // 改每页条数回到第一页，避免落在越界页
  emit('change')
}
onMounted(() => {
  if (!props.storageKey) return
  try {
    const saved = Number(localStorage.getItem(`pk_pager_size:${props.storageKey}`))
    if (saved && props.sizes.includes(saved) && saved !== props.size) {
      emit('update:size', saved)
      emit('change')
    }
  } catch { /* ignore */ }
})
// 数据变化把当前页挤出范围时（如筛选后总数骤减）自动回落到最后一页
watch(totalPages, tp => { if (props.page > tp) { emit('update:page', tp); emit('change') } })
</script>

<template>
  <div v-if="total > 0" class="pgr">
    <button class="btn btn-ghost btn-sm" :disabled="page <= 1" @click="go(page - 1)">上一页</button>
    <span class="pgr-info">{{ page }} / {{ totalPages }}<i>（共 {{ total }} 条）</i></span>
    <button class="btn btn-ghost btn-sm" :disabled="page >= totalPages" @click="go(page + 1)">下一页</button>
    <span v-if="totalPages > 1" class="pgr-jump">
      到第<input v-model.number="jump" type="number" :min="1" :max="totalPages"
                 :placeholder="`1-${totalPages}`" @keyup.enter="doJump" />页
    </span>
    <label class="pgr-size">
      每页
      <select :value="size" @change="setSize">
        <option v-for="s in sizes" :key="s" :value="s">{{ s }}</option>
      </select>
      条
    </label>
  </div>
</template>

<style scoped>
.pgr { display: flex; align-items: center; justify-content: center; gap: 12px;
  margin-top: 12px; font-size: 13px; color: var(--muted); flex-wrap: wrap; flex-shrink: 0; }
.pgr-info { font-variant-numeric: tabular-nums; }
.pgr-info i { font-style: normal; opacity: .8; margin-left: 2px; }
.pgr-jump { display: inline-flex; align-items: center; gap: 4px; }
.pgr-jump input { width: 52px; text-align: center; padding: 3px 4px;
  border: 1px solid var(--border); border-radius: 6px; font-size: 13px;
  background: var(--card); color: var(--text); }
.pgr-size { display: inline-flex; align-items: center; gap: 4px; }
.pgr-size select { width: auto; padding: 3px 26px 3px 8px; font-size: 12.5px;
  border-radius: 6px; border: 1px solid var(--border); }
</style>
