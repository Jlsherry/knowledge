<script setup>
import { formatFileSize, formatRelativeTime, fileTypeColor, statusLabel } from '../utils/format'

defineProps({
  doc: { type: Object, required: true },
})

const emit = defineEmits(['delete', 'rebuild'])
</script>

<template>
  <div
    class="group flex items-start gap-3 p-3 mb-2 rounded-xl bg-white/5 hover:bg-white/8 border border-transparent hover:border-white/10 transition-all cursor-default"
  >
    <!-- 文件图标 -->
    <div
      class="w-9 h-9 rounded-lg flex items-center justify-center shrink-0 text-xs font-bold uppercase"
      :style="{ background: fileTypeColor(doc.file_type) + '22', color: fileTypeColor(doc.file_type) }"
    >
      {{ doc.file_type }}
    </div>

    <div class="flex-1 min-w-0">
      <div class="text-sm text-white/90 truncate" :title="doc.filename">{{ doc.filename }}</div>
      <div class="flex items-center gap-2 mt-1 text-[11px] text-white/40">
        <span>{{ formatFileSize(doc.file_size) }}</span>
        <span>·</span>
        <span>{{ formatRelativeTime(doc.created_at) }}</span>
      </div>
      <div class="flex items-center gap-2 mt-1">
        <span
          class="text-[10px] px-1.5 py-0.5 rounded"
          :class="{
            'bg-green-500/20 text-green-400': doc.status === 'ready',
            'bg-yellow-500/20 text-yellow-400': doc.status === 'processing' || doc.status === 'pending',
            'bg-red-500/20 text-red-400': doc.status === 'failed',
          }"
        >
          {{ statusLabel(doc.status) }}
        </span>
        <span v-if="doc.chunk_count" class="text-[10px] text-white/30">{{ doc.chunk_count }} 片段</span>
      </div>
    </div>

    <div class="opacity-0 group-hover:opacity-100 flex items-center gap-1 shrink-0 transition-all">
      <button
        class="p-1 rounded hover:bg-gold/20 text-white/40 hover:text-gold transition-colors"
        title="重建文档向量"
        @click.stop="emit('rebuild', doc)"
      >
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            stroke-width="2"
            d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
          />
        </svg>
      </button>
      <button
        class="p-1 rounded hover:bg-red-500/20 text-white/40 hover:text-red-400 transition-colors"
        title="删除文档"
        @click.stop="emit('delete', doc)"
      >
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
        </svg>
      </button>
    </div>
  </div>
</template>
