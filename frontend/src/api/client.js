/**

 * 后端 API 客户端

 * 通过 Vite 代理转发到 FastAPI (localhost:8000)

 */



import { ApiError, ErrorCode, normalizeError, parseResponseError, toWarningText } from '../utils/errors'



const BASE = ''



async function request(url, options = {}) {

  let res

  try {

    res = await fetch(`${BASE}${url}`, options)

  } catch (err) {

    throw normalizeError(err)

  }



  if (!res.ok) {

    throw await parseResponseError(res)

  }

  const json = await res.json()

  if (json.code !== 0 && json.code !== undefined) {

    throw new ApiError(ErrorCode.SERVER_ERROR, json.message || '请求失败')

  }

  return json.data

}



/** 获取默认知识库信息 */

export function getKnowledgeBase() {

  return request('/api/kb')

}



/** 获取文档列表 */

export function getDocuments() {

  return request('/api/documents')

}



/** 上传文档 */

export function uploadDocument(file) {

  const form = new FormData()

  form.append('file', file)

  return request('/api/documents', { method: 'POST', body: form })

}



/** 删除文档 */

export function deleteDocument(docId) {

  return request(`/api/documents/${docId}`, { method: 'DELETE' })

}



/** 重建单个文档向量 */

export function rebuildDocument(docId) {

  return request(`/api/documents/${docId}/rebuild`, { method: 'POST' })

}



/** 重建整个知识库向量 */

export function rebuildKnowledgeBase() {

  return request('/api/documents/rebuild', { method: 'POST' })

}



/** 创建对话会话 */

export function createSession(title = '新对话') {

  return request('/api/sessions', {

    method: 'POST',

    headers: { 'Content-Type': 'application/json' },

    body: JSON.stringify({ title }),

  })

}



/** 获取会话列表 */

export function getSessions() {

  return request('/api/sessions')

}



/** 获取会话历史消息 */

export function getMessages(sessionId) {

  return request(`/api/sessions/${sessionId}/messages`)

}



/** 删除对话会话 */

export function deleteSession(sessionId) {

  return request(`/api/sessions/${sessionId}`, { method: 'DELETE' })

}



/**

 * 停止流式生成并持久化当前已生成内容

 * @param {string} sessionId

 * @param {{ content?: string, sources?: object[], requestId?: string }} payload

 */

export function stopChatStream(sessionId, payload = {}) {

  return request(`/api/sessions/${sessionId}/chat/stop`, {

    method: 'POST',

    headers: { 'Content-Type': 'application/json' },

    body: JSON.stringify({

      request_id: payload.requestId || '',

      content: payload.content || '',

      sources: payload.sources || null,

    }),

  })

}



/**

 * SSE 流式对话

 * @param {string} sessionId

 * @param {string} message

 * @param {{ signal?: AbortSignal, onToken: (t: string) => void, onSources: (s: object[]) => void, onWarning?: (w: object) => void, onDone: () => void, onError: (e: Error) => void }} callbacks

 */

export async function chatStream(sessionId, message, callbacks) {

  let res

  try {

    res = await fetch(`${BASE}/api/sessions/${sessionId}/chat`, {

      method: 'POST',

      headers: { 'Content-Type': 'application/json' },

      body: JSON.stringify({ message, stream: true }),

      signal: callbacks.signal,

    })

  } catch (err) {

    throw normalizeError(err)

  }



  if (!res.ok) {

    throw await parseResponseError(res)

  }



  let streamRequestId = res.headers.get('X-Request-ID') || ''

  if (streamRequestId) {

    callbacks.onStart?.({ requestId: streamRequestId })

  }



  const reader = res.body.getReader()

  const decoder = new TextDecoder()

  let buffer = ''

  let doneEventReceived = false



  try {

    while (true) {

      const { done, value } = await reader.read()

      if (done) break



      buffer += decoder.decode(value, { stream: true })

      const parts = buffer.split('\n\n')

      buffer = parts.pop() || ''



      for (const part of parts) {

        const line = part.trim()

        if (!line.startsWith('data: ')) continue

        let event

        try {

          event = JSON.parse(line.slice(6))

        } catch {

          continue

        }



        if (event.type === 'start') {

          streamRequestId = event.request_id || streamRequestId

          callbacks.onStart?.({ requestId: streamRequestId })

        } else if (event.type === 'token') callbacks.onToken(event.content)

        else if (event.type === 'sources') callbacks.onSources(event.data || [])

        else if (event.type === 'warning') callbacks.onWarning?.(event)

        else if (event.type === 'error') {

          const error = new ApiError(

            event.code || ErrorCode.SERVER_ERROR,

            event.message || '生成回答失败',

            '',

            event.request_id || streamRequestId,

          )

          callbacks.onError?.(error)

          throw error

        } else if (event.type === 'done') {

          doneEventReceived = true

          callbacks.onDone()

        }

      }

    }

  } catch (err) {

    if (err?.name === 'AbortError' || callbacks.signal?.aborted) {

      throw err

    }

    throw normalizeError(err)

  }



  if (!doneEventReceived && !callbacks.signal?.aborted) {

    callbacks.onDone()

  }

}



export { toWarningText }


