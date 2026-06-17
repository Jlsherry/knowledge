<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import {
  getDocuments,
  uploadDocument,
  deleteDocument,
  rebuildDocument,
  getSessions,
  deleteSession,
} from '../api/client'
import { formatFileSize } from '../utils/format'
import { toShortErrorText } from '../utils/errors'
import DocumentItem from './DocumentItem.vue'
import SessionItem from './SessionItem.vue'

const props = defineProps({
  activeTab: { type: String, default: 'kb' },
  collapsed: { type: Boolean, default: false },
  currentSessionId: { type: String, default: null },
})

const emit = defineEmits([
  'update:activeTab',
  'update:collapsed',
  'rebuild',
  'selectSession',
  'newChat',
  'sessionDeleted',
])

const documents = ref([])
const sessions = ref([])
const searchQuery = ref('')
const sessionSearch = ref('')
const uploading = ref(false)
const loadingDocs = ref(false)
const loadingSessions = ref(false)
const fileInput = ref(null)
const DOCS_POLL_INTERVAL_MS = 3000
let docsPollTimer = null

const filteredDocs = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  if (!q) return documents.value
  return documents.value.filter((d) => d.filename.toLowerCase().includes(q))
})

const filteredSessions = computed(() => {
  const q = sessionSearch.value.trim().toLowerCase()
  if (!q) return sessions.value
  return sessions.value.filter((s) => (s.title || '新对话').toLowerCase().includes(q))
})

const totalSize = computed(() =>
  documents.value.reduce((sum, d) => sum + (d.file_size || 0), 0)
)

const readyCount = computed(() =>
  documents.value.filter((d) => d.status === 'ready').length
)

const hasProcessingDocs = computed(() =>
  documents.value.some((d) => d.status === 'pending' || d.status === 'processing')
)

function stopDocumentsPolling() {
  if (docsPollTimer) {
    window.clearTimeout(docsPollTimer)
    docsPollTimer = null
  }
}

function scheduleDocumentsPoll() {
  stopDocumentsPolling()
  if (!hasProcessingDocs.value) return
  docsPollTimer = window.setTimeout(() => {
    docsPollTimer = null
    loadDocuments(true)
  }, DOCS_POLL_INTERVAL_MS)
}

function syncDocumentsPolling() {
  if (hasProcessingDocs.value) {
    scheduleDocumentsPoll()
  } else {
    stopDocumentsPolling()
  }
}

async function loadDocuments(fromPoll = false) {
  if (loadingDocs.value && fromPoll) return
  loadingDocs.value = true
  try {
    documents.value = await getDocuments()
  } catch (e) {
    console.error(e)
  } finally {
    loadingDocs.value = false
    syncDocumentsPolling()
  }
}

/** 加载历史对话会话列表 */
async function loadSessions() {
  loadingSessions.value = true
  try {
    sessions.value = await getSessions()
  } catch (e) {
    console.error(e)
  } finally {
    loadingSessions.value = false
  }
}

function triggerUpload() {
  fileInput.value?.click()
}

async function onFileChange(e) {
  const file = e.target.files?.[0]
  if (!file) return
  e.target.value = ''

  const ext = file.name.split('.').pop()?.toLowerCase()
  if (!['pdf', 'docx', 'txt'].includes(ext)) {
    alert('仅支持 PDF、DOCX、TXT 格式')
    return
  }
  if (file.size > 20 * 1024 * 1024) {
    alert('文件大小不能超过 20MB')
    return
  }

  uploading.value = true
  try {
    const data = await uploadDocument(file)
    await loadDocuments()
    if (data?.status === 'failed') {
      alert(`文档处理失败：${data.error_message || '未知错误'}`)
    }
  } catch (err) {
    alert(toShortErrorText(err))
  } finally {
    uploading.value = false
  }
}

async function handleDelete(doc) {
  if (!confirm(`确定删除「${doc.filename}」？`)) return
  try {
    await deleteDocument(doc.id)
    await loadDocuments()
  } catch (err) {
    alert(toShortErrorText(err))
  }
}

async function handleRebuildDocument(doc) {
  if (!confirm(`确定重建「${doc.filename}」的向量？`)) return
  try {
    await rebuildDocument(doc.id)
    await loadDocuments()
  } catch (err) {
    alert(toShortErrorText(err))
  }
}

function switchTab(tab) {
  emit('update:activeTab', tab)
}

function handleSelectSession(session) {
  emit('selectSession', session)
}

function handleNewChat() {
  emit('newChat')
}

async function handleDeleteSession(session) {
  const title = session.title || '新对话'
  if (!confirm(`确定删除「${title}」？`)) return
  try {
    await deleteSession(session.id)
    await loadSessions()
    emit('sessionDeleted', session.id)
  } catch (err) {
    alert(toShortErrorText(err))
  }
}

watch(
  () => props.activeTab,
  (tab) => {
    if (tab === 'kb') loadDocuments()
    if (tab === 'chat') loadSessions()
  }
)

onMounted(() => {
  loadDocuments()
  loadSessions()
})

onBeforeUnmount(() => {
  stopDocumentsPolling()
})

defineExpose({ loadDocuments, loadSessions, readyCount })
</script>

<template>
  <aside
    class="flex flex-col h-full bg-sidebar text-white/90 transition-all duration-300"
    :class="collapsed ? 'w-16' : 'w-72'"
  >
    <!-- 顶部 Logo -->
    <div class="flex items-center justify-between px-4 py-4 border-b border-white/10">
      <div v-if="!collapsed" class="flex items-center gap-3">
        <div
          class="w-9 h-9 rounded-lg bg-black flex items-center justify-center text-gold font-serif font-bold text-lg shrink-0"
        >
          问
        </div>
        <div>
          <div class="text-sm font-medium text-white leading-tight">智问·知识库</div>
          <div class="text-[10px] text-gold/80 mt-0.5">RAG 智能问答 v1.0</div>
        </div>
      </div>
      <div
        v-else
        class="w-9 h-9 mx-auto rounded-lg bg-black flex items-center justify-center text-gold font-serif font-bold text-lg"
      >
        问
      </div>
      <button
        class="p-1.5 rounded hover:bg-white/10 text-white/60 hover:text-white transition-colors"
        :class="collapsed ? 'mx-auto mt-2' : ''"
        @click="emit('update:collapsed', !collapsed)"
      >
        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M4 6h16M4 12h16M4 18h16" />
        </svg>
      </button>
    </div>

    <template v-if="!collapsed">
      <!-- 标签切换 -->
      <div class="flex mx-4 mt-4 border border-white/10 rounded-lg overflow-hidden">
        <button
          class="flex-1 py-2 text-sm transition-colors"
          :class="
            activeTab === 'chat'
              ? 'bg-white/10 text-gold border-b-2 border-gold'
              : 'text-white/50 hover:text-white/80'
          "
          @click="switchTab('chat')"
        >
          对话
        </button>
        <button
          class="flex-1 py-2 text-sm transition-colors"
          :class="
            activeTab === 'kb'
              ? 'bg-white/10 text-gold border-b-2 border-gold'
              : 'text-white/50 hover:text-white/80'
          "
          @click="switchTab('kb')"
        >
          知识库
        </button>
      </div>

      <!-- ========== 知识库面板 ========== -->
      <template v-if="activeTab === 'kb'">
        <div class="px-4 mt-4 space-y-2">
          <button
            class="w-full flex items-center justify-center gap-2 py-2.5 rounded-lg border border-gold/40 text-gold text-sm hover:bg-gold/10 transition-colors disabled:opacity-50"
            :disabled="uploading"
            @click="triggerUpload"
          >
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
            </svg>
            {{ uploading ? '上传中...' : '上传文档' }}
          </button>
          <button
            class="w-full flex items-center justify-center gap-2 py-2 rounded-lg border border-white/10 text-white/60 text-sm hover:bg-white/5 transition-colors"
            @click="emit('rebuild')"
          >
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
              />
            </svg>
            重建向量库
          </button>
          <input ref="fileInput" type="file" accept=".pdf,.docx,.txt" class="hidden" @change="onFileChange" />
          <p class="text-[11px] text-white/30 text-center">支持 TXT、PDF、DOCX（须为新版 Word，非 .doc）| 最大 20MB</p>
        </div>

        <div class="px-4 mt-4">
          <div class="relative">
            <svg
              class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/30"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
              />
            </svg>
            <input
              v-model="searchQuery"
              type="text"
              placeholder="搜索文档..."
              class="w-full pl-9 pr-3 py-2 bg-white/5 border border-white/10 rounded-lg text-sm text-white placeholder-white/30 focus:outline-none focus:border-gold/40"
            />
          </div>
        </div>

        <div class="px-4 mt-3 text-[11px] text-white/40">
          文档数量 {{ documents.length }} &nbsp;·&nbsp; 已就绪 {{ readyCount }}
          <span v-if="hasProcessingDocs">&nbsp;·&nbsp; 处理中...</span>
          &nbsp;·&nbsp; 总大小
          {{ formatFileSize(totalSize) }}
        </div>

        <div class="flex-1 overflow-y-auto custom-scroll px-3 mt-3 pb-4">
          <div v-if="loadingDocs" class="text-center text-white/30 text-sm py-8">加载中...</div>
          <div v-else-if="filteredDocs.length === 0" class="text-center text-white/30 text-sm py-8">
            {{ searchQuery ? '无匹配文档' : '暂无文档，请上传' }}
          </div>
          <DocumentItem
            v-for="doc in filteredDocs"
            :key="doc.id"
            :doc="doc"
            @delete="handleDelete"
            @rebuild="handleRebuildDocument"
          />
        </div>
      </template>

      <!-- ========== 对话面板：历史会话 ========== -->
      <template v-else>
        <div class="px-4 mt-4">
          <button
            class="w-full flex items-center justify-center gap-2 py-2.5 rounded-lg border border-gold/40 text-gold text-sm hover:bg-gold/10 transition-colors"
            @click="handleNewChat"
          >
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
            </svg>
            新对话
          </button>
        </div>

        <div class="px-4 mt-4">
          <div class="relative">
            <svg
              class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/30"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
              />
            </svg>
            <input
              v-model="sessionSearch"
              type="text"
              placeholder="搜索对话..."
              class="w-full pl-9 pr-3 py-2 bg-white/5 border border-white/10 rounded-lg text-sm text-white placeholder-white/30 focus:outline-none focus:border-gold/40"
            />
          </div>
        </div>

        <div class="px-4 mt-3 text-[11px] text-white/40">历史对话 {{ sessions.length }} 条</div>

        <div class="flex-1 overflow-y-auto custom-scroll px-3 mt-3 pb-4">
          <div v-if="loadingSessions" class="text-center text-white/30 text-sm py-8">加载中...</div>
          <div v-else-if="filteredSessions.length === 0" class="text-center text-white/30 text-sm py-8">
            {{ sessionSearch ? '无匹配对话' : '暂无历史对话' }}
          </div>
          <SessionItem
            v-for="s in filteredSessions"
            :key="s.id"
            :session="s"
            :active="s.id === currentSessionId"
            @select="handleSelectSession"
            @delete="handleDeleteSession"
          />
        </div>
      </template>
    </template>
  </aside>
</template>
