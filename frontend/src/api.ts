let csrfToken = ''
export function setCsrf(value: string) { csrfToken = value }
export function newIdempotencyKey() { return Array.from(crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, '0')).join('') }

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message) }
}

export async function api<T>(path: string, method = 'GET', body?: unknown, key?: string): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${import.meta.env.BASE_URL}api${path}`, {
      method,
      credentials: 'same-origin',
      headers: {
        ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
        ...(method === 'GET' ? {} : { 'X-CSRF-Token': csrfToken }),
        ...(key ? { 'Idempotency-Key': key } : {}),
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    })
  } catch { throw new ApiError(0, '网络连接失败，请检查网络后重试。') }
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    const fallback: Record<number, string> = { 401: '登录已失效，请重新登录。', 403: '没有权限执行此操作。', 404: '内容不存在或已被删除。', 409: '内容已发生变化，请刷新后重试。', 422: '输入内容不符合要求，请检查后重试。' }
    const message = typeof data.detail === 'string' && /[\u3400-\u9fff]/.test(data.detail) ? data.detail : (fallback[response.status] || `请求失败（${response.status}），请稍后重试。`)
    throw new ApiError(response.status, message)
  }
  return data as T
}

