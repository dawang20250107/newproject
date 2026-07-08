<script setup>
/* 预设 + 自定义 二合一选择器：预设作为可点胶囊，点「＋ 自定义」内联输入；
   自定义值自动变成一枚高亮胶囊，可点笔改、点✕清。始终恰有一个处于选中态，直观。 */
import { ref, computed, nextTick } from 'vue'
const props = defineProps({
  modelValue: { type: String, default: '' },
  presets: { type: Array, default: () => [] },
  placeholder: { type: String, default: '自定义…' },
  allowClear: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue'])
const editing = ref(false)
const draft = ref('')
const inputEl = ref(null)
const isCustom = computed(() => !!props.modelValue && !props.presets.includes(props.modelValue))
function pick(v) { editing.value = false; emit('update:modelValue', v) }
async function startCustom() {
  draft.value = isCustom.value ? props.modelValue : ''
  editing.value = true
  await nextTick(); inputEl.value?.focus()
}
function commit() {
  const v = draft.value.trim()
  editing.value = false
  if (v) emit('update:modelValue', v)
}
</script>

<template>
  <div class="pp">
    <button v-for="p in presets" :key="p" type="button" class="pp-pill" :class="{ on: modelValue === p }" @click="pick(p)">{{ p }}</button>
    <!-- 已选的自定义值：显示为高亮胶囊 -->
    <span v-if="isCustom && !editing" class="pp-pill on custom">
      {{ modelValue }}
      <i class="pp-edit" title="修改" @click.stop="startCustom">✎</i>
      <i v-if="allowClear" class="pp-clear" title="清除" @click.stop="pick('')">✕</i>
    </span>
    <!-- 自定义输入 -->
    <span v-if="editing" class="pp-input">
      <input ref="inputEl" v-model="draft" :placeholder="placeholder" @keyup.enter="commit" @keyup.esc="editing = false" @blur="commit" />
    </span>
    <button v-else type="button" class="pp-add" :class="{ dim: isCustom }" @click="startCustom">
      {{ isCustom ? '改自定义' : '＋ 自定义' }}
    </button>
  </div>
</template>

<style scoped>
.pp { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; }
.pp-pill { border: 1px solid var(--border, #d8c9b8); background-color: var(--card-bg, #fff); color: var(--text, #4a3322); border-radius: 9px; padding: 7px 14px; font-size: 13px; cursor: pointer; font-family: inherit; transition: .14s; display: inline-flex; align-items: center; gap: 6px; }
.pp-pill:hover { border-color: var(--primary, #1565c0); }
.pp-pill.on { background: var(--primary, #1565c0); border-color: var(--primary, #1565c0); color: #fff; font-weight: 650; box-shadow: 0 5px 14px -5px color-mix(in srgb, var(--primary, #1565c0) 55%, transparent); }
.pp-pill.custom { padding-right: 8px; }
.pp-edit, .pp-clear { font-style: normal; font-size: 11px; opacity: .8; cursor: pointer; }
.pp-edit:hover, .pp-clear:hover { opacity: 1; }
.pp-add { border: 1px dashed var(--primary, #1565c0); background: none; color: var(--primary, #1565c0); border-radius: 9px; padding: 7px 13px; font-size: 12.5px; cursor: pointer; font-family: inherit; font-weight: 600; }
.pp-add.dim { border-style: solid; opacity: .8; }
.pp-input input { border: 1px solid var(--primary, #1565c0); border-radius: 9px; padding: 7px 11px; font-size: 13px; font-family: inherit; width: 150px; outline: none; box-shadow: 0 0 0 3px color-mix(in srgb, var(--primary, #1565c0) 14%, transparent); background: var(--card-bg, #fff); color: var(--text, #4a3322); }
</style>
