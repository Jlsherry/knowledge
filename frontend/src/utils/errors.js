/** 与后端 app/errors.py 对齐的错误码 */
export const ErrorCode = {
  KB_EMPTY: 'KB_EMPTY',
  DOCS_PROCESSING: 'DOCS_PROCESSING',
  KB_NOT_READY: 'KB_NOT_READY',
  MODEL_TIMEOUT: 'MODEL_TIMEOUT',
  MODEL_RATE_LIMIT: 'MODEL_RATE_LIMIT',
  MODEL_ERROR: 'MODEL_ERROR',
  RERANK_DEGRADED: 'RERANK_DEGRADED',
  NETWORK_ERROR: 'NETWORK_ERROR',
  SERVER_ERROR: 'SERVER_ERROR',
  NOT_FOUND: 'NOT_FOUND',
  GENERATION_STOPPED: 'GENERATION_STOPPED',
}

/** 用户可执行的操作提示 */
const ERROR_HINTS = {
  [ErrorCode.KB_EMPTY]: '请先在左侧「知识库」上传 PDF、Word 或 TXT 文档。',
  [ErrorCode.DOCS_PROCESSING]: '文档正在后台处理，请等待状态变为「已就绪」后再提问。',
  [ErrorCode.KB_NOT_READY]: '请检查文档是否处理失败，必要时删除后重新上传或点击重建。',
  [ErrorCode.MODEL_TIMEOUT]: '请稍后重试；若持续超时，可尝试缩短问题或更换网络环境。',
  [ErrorCode.MODEL_RATE_LIMIT]: '请等待片刻后重试，或检查 API 额度是否充足。',
  [ErrorCode.MODEL_ERROR]: '请稍后重试；若问题持续，请检查 DashScope API Key 配置。',
  [ErrorCode.RERANK_DEGRADED]: '本次回答仍基于检索结果生成，通常不影响使用。',
  [ErrorCode.NETWORK_ERROR]: '请确认后端服务已启动，并检查浏览器与服务器之间的网络连接。',
  [ErrorCode.SERVER_ERROR]: '请稍后重试；若仍失败，可查看后端日志排查。',
  [ErrorCode.NOT_FOUND]: '该会话可能已被删除，请新建对话后重试。',
  [ErrorCode.GENERATION_STOPPED]: '',
}

const ERROR_TITLES = {
  [ErrorCode.KB_EMPTY]: '知识库为空',
  [ErrorCode.DOCS_PROCESSING]: '文档处理中',
  [ErrorCode.KB_NOT_READY]: '知识库未就绪',
  [ErrorCode.MODEL_TIMEOUT]: '模型响应超时',
  [ErrorCode.MODEL_RATE_LIMIT]: '调用频率受限',
  [ErrorCode.MODEL_ERROR]: '模型调用失败',
  [ErrorCode.RERANK_DEGRADED]: '重排序已降级',
  [ErrorCode.NETWORK_ERROR]: '网络连接异常',
  [ErrorCode.SERVER_ERROR]: '服务异常',
  [ErrorCode.NOT_FOUND]: '资源不存在',
  [ErrorCode.GENERATION_STOPPED]: '已停止生成',
}

export class ApiError extends Error {
  constructor(code, message, hint = '', requestId = '') {
    super(message || ERROR_TITLES[code] || '请求失败')
    this.name = 'ApiError'
    this.code = code || ErrorCode.SERVER_ERROR
    this.hint = hint || ERROR_HINTS[this.code] || ''
    this.requestId = requestId || ''
  }
}

function detailFromBody(body) {
  const detail = body?.detail
  if (typeof detail === 'object' && detail !== null) {
    return {
      code: detail.code || ErrorCode.SERVER_ERROR,
      message: detail.message || detail.msg || '',
      requestId: detail.request_id || '',
    }
  }
  if (typeof detail === 'string' && detail) {
    return { code: ErrorCode.SERVER_ERROR, message: detail, requestId: '' }
  }
  if (body?.message) {
    return { code: ErrorCode.SERVER_ERROR, message: body.message, requestId: '' }
  }
  return { code: ErrorCode.SERVER_ERROR, message: '', requestId: '' }
}

/** 从 fetch 响应解析结构化错误 */
export async function parseResponseError(res) {
  const body = await res.json().catch(() => ({}))
  const { code, message, requestId } = detailFromBody(body)
  const headerRequestId = res.headers?.get?.('X-Request-ID') || ''
  const fallback =
    res.status === 404
      ? '资源不存在'
      : res.status === 409
        ? '当前无法完成操作'
        : res.status >= 500
          ? '服务暂时不可用'
          : '请求失败'
  return new ApiError(code, message || fallback, '', requestId || headerRequestId)
}

/** 将任意异常规范为 ApiError */
export function normalizeError(err) {
  if (err instanceof ApiError) return err

  if (err?.name === 'AbortError') {
    return new ApiError(ErrorCode.GENERATION_STOPPED, '已停止生成。')
  }

  if (err?.code && ERROR_HINTS[err.code]) {
    return new ApiError(err.code, err.message || ERROR_TITLES[err.code])
  }

  const msg = (err?.message || '').toLowerCase()
  if (
    err instanceof TypeError ||
    msg.includes('failed to fetch') ||
    msg.includes('networkerror') ||
    msg.includes('network')
  ) {
    return new ApiError(ErrorCode.NETWORK_ERROR, '无法连接服务器，请检查网络或确认后端已启动。')
  }

  if (msg.includes('timeout') || msg.includes('timed out')) {
    return new ApiError(ErrorCode.MODEL_TIMEOUT)
  }

  return new ApiError(ErrorCode.SERVER_ERROR, err?.message || '请求失败')
}

/** 格式化为 { title, message, hint, requestId } */
export function formatError(err) {
  const apiErr = normalizeError(err)
  return {
    code: apiErr.code,
    title: ERROR_TITLES[apiErr.code] || '出错了',
    message: apiErr.message,
    hint: apiErr.hint,
    requestId: apiErr.requestId || '',
  }
}

function appendRequestId(text, requestId) {
  if (!requestId) return text
  return `${text}\n\n请求 ID：\`${requestId}\`（排查问题时提供给管理员）`
}

/** 对话气泡中的错误展示（支持 simpleMarkdown） */
export function toChatErrorText(err) {
  const { title, message, hint, requestId } = formatError(err)
  let text = `**${title}**\n\n${message}`
  if (hint) text += `\n\n> ${hint}`
  return appendRequestId(text, requestId)
}

/** Toast / alert 单行摘要 */
export function toShortErrorText(err) {
  const { title, message, requestId } = formatError(err)
  let text = `${title}：${message}`
  if (requestId) text += `（请求 ID: ${requestId}）`
  return text
}

/** 非阻断提示（如 rerank 降级） */
export function toWarningText(warning) {
  const code = warning?.code || ErrorCode.RERANK_DEGRADED
  const message = warning?.message || ERROR_TITLES[code] || '提示'
  const hint = ERROR_HINTS[code]
  return hint ? `${message}（${hint}）` : message
}
