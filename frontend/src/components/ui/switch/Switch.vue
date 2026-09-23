<script setup lang="ts">
import type { SwitchRootEmits, SwitchRootProps } from "reka-ui"
import type { HTMLAttributes } from "vue"
import type { Ref } from "vue"
import { reactiveOmit } from "@vueuse/core"
import { useVModel } from "@vueuse/core"
import {
  SwitchRoot,
  SwitchThumb,
  useForwardPropsEmits,
} from "reka-ui"
import { cn } from "@/lib/utils"

// reka-ui SwitchRoot uses `modelValue` + `update:modelValue`.
// Our app code prefers `checked` + `update:checked`, so we provide a small
// compatibility layer.
const props = withDefaults(
  defineProps<SwitchRootProps & {
    class?: HTMLAttributes["class"]
    checked?: boolean
    defaultChecked?: boolean
  }>(),
  {
    checked: undefined,
    defaultChecked: false,
  },
)

const emits = defineEmits<SwitchRootEmits & {
  "update:checked": [checked: boolean]
}>()

// This is the source-of-truth that we bind to `SwitchRoot`.
const modelValue = useVModel(props, "checked", emits, {
  defaultValue: props.defaultChecked ?? false,
  passive: (props.checked === undefined) as false,
}) as Ref<boolean>

function onUpdateModelValue(next: boolean) {
  modelValue.value = next
  emits("update:checked", next)
}

// Don't forward our compatibility props into reka-ui.
const delegatedProps = reactiveOmit(props, "class", "checked", "defaultChecked")
const forwarded = useForwardPropsEmits(delegatedProps, emits)
</script>

<template>
  <SwitchRoot v-slot="slotProps" data-slot="switch" v-bind="forwarded" :model-value="modelValue"
    @update:model-value="onUpdateModelValue" :class="cn(
      'peer data-[state=checked]:bg-primary data-[state=unchecked]:bg-input focus-visible:border-ring focus-visible:ring-ring/50 dark:data-[state=unchecked]:bg-input/80 inline-flex h-[1.15rem] w-8 shrink-0 items-center rounded-full border border-transparent shadow-xs transition-all outline-none focus-visible:ring-[3px] disabled:cursor-not-allowed disabled:opacity-50',
      props.class,
    )">
    <SwitchThumb data-slot="switch-thumb"
      :class="cn('bg-background dark:data-[state=unchecked]:bg-foreground dark:data-[state=checked]:bg-primary-foreground pointer-events-none block size-4 rounded-full ring-0 transition-transform data-[state=checked]:translate-x-[calc(100%-2px)] data-[state=unchecked]:translate-x-0')">
      <slot name="thumb" v-bind="slotProps" />
    </SwitchThumb>
  </SwitchRoot>
</template>
