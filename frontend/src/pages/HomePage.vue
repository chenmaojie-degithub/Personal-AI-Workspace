<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { ArrowDownRight, ArrowRight, ArrowUpRight, X } from 'lucide-vue-next'
import WebGLGallery from '@/components/home/WebGLGallery.vue'
import type { GalleryItem } from '@/components/home/WebGLGallery.vue'
import galleryItems from '@/data/gallery.json'

const router = useRouter()
const gallery = ref<HTMLElement | null>(null)
const selected = ref<GalleryItem | null>(null)
const showGuide = ref(false)
const leaving = ref(false)
let transitionTimer: number | undefined

function enterWorkspace() {
  if (leaving.value) return
  leaving.value = true
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  transitionTimer = window.setTimeout(() => { void router.push('/chat') }, reduced ? 0 : 780)
}

function explore() {
  showGuide.value = true
  gallery.value?.scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'center' })
}

onBeforeUnmount(() => window.clearTimeout(transitionTimer))
</script>

<template>
  <div class="home-shell" :class="{ leaving }">
    <div class="ambient ambient-one" aria-hidden="true" />
    <div class="ambient ambient-two" aria-hidden="true" />
    <div class="home-grid" aria-hidden="true" />

    <header class="home-nav">
      <RouterLink to="/" class="brand" aria-label="Personal AI Workspace home">
        <span class="brand-symbol">✳</span>
        <span>PERSONAL <span class="brand-soft">/ AI</span></span>
      </RouterLink>
      <nav aria-label="Primary navigation">
        <RouterLink to="/chat">Chat</RouterLink>
        <RouterLink to="/chat">Workspace</RouterLink>
        <RouterLink to="/files">Knowledge</RouterLink>
        <span class="nav-soon" title="Usage page coming later">Usage <small>soon</small></span>
      </nav>
      <button class="nav-enter" type="button" @click="enterWorkspace">Open app <ArrowUpRight :size="15" /></button>
    </header>

    <main class="home-main">
      <section class="hero-copy" aria-labelledby="hero-title">
        <div class="eyebrow"><span class="status-light" /> A MORE INTELLIGENT SPACE <span class="eyebrow-line" /></div>
        <h1 id="hero-title"><span class="reveal-one">Personal</span><span class="reveal-two">AI Workspace<span class="period">.</span></span></h1>
        <p class="hero-subtitle">Your models. Your knowledge. Your tools.<br /><span>One intelligent workspace.</span></p>
        <div class="hero-actions">
          <button type="button" class="primary-action" @click="enterWorkspace">Enter Workspace <ArrowUpRight :size="18" /></button>
          <button type="button" class="secondary-action" @click="explore">Explore gallery <ArrowDownRight :size="17" /></button>
        </div>
        <div class="hero-aside"><span>01 <i>/</i> 03</span><span class="aside-rule" /><span>MODELS <b>·</b> KNOWLEDGE <b>·</b> TOOLS</span></div>
      </section>

      <section ref="gallery" class="hero-gallery" aria-label="Interactive gallery of your images">
        <div class="gallery-aura" aria-hidden="true" />
        <WebGLGallery :exiting="leaving" @select="(item) => { selected = item; showGuide = false }" />
        <div class="gallery-count">{{ galleryItems.length.toString().padStart(2, '0') }} ORIGINAL FRAMES <span>—</span> ONE SPATIAL VIEW</div>
      </section>
    </main>

    <footer class="home-footer">
      <span>PERSONAL AI WORKSPACE <span class="footer-muted">© 2026</span></span>
      <span class="footer-center">A DIFFERENT WAY TO THINK WITH AI</span>
      <span>SCROLL TO EXPLORE <ArrowRight :size="13" /></span>
    </footer>

    <Transition name="detail">
      <aside v-if="selected || showGuide" class="detail-panel" aria-label="Gallery detail">
        <button class="detail-close" type="button" aria-label="Close detail" @click="selected = null; showGuide = false"><X :size="17" /></button>
        <template v-if="selected">
          <img :src="selected.image" :alt="selected.title" />
          <div class="detail-overline">FROM YOUR GALLERY / {{ selected.id }}</div>
          <h2>{{ selected.title }}</h2>
          <p>One of {{ galleryItems.length }} images in your local collection.</p>
        </template>
        <template v-else>
          <div class="detail-overline">HOW TO EXPLORE</div>
          <h2>Your gallery, in motion.</h2>
          <p>Scroll to orbit, move the pointer to shift perspective, and select an image to focus.</p>
        </template>
        <button class="detail-link" type="button" @click="enterWorkspace">Enter Workspace <ArrowUpRight :size="15" /></button>
      </aside>
    </Transition>
  </div>
</template>

<style scoped>
.home-shell { position: relative; min-height: 100svh; overflow: hidden; display: flex; flex-direction: column; color: #f2f3f6; background: #08090b; isolation: isolate; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
.ambient { position: absolute; pointer-events: none; z-index: -1; filter: blur(60px); }
.ambient-one { width: 57vw; height: 58vw; right: -17vw; top: -17vw; background: radial-gradient(circle, #39487245, transparent 66%); }
.ambient-two { width: 45vw; height: 28vw; left: -17vw; bottom: -18vw; background: radial-gradient(circle, #2c365a23, transparent 72%); }
.home-grid { position: absolute; inset: 0; z-index: -1; opacity: .18; background-image: linear-gradient(#b7c3ea0b 1px, transparent 1px), linear-gradient(90deg, #b7c3ea0b 1px, transparent 1px); background-size: 72px 72px; mask-image: linear-gradient(to bottom, transparent 2%, #000 46%, transparent 100%); }
.home-nav { height: 90px; width: min(100% - 112px, 1500px); margin: 0 auto; display: flex; align-items: center; justify-content: space-between; gap: 32px; z-index: 4; flex-shrink: 0; }
.brand { display: inline-flex; align-items: center; gap: 12px; font-size: 12px; font-weight: 700; letter-spacing: .21em; white-space: nowrap; }
.brand-symbol { display: inline-grid; place-items: center; width: 32px; height: 32px; border: 1px solid #ffffff4a; border-radius: 9px; font-size: 20px; font-weight: 400; letter-spacing: 0; }
.brand-soft { color: #9299a7; font-weight: 500; }
.home-nav nav { display: flex; gap: clamp(18px, 3vw, 44px); align-items: center; color: #a5aab6; font-size: 12px; }
.home-nav nav a, .nav-soon { transition: color .25s; white-space: nowrap; }
.home-nav nav a:hover { color: white; }
.nav-soon { color: #717783; cursor: default; }
.nav-soon small { margin-left: 2px; font-size: 9px; opacity: .55; }
.nav-enter { display: inline-flex; align-items: center; gap: 10px; white-space: nowrap; color: #e8eaf0; font-size: 12px; border-bottom: 1px solid #9ca7bb70; padding-bottom: 7px; transition: border-color .2s, color .2s; cursor: pointer; }
.nav-enter:hover { border-color: #fff; color: #fff; }
.home-main { width: min(100% - 112px, 1500px); margin: 0 auto; flex: 1; min-height: 690px; display: grid; grid-template-columns: minmax(400px, 46%) minmax(0, 54%); align-items: center; }
.hero-copy { position: relative; z-index: 2; margin-top: -30px; transition: opacity .75s, filter .75s, transform .75s; }
.eyebrow { display: flex; align-items: center; gap: 12px; color: #a8b1c3; font-size: 10px; letter-spacing: .24em; font-weight: 600; margin-bottom: 34px; white-space: nowrap; }
.status-light { width: 6px; height: 6px; border-radius: 50%; background: #9cb5e2; box-shadow: 0 0 15px #adc5fa; }
.eyebrow-line { width: 36px; height: 1px; background: #a6b5d465; }
h1 { display: flex; flex-direction: column; margin: 0; font-size: clamp(55px, 6.1vw, 108px); line-height: .98; letter-spacing: -.075em; font-weight: 500; white-space: nowrap; }
h1 span { display: block; }
.reveal-one, .reveal-two { opacity: 0; animation: reveal .9s cubic-bezier(.2,.75,.22,1) forwards; }
.reveal-two { animation-delay: .14s; }
.period { display: inline; color: #9eb8e7; }
@keyframes reveal { from { opacity: 0; filter: blur(12px); transform: translateY(20px); } to { opacity: 1; filter: blur(0); transform: translateY(0); } }
.hero-subtitle { margin: 38px 0 0; color: #a4a9b4; font-size: clamp(15px, 1.28vw, 19px); font-weight: 350; line-height: 1.7; letter-spacing: -.015em; }
.hero-subtitle span { color: #dde0e8; }
.hero-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 14px; margin-top: 40px; }
.hero-actions button { display: inline-flex; align-items: center; justify-content: center; gap: 28px; height: 52px; border-radius: 8px; padding: 0 20px; font-size: 12px; font-weight: 600; letter-spacing: .02em; cursor: pointer; transition: transform .22s, background .22s, border-color .22s; }
.hero-actions button:hover { transform: translateY(-2px); }
.primary-action { background: #e8eaf0; color: #0e1118; }
.primary-action:hover { background: white; }
.secondary-action { border: 1px solid #ffffff30; color: #d3d6e0; background: #ffffff08; backdrop-filter: blur(10px); }
.secondary-action:hover { border-color: #ffffff70; }
.hero-aside { display: flex; align-items: center; gap: 15px; margin-top: 92px; color: #89909e; font-size: 10px; font-weight: 600; letter-spacing: .18em; white-space: nowrap; }
.hero-aside i, .hero-aside b { color: #555e70; font-style: normal; font-weight: 400; }
.aside-rule { width: 52px; height: 1px; background: #7e889c55; }
.hero-gallery { position: relative; height: min(75vh, 790px); min-height: 600px; margin-left: -5%; }
.gallery-aura { position: absolute; inset: 13%; border-radius: 50%; background: radial-gradient(circle, #a6b9e016, #6e85bb0a 36%, transparent 68%); filter: blur(30px); pointer-events: none; }
.gallery-count { position: absolute; right: 4%; top: 9%; color: #8e95a4; font-size: 9px; font-weight: 600; letter-spacing: .19em; pointer-events: none; }
.gallery-count span { padding: 0 7px; color: #566072; }
.home-footer { display: flex; justify-content: space-between; align-items: center; width: min(100% - 112px, 1500px); margin: 0 auto; height: 70px; flex-shrink: 0; border-top: 1px solid #ffffff16; color: #a0a5b0; font-size: 9px; font-weight: 600; letter-spacing: .16em; }
.footer-muted { color: #616978; font-weight: 400; margin-left: 10px; }
.footer-center { color: #616978; }
.home-footer > span:last-child { display: flex; align-items: center; gap: 10px; }
.leaving .hero-copy, .leaving .home-nav, .leaving .home-footer { opacity: 0; filter: blur(12px); transform: translateY(-9px); }
.detail-panel { position: fixed; z-index: 7; right: 6vw; bottom: 8vh; width: min(340px, calc(100vw - 30px)); padding: 18px; border: 1px solid #ffffff29; border-radius: 17px; background: #11151bdf; backdrop-filter: blur(24px); box-shadow: 0 30px 90px #0009; }
.detail-panel img { width: 100%; height: 142px; object-fit: cover; border-radius: 9px; margin-bottom: 18px; }
.detail-overline { color: #8e9bb6; font-size: 9px; letter-spacing: .2em; margin-bottom: 10px; }
.detail-panel h2 { font-size: 20px; font-weight: 500; margin: 0 20px 7px 0; line-height: 1.3; }
.detail-panel p { color: #a5a9b4; font-size: 12px; line-height: 1.5; }
.detail-close { position: absolute; right: 14px; top: 12px; cursor: pointer; color: #a9afbb; }
.detail-link { display: flex; align-items: center; justify-content: space-between; width: 100%; margin-top: 20px; border-top: 1px solid #ffffff23; padding-top: 14px; font-size: 11px; color: #e2e5ed; cursor: pointer; }
.detail-enter-active, .detail-leave-active { transition: opacity .25s, transform .25s; }
.detail-enter-from, .detail-leave-to { opacity: 0; transform: translateY(12px); }
@media (max-width: 1100px) { .home-main { grid-template-columns: 48% 52%; } h1 { font-size: clamp(52px, 6vw, 80px); } .hero-gallery { margin-left: -10%; } }
@media (max-width: 800px) { .home-nav, .home-main, .home-footer { width: min(100% - 40px, 680px); } .home-nav { height: 72px; } .home-nav nav { display: none; } .home-main { display: flex; flex-direction: column; min-height: 0; align-items: stretch; } .hero-copy { margin-top: 56px; } h1 { font-size: clamp(49px, 10vw, 74px); } .hero-subtitle { margin-top: 28px; } .hero-aside { margin-top: 48px; } .hero-gallery { height: 470px; min-height: 470px; margin: -2px -30px 0; } .gallery-count { top: 9%; right: 9%; } .footer-center { display: none; } }
@media (max-width: 520px) { .brand { font-size: 10px; } .nav-enter { display: none; } .hero-copy { margin-top: 38px; } h1 { font-size: clamp(45px, 11vw, 61px); } .hero-subtitle { font-size: 14px; } .hero-actions button { height: 46px; gap: 12px; padding: 0 14px; } .hero-aside { gap: 10px; font-size: 8px; letter-spacing: .13em; } .aside-rule { width: 20px; } .hero-gallery { height: 395px; min-height: 395px; margin: 5px -20px 0; } .home-footer { height: 56px; font-size: 8px; } .home-footer > span:last-child { display: none; } .detail-panel { right: 15px; bottom: 16px; } }
@media (prefers-reduced-motion: reduce) { .reveal-one, .reveal-two { animation-duration: .01ms; animation-delay: 0ms; } .home-shell * { scroll-behavior: auto !important; } .hero-copy, .home-nav, .home-footer, .detail-panel { transition-duration: .01ms !important; } }
</style>
