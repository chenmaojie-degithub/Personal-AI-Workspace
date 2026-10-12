<script setup lang="ts">
import { nextTick, ref } from 'vue'
import { ArrowUp, Square } from 'lucide-vue-next'

const props = defineProps<{ disabled?: boolean; streaming?: boolean }>()
const emit = defineEmits<{ (e: 'send', text: string): void; (e: 'stop'): void }>()
const text = ref('')
const textarea = ref<HTMLTextAreaElement | null>(null)

function resize() {
  const el = textarea.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 200)}px`
}

function setText(value: string) {
  text.value = value
  void nextTick(() => { resize(); textarea.value?.focus() })
}

function onSend() {
  const trimmed = text.value.trim()
  if (!trimmed || props.disabled || props.streaming) return
  emit('send', trimmed)
  text.value = ''
  void nextTick(resize)
}

function onEnter(event: KeyboardEvent) {
  if (event.isComposing) return
  event.preventDefault()
  onSend()
}

defineExpose({ setText })
</script>

<template>
  <div class="rounded-[26px] border border-white/[0.08] bg-[#14161b]/95 shadow-[0_12px_40px_rgba(0,0,0,0.25)] backdrop-blur-xl transition-[background,border-color,box-shadow] duration-200 hover:bg-[#181c22] focus-within:border-white/[0.16] focus-within:shadow-[0_16px_44px_rgba(0,0,0,0.32)]">
    <slot name="attachments" />
    <textarea ref="textarea" v-model="text" rows="1" :disabled="disabled" placeholder="输入消息..."
      class="block min-h-20 max-h-[200px] w-full resize-none overflow-y-auto bg-transparent px-5 pb-2 pt-[18px] text-[15px] leading-[1.6] text-[#f3f4f6] outline-none placeholder:text-white/30 disabled:cursor-not-allowed disabled:opacity-60"
      aria-label="输入你的消息" @input="resize" @keydown.enter.exact="onEnter" />
    <div class="flex min-w-0 items-center gap-2 px-3 pb-3">
      <div class="flex min-w-0 items-center gap-1 text-xs text-white/45">
        <slot name="prepend" />
        <slot name="actions" />
      </div>
      <div class="flex min-w-0 flex-1 justify-center"><slot name="center" /></div>
      <div class="flex shrink-0 items-center gap-1">
        <slot name="before-send" />
      <button v-if="streaming" type="button" class="flex size-9 shrink-0 items-center justify-center rounded-xl bg-white text-[#111318] transition-colors hover:bg-white/85"
        aria-label="停止生成" title="停止生成" @click="emit('stop')">
        <Square class="size-3.5 fill-current" />
      </button>
      <button v-else type="button" class="flex size-9 shrink-0 items-center justify-center rounded-xl bg-white text-[#111318] transition-[opacity,transform,background] duration-150 hover:bg-white/85 active:scale-95 disabled:cursor-not-allowed disabled:opacity-25"
        :disabled="disabled || !text.trim()" aria-label="发送消息" title="发送消息" @click="onSend">
        <ArrowUp class="size-[18px]" />
      </button>
      </div>
    </div>
  </div>
</template>
