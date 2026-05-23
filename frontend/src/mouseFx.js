// Global cursor glow that trails the pointer + a ripple burst on every click.
// Warm terracotta theme to match the rest of the app. No-ops on touch devices
// or when the user prefers reduced motion.
export function initMouseFx() {
  if (typeof window === 'undefined' || !document?.body) return
  const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  const coarse = window.matchMedia?.('(pointer: coarse)').matches
  if (reduce || coarse) return

  const glow = document.createElement('div')
  glow.className = 'mfx-glow'
  document.body.appendChild(glow)

  let mx = innerWidth / 2, my = innerHeight / 2
  let gx = mx, gy = my
  let shown = false

  addEventListener('mousemove', e => {
    mx = e.clientX; my = e.clientY
    if (!shown) { shown = true; glow.classList.add('on') }
  }, { passive: true })

  addEventListener('mouseout', e => {
    if (!e.relatedTarget) { shown = false; glow.classList.remove('on') }
  })

  // Grow the glow slightly while pressed for tactile feedback.
  addEventListener('mousedown', () => glow.classList.add('press'))
  addEventListener('mouseup', () => glow.classList.remove('press'))

  ;(function tick() {
    gx += (mx - gx) * 0.18
    gy += (my - gy) * 0.18
    glow.style.transform = `translate(${gx}px, ${gy}px)`
    requestAnimationFrame(tick)
  })()

  addEventListener('mousedown', e => {
    const r = document.createElement('div')
    r.className = 'mfx-ripple'
    r.style.left = e.clientX + 'px'
    r.style.top = e.clientY + 'px'
    document.body.appendChild(r)
    r.addEventListener('animationend', () => r.remove())
  })
}
