export function numberedLineBreak(value: string, start: number, end: number): { value: string; caret: number } | null {
  const lineStart = value.lastIndexOf('\n', start - 1) + 1
  const lineEnd = value.indexOf('\n', start)
  const line = value.slice(lineStart, lineEnd === -1 ? value.length : lineEnd)
  const match = /^([ \t]*)([(（]?)(\d+)([.．、)）])([ \t]*)/.exec(line)
  if (!match || start < lineStart + match[0].length) return null
  const [, indent, opening, digits, closing, spacing] = match
  if ((opening === '(' && closing !== ')') || (opening === '（' && closing !== '）')) return null
  if (/[.．]/.test(closing) && !spacing && /^\d/.test(line.slice(match[0].length))) return null
  const next = Number(digits) + 1
  if (!Number.isSafeInteger(next)) return null
  const number = digits.startsWith('0') ? String(next).padStart(digits.length, '0') : String(next)
  const insertion = `\n${indent}${opening}${number}${closing}${spacing}`
  return { value: value.slice(0, start) + insertion + value.slice(end), caret: start + insertion.length }
}
