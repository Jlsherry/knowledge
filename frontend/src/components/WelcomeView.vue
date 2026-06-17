<script setup>
const props = defineProps({
  questions: { type: Array, default: () => [] },
})

const emit = defineEmits(['ask'])

const defaultQuestions = [
  '知识库中有哪些主要内容？',
  '请帮我总结一下文档的核心要点',
  '文档里提到了哪些关键流程？',
  '有哪些需要注意的规章制度？',
]

const list = props.questions.length ? props.questions : defaultQuestions
</script>

<template>
  <div class="flex flex-col items-center justify-center h-full px-8 py-12">
    <!-- Logo -->
    <div
      class="w-16 h-16 rounded-2xl bg-sidebar flex items-center justify-center text-gold font-serif font-bold text-3xl shadow-lg mb-6"
    >
      问
    </div>

    <!-- 标题 -->
    <h1 class="font-serif text-4xl font-bold text-gray-800 tracking-wide">智问·知识库</h1>
    <p class="mt-3 text-base text-slate-500 tracking-widest">检索增强 · 智能问答 · 多轮对话</p>

    <!-- 快捷问题卡片 -->
    <div class="w-full max-w-lg mt-12 space-y-3">
      <button
        v-for="(q, i) in list"
        :key="i"
        class="w-full flex items-center justify-between px-5 py-4 bg-white rounded-2xl shadow-card text-left text-gray-700 text-sm hover:shadow-md hover:border-gold/30 border border-transparent transition-all group"
        @click="emit('ask', q)"
      >
        <span>{{ q }}</span>
        <svg
          class="w-4 h-4 text-gray-300 group-hover:text-gold transition-colors shrink-0 ml-3"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
        </svg>
      </button>
    </div>

    <p class="mt-10 text-xs text-gray-400">
      基于 Qwen 大模型 + RAG 检索，答案来源于已上传的知识库文档
    </p>
  </div>
</template>
