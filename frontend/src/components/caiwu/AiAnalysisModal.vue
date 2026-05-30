<script setup>
import { computed } from 'vue'

const props = defineProps({
  visible: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
  text: { type: String, default: '' },
  error: { type: String, default: '' },
  title: { type: String, default: 'AI 智能分析' },
  subtitle: { type: String, default: '' },
})

const emit = defineEmits(['close', 'reanalyze'])

const paragraphs = computed(() => {
  if (!props.text) return []
  return props.text.split(/\n\n+/).map(para =>
    para
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/\n/g, '<br>')
  )
})
</script>

<template>
  <Transition name="ai-fade">
    <div v-if="visible" class="ai-mask" @click.self="emit('close')">
      <div class="ai-modal">
        <!-- Animated tech border glow -->
        <div class="ai-glow"></div>

        <div class="ai-head">
          <div class="ai-title-wrap">
            <span class="ai-orb">✨</span>
            <div>
              <div class="ai-title">{{ title }}</div>
              <div v-if="subtitle" class="ai-sub">{{ subtitle }}</div>
            </div>
          </div>
          <button class="ai-x" @click="emit('close')">×</button>
        </div>

        <div class="ai-body">
          <!-- Loading -->
          <div v-if="loading" class="ai-loading">
            <div class="ai-scanner">
              <div class="ai-scan-line"></div>
            </div>
            <div class="ai-loading-text">DeepSeek 正在分析财务数据…</div>
            <div class="ai-dots"><span></span><span></span><span></span></div>
          </div>

          <!-- Error -->
          <div v-else-if="error" class="ai-err">
            <div style="font-size:26px;margin-bottom:8px">⚠️</div>
            {{ error }}
          </div>

          <!-- Result -->
          <div v-else-if="text" class="ai-content">
            <p v-for="(p, i) in paragraphs" :key="i" v-html="p"></p>
          </div>
        </div>

        <div class="ai-foot">
          <button class="btn btn-ghost btn-sm" :disabled="loading" @click="emit('reanalyze')">
            <span>↻</span> 重新分析
          </button>
          <button class="btn btn-primary btn-sm" @click="emit('close')">确认</button>
        </div>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.ai-mask {
  position: fixed; inset: 0; z-index: 1000;
  display: flex; align-items: center; justify-content: center;
  padding: 20px;
  background: rgba(30, 18, 10, 0.45);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
}

.ai-modal {
  position: relative;
  width: min(580px, 96vw);
  max-height: 86vh;
  display: flex; flex-direction: column;
  border-radius: 20px;
  background: linear-gradient(165deg, rgba(255,252,248,0.97), rgba(252,244,236,0.97));
  box-shadow: 0 30px 90px rgba(80, 40, 20, 0.32);
  overflow: hidden;
}

/* Rotating gradient glow ring behind modal edge */
.ai-glow {
  position: absolute; inset: -2px;
  border-radius: 22px;
  padding: 2px;
  background: linear-gradient(120deg, #c96342, #e8a05a, #7a9fd4, #c96342);
  background-size: 300% 300%;
  -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  -webkit-mask-composite: xor;
  mask-composite: exclude;
  animation: aiGlowShift 6s ease infinite;
  pointer-events: none;
}
@keyframes aiGlowShift {
  0% { background-position: 0% 50%; }
  50% { background-position: 100% 50%; }
  100% { background-position: 0% 50%; }
}

.ai-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 18px 22px 14px;
  border-bottom: 1px solid rgba(201,99,66,0.12);
}
.ai-title-wrap { display: flex; align-items: center; gap: 12px; }
.ai-orb {
  font-size: 22px;
  filter: drop-shadow(0 0 6px rgba(201,99,66,0.5));
  animation: aiOrb 3s ease-in-out infinite;
}
@keyframes aiOrb {
  0%, 100% { transform: scale(1) rotate(0deg); }
  50% { transform: scale(1.15) rotate(8deg); }
}
.ai-title { font-size: 16px; font-weight: 800; color: var(--text); letter-spacing: 0.02em; }
.ai-sub { font-size: 12px; color: var(--muted); margin-top: 2px; }
.ai-x {
  background: none; border: none; font-size: 24px; line-height: 1;
  color: var(--muted); cursor: pointer; padding: 0 4px;
}

.ai-body {
  flex: 1; overflow-y: auto;
  padding: 18px 22px;
  min-height: 160px;
}

/* Loading scanner */
.ai-loading {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 16px; padding: 40px 0;
}
.ai-scanner {
  width: 120px; height: 64px; border-radius: 12px;
  background: linear-gradient(180deg, rgba(201,99,66,0.06), rgba(122,159,212,0.06));
  border: 1px solid rgba(201,99,66,0.15);
  position: relative; overflow: hidden;
}
.ai-scan-line {
  position: absolute; left: 0; right: 0; height: 30%;
  background: linear-gradient(180deg, transparent, rgba(201,99,66,0.35), transparent);
  animation: aiScan 1.4s ease-in-out infinite;
}
@keyframes aiScan {
  0% { top: -30%; }
  100% { top: 100%; }
}
.ai-loading-text { font-size: 13px; color: var(--muted); }
.ai-dots { display: flex; gap: 6px; }
.ai-dots span {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--primary); opacity: 0.4;
  animation: aiDot 1.2s ease-in-out infinite;
}
.ai-dots span:nth-child(2) { animation-delay: 0.2s; }
.ai-dots span:nth-child(3) { animation-delay: 0.4s; }
@keyframes aiDot {
  0%, 100% { opacity: 0.3; transform: translateY(0); }
  50% { opacity: 1; transform: translateY(-4px); }
}

.ai-err { text-align: center; color: var(--danger); font-size: 13px; padding: 30px 10px; }

.ai-content { font-size: 13.5px; line-height: 1.85; color: var(--text); }
.ai-content p { margin: 0 0 10px; }
.ai-content p:last-child { margin-bottom: 0; }
.ai-content :deep(strong) { color: var(--primary); font-weight: 700; }

.ai-foot {
  display: flex; justify-content: flex-end; gap: 10px;
  padding: 14px 22px;
  border-top: 1px solid rgba(201,99,66,0.12);
}

/* transition */
.ai-fade-enter-active, .ai-fade-leave-active { transition: opacity 0.22s ease; }
.ai-fade-enter-from, .ai-fade-leave-to { opacity: 0; }
.ai-fade-enter-active .ai-modal { transition: transform 0.26s cubic-bezier(0.2,0.8,0.3,1); }
.ai-fade-enter-from .ai-modal { transform: scale(0.92) translateY(12px); }
</style>
