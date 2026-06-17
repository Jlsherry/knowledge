/** 格式化文件大小 */
export function formatFileSize(bytes) {
  if (!bytes || bytes === 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(1024))
  return `${(bytes / Math.pow(1024, i)).toFixed(i > 0 ? 2 : 0)} ${units[i]}`
}

/** 相对时间 */
export function formatRelativeTime(dateStr) {
  const date = new Date(dateStr)
  const now = new Date()
  const diff = now - date
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes}分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}小时前`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days}天前`
  return date.toLocaleDateString('zh-CN')
}

/** 简易 markdown 转 HTML（仅支持常用格式） */
export function simpleMarkdown(text) {
  if (!text) return ''
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/`(.+?)`/g, '<code>$1</code>')
    .replace(/^[-*] (.+)$/gm, '<li>$1</li>')
    .replace(/(<li>.*<\/li>\n?)+/g, (m) => `<ul>${m}</ul>`)
    .replace(/\n\n/g, '</p><p>')
    .replace(/\n/g, '<br>')
    .replace(/^(.+)$/, '<p>$1</p>')
}

/** 根据文件类型返回图标色 */
export function fileTypeColor(type) {
  const map = { pdf: '#e74c3c', docx: '#2980b9', txt: '#27ae60' }
  return map[type] || '#888'
}

/** 文档状态中文 */
export function statusLabel(status) {
  const map = {
    pending: '等待中',
    processing: '处理中',
    ready: '已就绪',
    failed: '失败',
  }
  return map[status] || status
}

function normalizeContentFingerprint(content) {
  return (content || '').replace(/\s+/g, '').slice(0, 240)
}

function sourceKey(src) {
  const docId = src.document_id != null ? String(src.document_id) : ''
  const chunkIndex = src.chunk_index != null ? Number(src.chunk_index) : null
  if (docId && chunkIndex != null && !Number.isNaN(chunkIndex)) {
    return `chunk:${docId}:${chunkIndex}`
  }
  const filename = src.filename || ''
  return `text:${filename}:${normalizeContentFingerprint(src.content)}`
}

/** 引用来源去重（与后端 normalize_source_items 规则一致） */
export function dedupeSources(sources) {
  if (!sources?.length) return []
  const seenKeys = new Set()
  const seenFingerprints = new Set()
  const result = []

  for (const src of sources) {
    const key = sourceKey(src)
    const fingerprint = normalizeContentFingerprint(src.content)
    if (seenKeys.has(key) || (fingerprint && seenFingerprints.has(fingerprint))) {
      continue
    }
    seenKeys.add(key)
    if (fingerprint) seenFingerprints.add(fingerprint)
    result.push(src)
  }
  return result
}
