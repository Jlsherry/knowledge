<script setup>
import { ref, nextTick, watch } from 'vue'
import { simpleMarkdown, dedupeSources } from '../utils/format'

const props = defineProps({
  messages: { type: Array, default: () => [] },
  streaming: { type: Boolean, default: false },
})

const emit = defineEmits(['send', 'stop'])

const input = ref('')
const listRef = ref(null)
/** 每条消息引用来源区块是否展开，key 为消息下标 */
const expandedSources = ref({})
/** 每条消息内单个来源条目是否展开，key 为 `${msgIdx}-${srcIdx}` */
const expandedSourceItems = ref({})

function submit() {
  const text = input.value.trim()
  if (!text || props.streaming) return
  emit('send', text)
  input.value = ''
}

function onKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    submit()
  }
}

function stop() {
  if (props.streaming) emit('stop')
}

function getSources(msg) {
  return dedupeSources(msg.sources)
}

function toggleSourcesBlock(msgIdx) {
  expandedSources.value = {
    ...expandedSources.value,
    [msgIdx]: !expandedSources.value[msgIdx],
  }
}

function toggleSourceItem(msgIdx, srcIdx) {
  const key = `${msgIdx}-${srcIdx}`
  expandedSourceItems.value = {
    ...expandedSourceItems.value,
    [key]: !expandedSourceItems.value[key],
  }
}

function sourceItemKey(msgIdx, srcIdx) {
  return `${msgIdx}-${srcIdx}`
}

watch(
  () => props.messages.length,
  async () => {
    await nextTick()
    if (listRef.value) {
      listRef.value.scrollTop = listRef.value.scrollHeight
    }
  }
)
</script>

<template>
  <div class="flex flex-col h-full">
    <!-- 消息列表 -->
    <div ref="listRef" class="flex-1 overflow-y-auto custom-scroll-light px-6 py-6">
      <div v-if="messages.length === 0" class="flex items-center justify-center h-full text-gray-400 text-sm">
        开始提问，我将基于知识库为您解答
      </div>

      <div v-for="(msg, i) in messages" :key="i" class="mb-6">
        <!-- 用户消息 -->
        <div v-if="msg.role === 'user'" class="flex justify-end">
          <div class="max-w-[75%] px-4 py-3 bg-sidebar text-white rounded-2xl rounded-tr-sm text-sm leading-relaxed">
            {{ msg.content }}
          </div>
        </div>

        <!-- AI 回复 -->
        <div v-else class="flex gap-3">
          <div
            class="w-8 h-8 rounded-lg bg-sidebar flex items-center justify-center text-gold font-serif font-bold text-sm shrink-0"
          >
            问
          </div>
          <div class="flex-1 min-w-0">
            <div
              class="msg-content text-sm text-gray-700 leading-relaxed"
              v-html="simpleMarkdown(msg.content)"
            />
            <!-- 引用来源（默认折叠） -->
            <div v-if="getSources(msg).length" class="mt-3">
              <button
                type="button"
                class="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-700 transition-colors"
                @click="toggleSourcesBlock(i)"
              >
                <svg
                  class="w-3.5 h-3.5 transition-transform"
                  :class="expandedSources[i] ? 'rotate-90' : ''"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
                </svg>
                <span class="font-medium">引用来源</span>
                <span class="text-gray-400">({{ getSources(msg).length }})</span>
              </button>

              <div v-show="expandedSources[i]" class="mt-2 space-y-2">
                <div
                  v-for="(src, j) in getSources(msg)"
                  :key="sourceItemKey(i, j)"
                  class="bg-white/80 border border-gray-100 rounded-xl text-xs overflow-hidden"
                >
                  <button
                    type="button"
                    class="w-full flex items-center justify-between gap-2 px-3 py-2.5 text-left hover:bg-gray-50/80 transition-colors"
                    @click="toggleSourceItem(i, j)"
                  >
                    <div class="flex items-center gap-2 min-w-0 text-gray-600 font-medium">
                      <span class="shrink-0">📄</span>
                      <span class="truncate">{{ src.filename || '未知文档' }}</span>
                      <span v-if="src.page != null" class="shrink-0 text-gray-400 font-normal">
                        第 {{ src.page + 1 }} 页
                      </span>
                    </div>
                    <svg
                      class="w-3.5 h-3.5 shrink-0 text-gray-400 transition-transform"
                      :class="expandedSourceItems[sourceItemKey(i, j)] ? 'rotate-180' : ''"
                      fill="none"
                      stroke="currentColor"
                      viewBox="0 0 24 24"
                    >
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
                    </svg>
                  </button>
                  <div
                    v-show="expandedSourceItems[sourceItemKey(i, j)]"
                    class="px-3 pb-3 text-gray-500 leading-relaxed border-t border-gray-50"
                  >
                    {{ src.content }}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 流式输入中光标 -->
      <div v-if="streaming" class="flex gap-3 mb-4">
        <div class="w-8 h-8 rounded-lg bg-sidebar flex items-center justify-center text-gold font-serif font-bold text-sm shrink-0">
          问
        </div>
        <div class="flex items-center gap-1 text-gray-400 text-sm">
          <span class="animate-pulse">思考中</span>
          <span class="animate-bounce">.</span>
          <span class="animate-bounce" style="animation-delay: 0.1s">.</span>
          <span class="animate-bounce" style="animation-delay: 0.2s">.</span>
        </div>
      </div>
    </div>

    <!-- 输入框 -->
    <div class="px-6 pb-6 pt-2">
      <div class="flex items-end gap-3 bg-white rounded-2xl shadow-card border border-gray-100 px-4 py-3">
        <textarea
          v-model="input"
          rows="1"
          placeholder="输入您的问题，基于知识库智能回答..."
          class="flex-1 resize-none bg-transparent text-sm text-gray-700 placeholder-gray-400 focus:outline-none max-h-32"
          :disabled="streaming"
          @keydown="onKeydown"
        />
        <button
          v-if="streaming"
          class="shrink-0 w-9 h-9 rounded-xl flex items-center justify-center transition-colors"
          :class="'bg-red-100 text-red-500 hover:bg-red-200'"
          title="停止生成"
          @click="stop"
        >
          <svg class="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 24 24">
            <path d="M6 6h12v12H6z" />
          </svg>
        </button>
        <button
          v-else
          class="shrink-0 w-9 h-9 rounded-xl flex items-center justify-center transition-colors"
          :class="input.trim() ? 'bg-gold text-white hover:bg-gold-dark' : 'bg-gray-100 text-gray-300 cursor-not-allowed'"
          :disabled="!input.trim()"
          @click="submit"
        >
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 12h14M12 5l7 7-7 7" />
          </svg>
        </button>
      </div>
      <p class="text-center text-[11px] text-gray-400 mt-2">
        {{ streaming ? '正在生成，可点击停止' : 'Enter 发送 · Shift+Enter 换行' }}
      </p>
    </div>
  </div>
</template>
