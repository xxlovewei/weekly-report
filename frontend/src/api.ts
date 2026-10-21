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

function base64(bytes: Uint8Array): string {
  let binary = ''
  for (const byte of bytes) binary += String.fromCharCode(byte)
  return btoa(binary)
}

export async function credentialApi<T>(path: string, body: object): Promise<T> {
  if (!crypto.subtle) throw new ApiError(0, '请通过 HTTPS 安全连接访问后重试。')
  const { key } = await api<{ key: string }>('/auth/public-key')
  let encrypted: { key: string; iv: string; data: string }
  try {
    const der = Uint8Array.from(atob(key), char => char.charCodeAt(0))
    const publicKey = await crypto.subtle.importKey('spki', der, { name: 'RSA-OAEP', hash: 'SHA-256' }, false, ['encrypt'])
    const aesKey = await crypto.subtle.generateKey({ name: 'AES-GCM', length: 256 }, true, ['encrypt'])
    const iv = crypto.getRandomValues(new Uint8Array(12))
    const rawKey = new Uint8Array(await crypto.subtle.exportKey('raw', aesKey))
    const wrappedKey = new Uint8Array(await crypto.subtle.encrypt({ name: 'RSA-OAEP' }, publicKey, rawKey))
    const data = new Uint8Array(await crypto.subtle.encrypt(
      { name: 'AES-GCM', iv, additionalData: new TextEncoder().encode(path) },
      aesKey,
      new TextEncoder().encode(JSON.stringify(body)),
    ))
    encrypted = { key: base64(wrappedKey), iv: base64(iv), data: base64(data) }
  } catch {
    throw new ApiError(0, '密码加密失败，请刷新页面后重试。')
  }
  return api<T>(path, 'POST', encrypted)
}

