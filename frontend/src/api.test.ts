import { afterEach, expect, it, vi } from 'vitest'
import { api, newIdempotencyKey } from './api'

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
