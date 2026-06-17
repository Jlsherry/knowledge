<script setup>
import { formatRelativeTime } from '../utils/format'

defineProps({
  session: { type: Object, required: true },
  active: { type: Boolean, default: false },
})

const emit = defineEmits(['select', 'delete'])
</script>

<template>
  <div
    class="group flex items-start gap-3 p-3 mb-2 rounded-xl transition-all cursor-default"
    :class="
      active
        ? 'bg-gold/15 border border-gold/30'
        : 'bg-white/5 hover:bg-white/8 border border-transparent hover:border-white/10'
    "
  >
    <button
      class="flex items-start gap-3 flex-1 min-w-0 text-left"
      @click="emit('select', session)"
    >
      <div
        class="w-9 h-9 rounded-lg flex items-center justify-center shrink-0 text-sm"
        :class="active ? 'bg-gold/20 text-gold' : 'bg-white/10 text-white/50'"
      >
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            stroke-width="2"
            d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
          />
        </svg>
      </div>
      <div class="flex-1 min-w-0">
        <div
          class="text-sm truncate"
          :class="active ? 'text-gold' : 'text-white/90'"
          :title="session.title"
        >
          {{ session.title || '新对话' }}
        </div>
        <div class="text-[11px] text-white/40 mt-1">
          {{ formatRelativeTime(session.updated_at) }}
        </div>
      </div>
    </button>

    <!-- 删除 -->
    <button
      class="opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-red-500/20 text-white/40 hover:text-red-400 transition-all shrink-0"
      title="删除对话"
      @click.stop="emit('delete', session)"
    >
      <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path
          stroke-linecap="round"
          stroke-linejoin="round"
          stroke-width="2"
          d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
        />
      </svg>
    </button>
  </div>
</template>
