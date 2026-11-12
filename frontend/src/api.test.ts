import { afterEach, expect, it, vi } from 'vitest'
import { api, credentialApi, newIdempotencyKey } from './api'

afterEach(() => vi.unstubAllGlobals())

it('把服务端英文和网络异常转换为中文提示', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 404, json: async () => ({ detail: 'Not Found' }) }))
  await expect(api('/missing')).rejects.toThrow('内容不存在或已被删除。')
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
  await expect(api('/offline')).rejects.toThrow('网络连接失败，请检查网络后重试。')
})

it('在没有 randomUUID 的 HTTP 环境生成不同的幂等键', () => {
  const first = newIdempotencyKey()
  const second = newIdempotencyKey()
  expect(first).toMatch(/^[0-9a-f]{32}$/)
  expect(second).not.toBe(first)
})

it('加密整个凭据请求体并绑定目标接口', async () => {
  const keys = await crypto.subtle.generateKey({ name: 'RSA-OAEP', modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: 'SHA-256' }, true, ['encrypt', 'decrypt']) as CryptoKeyPair
  const key = btoa(String.fromCharCode(...new Uint8Array(await crypto.subtle.exportKey('spki', keys.publicKey))))
  const fetchMock = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => ({ key }) })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ ok: true }) })
  vi.stubGlobal('fetch', fetchMock)
  await expect(credentialApi('/auth/login', { username: 'alice', password: 'secret-123' })).resolves.toEqual({ ok: true })
  const request = fetchMock.mock.calls[1][1]
  expect(request.body).not.toContain('secret-123')
  expect(request.body).not.toContain('alice')
  const encrypted = JSON.parse(request.body)
  expect(Object.keys(encrypted).sort()).toEqual(['data', 'iv', 'key'])
  const aesKey = await crypto.subtle.importKey('raw', await crypto.subtle.decrypt({ name: 'RSA-OAEP' }, keys.privateKey, Uint8Array.from(atob(encrypted.key), char => char.charCodeAt(0))), 'AES-GCM', false, ['decrypt'])
  const plaintext = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: Uint8Array.from(atob(encrypted.iv), char => char.charCodeAt(0)), additionalData: new TextEncoder().encode('/auth/login') }, aesKey, Uint8Array.from(atob(encrypted.data), char => char.charCodeAt(0)))
  expect(JSON.parse(new TextDecoder().decode(plaintext))).toEqual({ username: 'alice', password: 'secret-123' })
})
