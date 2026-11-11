import React from 'react'

// A deliberately small renderer: never execute source HTML or link protocols.
// Installation/confirmation cards come only from structured events, not prose.
function inline(text) {
  const parts = String(text).split(/(\*\*[^*\n]+\*\*|`[^`\n]+`|\[[^\]\n]+\]\([^\s)]+\))/g)
  return parts.map((part, index) => {
    if (part.startsWith('**') && part.endsWith('**')) return <strong key={index}>{part.slice(2, -2)}</strong>
    if (part.startsWith('`') && part.endsWith('`')) return <code key={index} className="rounded bg-surface-900 px-1 font-mono text-cyber-cyan">{part.slice(1, -1)}</code>
    const link = part.match(/^\[([^\]]+)\]\(([^)]+)\)$/)
    if (link) {
      try {
        const url = new URL(link[2])
        if (['https:', 'http:'].includes(url.protocol)) return <a key={index} href={url.href} target="_blank" rel="noopener noreferrer" className="text-cyber-cyan underline">{link[1]}</a>
      } catch (_) { /* Keep malformed links as literal text. */ }
    }
    return part
  })
}

const cells = line => line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(cell => cell.trim())
const separator = line => !!line && line.includes('|') && cells(line).every(cell => /^:?-{3,}:?$/.test(cell))

export default function ChatMarkdown({ text = '' }) {
  const lines = String(text).replace(/\r\n/g, '\n').split('\n')
  const blocks = []
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    if (!line.trim()) continue
    if (line.startsWith('```')) {
      const body = []
      while (++i < lines.length && !lines[i].startsWith('```')) body.push(lines[i])
      blocks.push(<pre key={i} className="my-2 overflow-x-auto rounded-md bg-surface-900 p-3 text-xs font-mono text-cyber-cyan">{body.join('\n')}</pre>)
      continue
    }
    if (line.includes('|') && separator(lines[i + 1])) {
      const headers = cells(line)
      const rows = []
      i += 2
      while (i < lines.length && lines[i].includes('|') && lines[i].trim()) rows.push(cells(lines[i++]))
      i--
      blocks.push(<div key={i} className="my-3 overflow-x-auto"><table className="w-full border-collapse text-left text-xs"><thead><tr>{headers.map((cell, n) => <th key={n} className="border-b border-surface-600 p-2 font-semibold">{inline(cell)}</th>)}</tr></thead><tbody>{rows.map((row, n) => <tr key={n}>{headers.map((_, c) => <td key={c} className="border-b border-surface-700 p-2 align-top">{inline(row[c] || '')}</td>)}</tr>)}</tbody></table></div>)
      continue
    }
    if (/^#{1,6}\s/.test(line)) {
      blocks.push(<h3 key={i} className="mb-1 mt-3 text-base font-semibold text-white">{inline(line.replace(/^#+\s/, ''))}</h3>)
      continue
    }
    if (/^\s*(?:[-*]\s|\d+[.)]\s)/.test(line)) {
      const ordered = /^\s*\d+[.)]\s/.test(line)
      const pattern = ordered ? /^\s*\d+[.)]\s/ : /^\s*[-*]\s/
      const items = []
      do { items.push(<li key={i}>{inline(lines[i].replace(pattern, ''))}</li>); i++ } while (i < lines.length && pattern.test(lines[i]))
      i--
      blocks.push(ordered ? <ol key={i} className="my-2 ml-5 list-decimal space-y-1">{items}</ol> : <ul key={i} className="my-2 ml-5 list-disc space-y-1">{items}</ul>)
      continue
    }
    if (/^\s*(?:---+|\*\*\*+)\s*$/.test(line)) {
      blocks.push(<hr key={i} className="my-3 border-surface-700" />)
      continue
    }
    blocks.push(<p key={i} className="my-1 break-words">{inline(line)}</p>)
  }
  return <div className="chat-markdown leading-relaxed">{blocks}</div>
}
