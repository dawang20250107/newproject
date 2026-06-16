<script setup>
import { ref, computed } from 'vue'
import { useAuthStore } from '../stores/auth.js'

const props = defineProps({
  // forced=true：超管重置后强制改密，不可取消/关闭
  forced: { type: Boolean, default: false },
})
const emit = defineEmits(['close'])
const auth = useAuthStore()

const oldPwd = ref('')
const newPwd = ref('')
const confirmPwd = ref('')
const saving = ref(false)
const error = ref('')

// 前端即时强度提示（与后端口径一致，最终以后端校验为准）
const strength = computed(() => {
  const p = newPwd.value
  if (!p) return ''
  if (p.length < 8) return '至少 8 位'
  if (!/[a-zA-Z]/.test(p) || !/\d/.test(p)) return '需同时包含字母和数字'
  if (new Set(p).size <= 2) return '字符种类太少'
  return 'ok'
})
const canSubmit = computed(() =>
  oldPwd.value && strength.value === 'ok' && newPwd.value === confirmPwd.value && !saving.value)

async function submit() {
  error.value = ''
  if (newPwd.value !== confirmPwd.value) { error.value = '两次输入的新密码不一致'; return }
  saving.value = true
  try {
    await auth.changePassword(oldPwd.value, newPwd.value)
    emit('close', true)
  } catch (e) {
    error.value = e?.msg || e?.error || '修改失败，请重试'
  } finally {
    saving.value = false
  }
}
function onCancel() {
  if (props.forced) return
  emit('close', false)
}
</script>

<template>
  <Teleport to="body">
    <div class="modal-overlay" @click.self="onCancel">
      <div class="modal-box" style="max-width:420px">
        <div class="modal-header"><h3>{{ forced ? '请先修改初始密码' : '修改密码' }}</h3></div>
        <div class="modal-body">
          <p v-if="forced" class="cp-hint">管理员已为你重置了临时密码，为账号安全，请设置一个新密码后继续使用。</p>
          <div class="cp-field">
            <label>原密码</label>
            <input v-model="oldPwd" type="password" autocomplete="current-password" placeholder="请输入当前密码" @keyup.enter="submit" />
          </div>
          <div class="cp-field">
            <label>新密码</label>
            <input v-model="newPwd" type="password" autocomplete="new-password" placeholder="至少8位，含字母和数字" @keyup.enter="submit" />
            <span v-if="newPwd && strength !== 'ok'" class="cp-weak">{{ strength }}</span>
            <span v-else-if="newPwd" class="cp-ok">强度合格</span>
          </div>
          <div class="cp-field">
            <label>确认新密码</label>
            <input v-model="confirmPwd" type="password" autocomplete="new-password" placeholder="再次输入新密码" @keyup.enter="submit" />
            <span v-if="confirmPwd && confirmPwd !== newPwd" class="cp-weak">两次输入不一致</span>
          </div>
          <p v-if="error" class="cp-error">{{ error }}</p>
        </div>
        <div class="modal-footer">
          <button v-if="!forced" class="btn btn-ghost" @click="onCancel">取消</button>
          <button class="btn btn-primary" :disabled="!canSubmit" @click="submit">{{ saving ? '提交中…' : '确认修改' }}</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.cp-hint { font-size: 13px; color: #8a6d1a; background: rgba(255,213,79,.14);
  border: 1px solid rgba(255,193,7,.35); border-radius: 9px; padding: 9px 12px; margin: 0 0 14px; line-height: 1.6; }
.cp-field { margin-bottom: 14px; display: flex; flex-direction: column; gap: 6px; }
.cp-field label { font-size: 12.5px; color: var(--muted); font-weight: 600; }
.cp-field input { width: 100%; padding: 9px 12px; border: 1.5px solid var(--border);
  border-radius: 8px; font-size: 14px; box-sizing: border-box; }
.cp-field input:focus { border-color: var(--primary); outline: none; }
.cp-weak { font-size: 11.5px; color: var(--danger); }
.cp-ok { font-size: 11.5px; color: #2e7d32; }
.cp-error { font-size: 13px; color: var(--danger); margin: 4px 0 0; }
</style>
