<script setup>
// 项目简称选择器：从项目台账（/ar/projects?q=）模糊搜索并选取 short_name。
// 后端在保存时会精确校验简称必须存在于台账——本组件负责把用户引导到合法值。
import { ref, watch } from 'vue'
import api from '../api/index.js'

const props = defineProps({
  modelValue: { type: String, default: '' },
  placeholder: { type: String, default: '模糊搜索项目台账简称（留空=不关联）' },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue', 'picked'])

const kw = ref(props.modelValue || '')
const sugs = ref([])
const open = ref(false)
const searching = ref(false)
let timer = null

watch(() => props.modelValue, v => { if (v !== kw.value) kw.value = v || '' })

function onInput(e) {
  kw.value = e.target.value
  emit('update:modelValue', kw.value)
  clearTimeout(timer)
  const q = kw.value.trim()
  if (!q) { sugs.value = []; open.value = false; return }
  timer = setTimeout(async () => {
    searching.value = true
    try {
      const r = await api.get('/ar/projects', { params: { q, size: 10 } })
      sugs.value = (r.data.items || []).filter(p => p.short_name)
      open.value = true
    } catch { sugs.value = [] }
    finally { searching.value = false }
  }, 300)
}
function pick(p) {
  kw.value = p.short_name
  emit('update:modelValue', p.short_name)
  emit('picked', p)
  open.value = false
}
function onBlur() { setTimeout(() => { open.value = false }, 180) }
</script>

<template>
  <div class="psn-wrap">
    <input :value="kw" :placeholder="placeholder" :disabled="disabled" autocomplete="off"
           @input="onInput" @focus="kw && onInput($event)" @blur="onBlur" />
    <div v-if="open" class="psn-drop">
      <div v-if="!sugs.length" class="psn-empty">
        {{ searching ? '搜索中…' : '台账中无匹配项目——请先在「项目台账」创建，否则保存将被拒绝' }}
      </div>
      <div v-for="p in sugs" :key="p.id" class="psn-item" @mousedown.prevent="pick(p)">
        <b>{{ p.short_name }}</b>
        <i>{{ p.delivery_dept }}<template v-if="p.sub_dept"> · {{ p.sub_dept }}</template> · {{ p.project_no }}</i>
      </div>
    </div>
  </div>
</template>

<style scoped>
.psn-wrap { position: relative; }
.psn-drop {
  position: absolute; top: calc(100% + 4px); left: 0; right: 0; z-index: 50;
  background: rgba(255,252,248,0.98); border: 1px solid var(--border);
  border-radius: 10px; box-shadow: 0 10px 30px rgba(100,60,30,0.18);
  max-height: 240px; overflow-y: auto; backdrop-filter: blur(10px);
}
.psn-item { padding: 8px 12px; cursor: pointer; display: flex; flex-direction: column; gap: 1px; }
.psn-item:hover { background: rgba(201,99,66,0.08); }
.psn-item b { font-size: 13px; color: var(--text); }
.psn-item i { font-style: normal; font-size: 11px; color: var(--muted); }
.psn-empty { padding: 10px 12px; font-size: 12px; color: var(--muted); }
</style>
