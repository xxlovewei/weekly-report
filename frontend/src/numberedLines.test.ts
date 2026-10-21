import { describe, expect, it } from 'vitest'
import { numberedLineBreak } from './numberedLines'

describe('task description numbered lines', () => {
  it.each([
    ['1. 完成联调', '1. 完成联调\n2. '],
    ['1. 2026年计划', '1. 2026年计划\n2. '],
    ['9、整理数据', '9、整理数据\n10、'],
    ['  2) 调整配置', '  2) 调整配置\n  3) '],
    ['(3) 测试', '(3) 测试\n(4) '],
    ['（4）测试', '（4）测试\n（5）'],
    ['5）测试', '5）测试\n6）'],
    ['6．测试', '6．测试\n7．'],
    ['说明\n09. 测试', '说明\n09. 测试\n10. '],
    ['1. ', '1. \n2. '],
  ])('continues %s preserving its format', (value, expected) => {
    expect(numberedLineBreak(value, value.length, value.length)).toEqual({ value: expected, caret: expected.length })
  })

  it('splits at the caret without changing following lines', () => {
    expect(numberedLineBreak('1. 接口联调\n7. 后续工作', 5, 5)).toEqual({ value: '1. 接口\n2. 联调\n7. 后续工作', caret: 9 })
  })

  it('replaces selected text and keeps the remainder', () => {
    expect(numberedLineBreak('1. 接口联调', 5, 7)).toEqual({ value: '1. 接口\n2. ', caret: 9 })
  })

  it.each(['普通文字', '工作1. 内容', '2026年计划', '1.5版本升级', '（1) 格式不匹配', '9007199254740991. 内容'])('leaves %s to native Enter', value => {
    expect(numberedLineBreak(value, value.length, value.length)).toBeNull()
  })

  it('does not continue when the caret is inside the marker or on a plain line', () => {
    expect(numberedLineBreak('12. 内容', 1, 1)).toBeNull()
    expect(numberedLineBreak('1. 内容\n普通文字', 12, 12)).toBeNull()
  })
})
