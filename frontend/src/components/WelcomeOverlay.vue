<script setup>
import { ref, onMounted, computed } from 'vue'

const props = defineProps({
  user: { type: Object, default: null },
})
const emit = defineEmits(['done'])

const visible = ref(true)
const progress = ref(0)

const hour = new Date().getHours()
const greeting = hour < 6 ? '夜深了' : hour < 12 ? '早上好' : hour < 18 ? '下午好' : '晚上好'
const greetIcon = hour < 6 ? '🌙' : hour < 12 ? '🌅' : hour < 18 ? '☀️' : '🌆'

const today = new Date().toLocaleDateString('zh-CN', {
  year: 'numeric', month: 'long', day: 'numeric', weekday: 'long',
})

const ROLE_LABELS = {
  super_admin: '超级管理员',
  manager: '财务经理',
  operator: '操作员',
  viewer: '查看员',
}

const motivations = [
  '每一笔排款，都是信任的证明。',
  '资金管理，精准高效。',
  '今日事今日毕，付款不逾期。',
  '严谨细致，把控每一分资金。',
]
const motto = motivations[new Date().getDay() % motivations.length]

function dismiss() {
  visible.value = false
  setTimeout(() => emit('done'), 400)
}

onMounted(() => {
  const duration = 4000
  const interval = 40
  const steps = duration / interval
  let step = 0
  const timer = setInterval(() => {
    step++
    progress.value = Math.min(100, (step / steps) * 100)
    if (step >= steps) {
      clearInterval(timer)
      dismiss()
    }
  }, interval)
})
</script>

<template>
  <Transition name="welcome-fade">
    <div v-if="visible" class="welcome-overlay" @click="dismiss">
      <div class="welcome-card" @click.stop>
        <!-- background particles -->
        <div class="particle p1"></div>
        <div class="particle p2"></div>
        <div class="particle p3"></div>
        <div class="particle p4"></div>

        <!-- celebratory confetti burst -->
        <div class="wc-confetti">
          <i v-for="n in 18" :key="n" :style="`--i:${n}`"></i>
        </div>

        <div class="welcome-icon">{{ greetIcon }}</div>

        <div class="welcome-greeting">{{ greeting }}</div>
        <div class="welcome-name">{{ user?.name || '欢迎' }}</div>

        <div class="welcome-role">
          <span class="role-badge">{{ ROLE_LABELS[user?.role] || '' }}</span>
          <span v-if="user?.job_title_label" class="job-badge">{{ user.job_title_label }}</span>
        </div>

        <div class="welcome-date">{{ today }}</div>
        <div class="welcome-motto">{{ motto }}</div>

        <div class="progress-bar">
          <div class="progress-fill" :style="`width:${progress}%`"></div>
        </div>
        <div class="welcome-hint">点击任意处进入系统</div>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.welcome-overlay {
  position: fixed; inset: 0; z-index: 1000;
  display: flex; align-items: center; justify-content: center;
  background: rgba(20, 10, 5, 0.55);
  backdrop-filter: blur(12px);
}

.welcome-card {
  position: relative;
  width: 420px; max-width: 92vw;
  background: rgba(255, 252, 248, 0.78);
  backdrop-filter: blur(32px) saturate(200%);
  -webkit-backdrop-filter: blur(32px) saturate(200%);
  border: 1px solid rgba(255, 255, 255, 0.65);
  border-radius: 28px;
  padding: 48px 40px 36px;
  text-align: center;
  box-shadow:
    0 32px 80px rgba(100, 60, 30, 0.28),
    0 1px 0 rgba(255,255,255,0.9) inset;
  animation: cardIn 0.55s cubic-bezier(0.34, 1.6, 0.64, 1) both;
  overflow: hidden;
}

/* floating particles behind content */
.particle {
  position: absolute; border-radius: 50%;
  opacity: 0.18; pointer-events: none;
}
.p1 { width:120px; height:120px; background:radial-gradient(circle,#c96342,transparent); top:-30px; left:-30px; animation:pfloat 6s ease-in-out infinite; }
.p2 { width:80px; height:80px; background:radial-gradient(circle,#e8a84a,transparent); bottom:-20px; right:-20px; animation:pfloat 8s ease-in-out infinite reverse; }
.p3 { width:60px; height:60px; background:radial-gradient(circle,#c96342,transparent); bottom:60px; left:20px; animation:pfloat 7s ease-in-out infinite; opacity:0.12; }
.p4 { width:50px; height:50px; background:radial-gradient(circle,#d4946a,transparent); top:60px; right:20px; animation:pfloat 5s ease-in-out infinite reverse; opacity:0.14; }

@keyframes pfloat {
  0%,100% { transform:translate(0,0) scale(1); }
  50%      { transform:translate(10px,-15px) scale(1.1); }
}

/* confetti burst from the top of the card */
.wc-confetti { position: absolute; top: 0; left: 0; right: 0; height: 0; pointer-events: none; }
.wc-confetti i {
  position: absolute; top: 40px; left: 50%;
  width: 9px; height: 15px; border-radius: 2px;
  background: hsl(calc(var(--i) * 40), 85%, 62%);
  opacity: 0;
  animation: wcConfetti 1.8s calc(var(--i) * 0.05s) cubic-bezier(0.2,0.7,0.3,1) both;
}
@keyframes wcConfetti {
  0%   { opacity: 0; transform: translate(0,0) rotate(0deg) scale(0.5); }
  12%  { opacity: 1; }
  100% {
    opacity: 0;
    transform:
      translate(calc((var(--i) - 9) * 24px), calc(180px + var(--i) * 5px))
      rotate(calc(var(--i) * 110deg)) scale(1);
  }
}

.welcome-icon {
  font-size: 62px; margin-bottom: 16px;
  animation: spinIn 0.6s cubic-bezier(0.34,1.56,0.64,1) 0.1s both,
             iconFloat 3s ease-in-out 0.8s infinite;
  display: block;
  filter: drop-shadow(0 6px 16px rgba(201,99,66,0.35));
}
@keyframes iconFloat { 0%,100% { transform: translateY(0); } 50% { transform: translateY(-7px); } }

.welcome-greeting {
  font-size: 16px; color: #9b8070; font-weight: 500;
  margin-bottom: 4px; letter-spacing: 0.06em;
  animation: slideUp 0.45s 0.2s both;
}

.welcome-name {
  font-size: 36px; font-weight: 800; color: #1a1208;
  letter-spacing: -0.02em; line-height: 1.1;
  background: linear-gradient(135deg, #c96342, #1a1208 60%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  margin-bottom: 16px;
  animation: slideUp 0.45s 0.25s both;
}

.welcome-role {
  display: flex; gap: 8px; justify-content: center;
  margin-bottom: 20px;
  animation: slideUp 0.45s 0.3s both;
}
.role-badge, .job-badge {
  display: inline-block; padding: 4px 14px;
  border-radius: 20px; font-size: 12px; font-weight: 600;
  letter-spacing: 0.04em;
}
.role-badge { background: rgba(201,99,66,0.12); color: #c96342; }
.job-badge  { background: rgba(21,101,192,0.1); color: #1565c0; }

.welcome-date {
  font-size: 13px; color: #9b8070; margin-bottom: 10px;
  animation: slideUp 0.45s 0.35s both;
}
.welcome-motto {
  font-size: 13px; color: #b09080; font-style: italic;
  margin-bottom: 28px;
  animation: slideUp 0.45s 0.4s both;
}

.progress-bar {
  width: 100%; height: 3px;
  background: rgba(180,140,110,0.18);
  border-radius: 2px; overflow: hidden;
  margin-bottom: 12px;
}
.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #c96342, #e8855a);
  border-radius: 2px;
  transition: width 0.04s linear;
  box-shadow: 0 0 8px rgba(201,99,66,0.4);
}

.welcome-hint {
  font-size: 11px; color: rgba(155,128,112,0.6);
  letter-spacing: 0.04em;
}

/* transitions */
.welcome-fade-enter-active { animation: fadeIn 0.25s ease; }
.welcome-fade-leave-active { animation: fadeOut 0.35s ease forwards; }

@keyframes fadeIn  { from { opacity:0; } to { opacity:1; } }
@keyframes fadeOut { from { opacity:1; } to { opacity:0; } }
@keyframes cardIn {
  from { opacity:0; transform: scale(0.88) translateY(24px); }
  to   { opacity:1; transform: scale(1) translateY(0); }
}
@keyframes slideUp {
  from { opacity:0; transform:translateY(14px); }
  to   { opacity:1; transform:translateY(0); }
}
@keyframes spinIn {
  from { transform:rotate(-180deg) scale(0.3); opacity:0; }
  to   { transform:rotate(0) scale(1); opacity:1; }
}
</style>
