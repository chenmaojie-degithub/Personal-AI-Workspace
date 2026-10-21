<script setup lang="ts">
import { computed, ref } from 'vue'
import { Check, ChevronDown } from 'lucide-vue-next'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import type { AvailableModel } from '@/lib/chat'

const props = defineProps<{
  modelValue: string | null
  models: AvailableModel[]
  disabled?: boolean
}>()
const emit = defineEmits<{ 'update:modelValue': [modelId: string] }>()
const open = ref(false)
const selected = computed(() => props.models.find((model) => model.model_id === props.modelValue))

function label(model: AvailableModel) {
  return model.model_id === 'openrouter/free' ? 'OpenRouter Free (experimental)'
    : model.provider === 'openrouter' ? `OpenRouter · ${model.model}`
    : model.provider === 'deepseek' ? 'DeepSeek' : model.model
}

function choose(modelId: string) {
  emit('update:modelValue', modelId)
  open.value = false
}
</script>

<template>
  <Popover v-model:open="open">
    <PopoverTrigger as-child>
      <button type="button" aria-label="Chat model" :disabled="disabled || !models.length"
        class="model-trigger inline-flex h-9 min-w-38 max-w-48 items-center justify-between gap-3 rounded-lg border border-white/10 bg-white/[0.045] px-3 text-sm text-[#e8eaf0] shadow-sm shadow-black/10 transition-colors duration-200 hover:border-white/20 hover:bg-white/[0.075] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/25 disabled:cursor-not-allowed disabled:opacity-50">
        <Transition name="model-name" mode="out-in">
          <span :key="selected?.model_id ?? 'loading'" class="block min-w-0 truncate text-left">
            {{ selected ? label(selected) : 'Loading models…' }}
          </span>
        </Transition>
        <ChevronDown class="size-4 shrink-0 text-white/55 transition-transform duration-200 ease-in-out" :class="open && 'rotate-180'" />
      </button>
    </PopoverTrigger>
    <PopoverContent side="top" align="start" :side-offset="8" class="model-menu z-50 w-54 rounded-xl p-1.5">
      <div class="px-2 pb-1 pt-1 text-[10px] font-medium uppercase tracking-[0.16em] text-white/40">Choose model</div>
      <button v-for="model in models" :key="model.model_id" type="button"
        class="model-option flex w-full items-center justify-between gap-3 rounded-lg px-2.5 py-2 text-left text-[13px] text-white/65 transition-[background-color,color,transform] duration-200 hover:bg-white/[0.075] hover:text-white focus-visible:bg-white/[0.075] focus-visible:text-white focus-visible:outline-none"
        :aria-pressed="model.model_id === modelValue" @click="choose(model.model_id)">
        <span class="truncate">{{ label(model) }}</span>
        <Check v-if="model.model_id === modelValue" class="size-3.5 shrink-0 text-[#c3d7ff]" />
      </button>
    </PopoverContent>
  </Popover>
</template>

<style>
.model-menu {
  border: 1px solid rgba(255, 255, 255, .09);
  background: rgba(16, 18, 22, .92);
  box-shadow: 0 12px 40px rgba(0, 0, 0, .36);
  backdrop-filter: blur(18px);
  color: #e8eaf0;
}
.model-menu[data-state="open"] { animation: model-open 220ms cubic-bezier(.22, .8, .25, 1) both !important; }
.model-menu[data-state="closed"] { animation: model-close 180ms cubic-bezier(.4, 0, .8, .2) both !important; }
.model-option:hover { transform: translateX(2px); }
.model-name-enter-active, .model-name-leave-active { transition: opacity 90ms ease, transform 90ms ease, filter 90ms ease; }
.model-name-enter-from { opacity: 0; transform: translateY(4px); filter: blur(3px); }
.model-name-leave-to { opacity: 0; transform: translateY(-4px); filter: blur(3px); }
@keyframes model-open {
  from { opacity: 0; transform: translateY(-6px) scale(.98); filter: blur(4px); }
  to { opacity: 1; transform: translateY(0) scale(1); filter: blur(0); }
}
@keyframes model-close {
  from { opacity: 1; transform: translateY(0) scale(1); filter: blur(0); }
  to { opacity: 0; transform: translateY(-6px) scale(.98); filter: blur(4px); }
}
@media (prefers-reduced-motion: reduce) {
  .model-menu[data-state], .model-name-enter-active, .model-name-leave-active { animation-duration: 1ms !important; transition-duration: 1ms; }
  .model-option:hover { transform: none; }
}
</style>
