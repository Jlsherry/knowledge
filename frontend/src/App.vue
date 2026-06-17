<script setup>
import { ref, onMounted } from 'vue'
import AppSidebar from './components/AppSidebar.vue'
import WelcomeView from './components/WelcomeView.vue'
import ChatPanel from './components/ChatPanel.vue'
import { createSession, chatStream, stopChatStream, getMessages, rebuildKnowledgeBase } from './api/client'
import { dedupeSources } from './utils/format'
import { ErrorCode, formatError, toChatErrorText, toShortErrorText, toWarningText } from './utils/errors'

const activeTab = ref('kb')
const sidebarCollapsed = ref(false)
const sessionId = ref(null)
const messages = ref([])
const streaming = ref(false)
const toast = ref('')
const sidebarRef = ref(null)
let currentChatController = null
let currentAssistantIdx = null
let currentRequestId = null

/** 将 API 消息转为 ChatPanel 格式 */
function mapMessages(list) {
  return (list || []).map((m) => ({
    role: m.role,
    content: m.content,
    sources: dedupeSources(m.sources || []),
  }))
}

/** 加载指定会话的历史消息 */
async function loadSession(session) {
  sessionId.value = session.id
  activeTab.value = 'chat'
  try {
    const list = await getMessages(session.id)
    messages.value = mapMessages(list)
  } catch (err) {
    showToast(toShortErrorText(err))
    messages.value = []
  }
}

/** 创建新会话 */
async function newChat() {
  try {
    const session = await createSession('新对话')
    sessionId.value = session.id
    messages.value = []
    activeTab.value = 'chat'
    sidebarRef.value?.loadSessions()
    showToast('已开启新对话')
  } catch (err) {
    showToast(toShortErrorText(err))
  }
}

/** 发送消息（SSE 流式） */
async function sendMessage(text) {
  if (!text.trim() || streaming.value) return

  activeTab.value = 'chat'
  currentChatController = new AbortController()

  try {
    if (!sessionId.value) {
      const session = await createSession('新对话')
      sessionId.value = session.id
      sidebarRef.value?.loadSessions()
    }

    const sid = sessionId.value
    messages.value.push({ role: 'user', content: text })

    const assistantIdx = messages.value.length
    currentAssistantIdx = assistantIdx
    messages.value.push({ role: 'assistant', content: '', sources: [] })

    streaming.value = true

    await chatStream(sid, text, {
      signal: currentChatController.signal,
      onStart({ requestId } = {}) {
        currentRequestId = requestId || null
        sidebarRef.value?.loadSessions()
      },
      onToken(token) {
        messages.value[assistantIdx].content += token
      },
      onSources(sources) {
        messages.value[assistantIdx].sources = dedupeSources(sources)
      },
      onWarning(warning) {
        showToast(toWarningText(warning))
      },
      onDone() {
        streaming.value = false
        currentChatController = null
        currentAssistantIdx = null
        currentRequestId = null
        sidebarRef.value?.loadSessions()
      },
      onError(err) {
        messages.value[assistantIdx].content = toChatErrorText(err)
        messages.value[assistantIdx].sources = []
        streaming.value = false
        currentChatController = null
        currentAssistantIdx = null
        currentRequestId = null
      },
    })
  } catch (err) {
    streaming.value = false
    const wasAborted = err?.name === 'AbortError' || err?.code === ErrorCode.GENERATION_STOPPED
    const idx = currentAssistantIdx
    if (idx != null && messages.value[idx]?.role === 'assistant') {
      const current = messages.value[idx].content
      if (wasAborted) {
        messages.value[idx].content = current || '已停止生成。'
      } else if (!current) {
        messages.value[idx].content = toChatErrorText(err)
        messages.value[idx].sources = []
      }
    } else if (!wasAborted) {
      messages.value.push({
        role: 'assistant',
        content: toChatErrorText(err),
        sources: [],
      })
    }
    if (!wasAborted) {
      const { code } = formatError(err)
      if (code === ErrorCode.KB_EMPTY || code === ErrorCode.DOCS_PROCESSING) {
        activeTab.value = 'kb'
      }
    }
    currentChatController = null
    currentAssistantIdx = null
    currentRequestId = null
  }
}

async function stopGeneration() {
  if (!streaming.value) return

  const sid = sessionId.value
  const idx = currentAssistantIdx
  const msg = idx != null ? messages.value[idx] : null
  const partialContent = msg?.content || ''
  const partialSources = msg?.sources || []
  const controller = currentChatController
  const requestId = currentRequestId

  streaming.value = false
  currentChatController = null
  currentAssistantIdx = null
  currentRequestId = null

  if (idx != null && messages.value[idx]?.role === 'assistant') {
    messages.value[idx].content = partialContent || '已停止生成。'
  }

  if (sid && requestId) {
    try {
      await stopChatStream(sid, {
        requestId,
        content: partialContent,
        sources: partialSources,
      })
      sidebarRef.value?.loadSessions()
    } catch (err) {
      console.error('停止生成持久化失败', err)
      showToast(toShortErrorText(err))
    }
  }

  controller?.abort()
}

function handleAsk(question) {
  sendMessage(question)
}

function handleSessionDeleted(deletedId) {
  if (sessionId.value === deletedId) {
    sessionId.value = null
    messages.value = []
  }
}

async function handleRebuild() {
  if (!confirm('确定清空并重建整个知识库向量库？重建期间问答结果可能不稳定。')) return
  showToast('已开始后台重建，可在文档列表查看进度')
  try {
    await rebuildKnowledgeBase()
    await sidebarRef.value?.loadDocuments()
  } catch (err) {
    showToast(toShortErrorText(err))
  }
}

function showToast(msg) {
  toast.value = msg
  setTimeout(() => (toast.value = ''), 3000)
}

onMounted(async () => {
  sidebarRef.value?.loadSessions()
})
</script>

<template>
  <div class="flex h-screen overflow-hidden">
    <AppSidebar
      ref="sidebarRef"
      v-model:active-tab="activeTab"
      v-model:collapsed="sidebarCollapsed"
      :current-session-id="sessionId"
      @rebuild="handleRebuild"
      @select-session="loadSession"
      @new-chat="newChat"
      @session-deleted="handleSessionDeleted"
    />

    <main class="flex-1 grid-bg flex flex-col relative overflow-hidden">
      <header class="flex items-center justify-between px-6 py-3 border-b border-black/5 bg-cream/60 backdrop-blur-sm">
        <div class="text-sm text-gray-500">
          <span v-if="activeTab === 'kb'">知识库管理</span>
          <span v-else>智能对话</span>
        </div>
        <div class="flex items-center gap-1.5 text-xs text-gray-400">
          <span class="w-1.5 h-1.5 rounded-full bg-green-400"></span>
          Qwen + RAG
        </div>
      </header>

      <div class="flex-1 overflow-hidden">
        <WelcomeView v-if="activeTab === 'kb'" @ask="handleAsk" />
        <ChatPanel
          v-else
          :messages="messages"
          :streaming="streaming"
          @send="sendMessage"
          @stop="stopGeneration"
        />
      </div>

      <div v-if="activeTab === 'kb'" class="absolute bottom-6 right-6">
        <button
          class="w-12 h-12 rounded-full bg-rose-400 shadow-lg flex items-center justify-center text-white hover:bg-rose-500 transition-colors"
          title="开始对话"
          @click="activeTab = 'chat'"
        >
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
            />
          </svg>
        </button>
      </div>
    </main>

    <Transition name="fade">
      <div
        v-if="toast"
        class="fixed bottom-8 left-1/2 -translate-x-1/2 px-5 py-2.5 bg-sidebar text-white text-sm rounded-xl shadow-xl z-50"
      >
        {{ toast }}
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
