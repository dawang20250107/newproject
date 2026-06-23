// 通用「列表筛选方案」基座（前端）：把任意列表页的「列头筛选 colFilters + 排序」
// 存成命名方案（私有/公共团队共享 + 默认方案，跟随账号）。后端 /pk/list-schemes。
//
// 用法：
//   const sch = useTableSchemes('pk_payments', { colFilters, sortField, sortOrder, onApply: () => load(true) })
//   <SchemePicker :ctl="sch" :can-public="auth.canCreate" />
import { ref, computed } from 'vue'
import api from '../api/index.js'
import { useToast } from './useToast.js'
import { useAuthStore } from '../stores/auth.js'

// extra（可选）：页面专属状态的存取钩子 { get: () => ({...}), set: (payload) => {...} }，
// 用于把 colFilters 之外的筛选（如单选状态列）一并纳入方案快照。
export function useTableSchemes(module, { colFilters, sortField, sortOrder, onApply, extra }) {
  const toast = useToast()
  const auth = useAuthStore()

  const schemes = ref([])
  const defaultSchemeId = ref(null)
  const loaded = ref(false)
  const showDrop = ref(false)
  const newName = ref('')
  const newScope = ref('private')

  const mySchemes = computed(() => schemes.value.filter(s => s.scope === 'private'))
  const publicSchemes = computed(() => schemes.value.filter(s => s.scope === 'public'))
  const isMine = s => s.owner_id === auth.user?.id
  const isDefault = s => s.id === defaultSchemeId.value
  const extraHas = () => {
    const e = extra?.get?.()
    return e && Object.values(e).some(v => v !== '' && v != null && !(Array.isArray(v) && !v.length))
  }
  const hasState = () => Object.keys(colFilters).length > 0 || !!sortField.value || extraHas()

  // 当前列表状态 → 方案快照
  function capture() {
    return {
      colFilters: JSON.parse(JSON.stringify(colFilters)),
      sort: sortField.value || '',
      order: sortOrder.value || '',
      ...(extra?.get?.() || {}),
    }
  }
  // 方案快照 → 应用到列表（清空再套用），随后回调刷新
  function applyScheme(s) {
    const p = s.payload || {}
    Object.keys(colFilters).forEach(k => delete colFilters[k])
    Object.assign(colFilters, p.colFilters || {})
    sortField.value = p.sort || ''
    sortOrder.value = p.order || ''
    extra?.set?.(p)
    showDrop.value = false
    onApply && onApply()
  }

  async function load() {
    try {
      const res = await api.get('/list-schemes', { params: { module } })
      schemes.value = res.data.items || []
      defaultSchemeId.value = res.data.default_id || null
    } catch { schemes.value = [] }
    finally { loaded.value = true }
  }

  async function saveCurrent() {
    const name = newName.value.trim()
    if (!name) return
    try {
      await api.post('/list-schemes', { module, name, scope: newScope.value, payload: capture() })
      newName.value = ''
      showDrop.value = false
      await load()
      toast.success(`已保存${newScope.value === 'public' ? '公共' : '私有'}方案「${name}」`)
    } catch (e) { toast.error(e?.msg || e?.error || '保存失败') }
  }

  async function remove(s) {
    if (!confirm(`删除方案「${s.name}」？${s.scope === 'public' ? '（公共方案，团队成员将不再可见）' : ''}`)) return
    try {
      await api.delete(`/list-schemes/${s.id}`)
      await load()
    } catch (e) { toast.error(e?.msg || e?.error || '删除失败') }
  }

  async function toggleDefault(s) {
    const next = defaultSchemeId.value === s.id ? null : s.id
    try {
      await api.post('/list-schemes/set-default', { module, scheme_id: next })
      defaultSchemeId.value = next
    } catch (e) { toast.error(e?.msg || e?.error || '设置默认失败') }
  }

  // 进页调用：拉方案；若有默认方案则套用并返回 true（调用方据此决定是否还要默认加载）
  async function loadAndApplyDefault() {
    await load()
    const def = defaultSchemeId.value && schemes.value.find(s => s.id === defaultSchemeId.value)
    if (def) { applyScheme(def); return true }
    return false
  }

  return {
    schemes, mySchemes, publicSchemes, defaultSchemeId, loaded,
    showDrop, newName, newScope,
    isMine, isDefault, hasState,
    load, applyScheme, saveCurrent, remove, toggleDefault, loadAndApplyDefault,
  }
}
