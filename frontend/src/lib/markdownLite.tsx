import { Fragment, type ReactNode } from 'react'

/** Renders the assistant's `**bold**` spans and `- ` bullet lines as real
 * markup (adapted from jdk_clean). Deliberately minimal -- only what the
 * assistant is told to use -- not a general markdown parser, and it never
 * renders HTML from the text. */
function renderInline(text: string, keyPrefix: string): ReactNode[] {
  return text
    .split(/(\*\*[^*]+\*\*)/g)
    .filter((part) => part !== '')
    .map((part, i) =>
      part.startsWith('**') && part.endsWith('**') && part.length > 4 ? (
        <strong key={`${keyPrefix}-${i}`} className="font-semibold text-gold-100">
          {part.slice(2, -2)}
        </strong>
      ) : (
        <Fragment key={`${keyPrefix}-${i}`}>{part}</Fragment>
      ),
    )
}

export function renderMarkdownLite(content: string): ReactNode {
  const blocks: ReactNode[] = []
  let bullets: string[] = []

  function flush(key: string) {
    if (bullets.length === 0) return
    blocks.push(
      <ul key={key} className="my-1 list-disc space-y-1 pl-4">
        {bullets.map((line, i) => (
          <li key={i}>{renderInline(line, `${key}-${i}`)}</li>
        ))}
      </ul>,
    )
    bullets = []
  }

  content.split('\n').forEach((line, index) => {
    const bullet = /^[-•]\s+(.*)$/.exec(line.trim())
    if (bullet) {
      bullets.push(bullet[1] ?? '')
      return
    }
    flush(`b${index}`)
    if (line.trim() === '') blocks.push(<div key={`s${index}`} className="h-2" />)
    else blocks.push(<p key={`p${index}`}>{renderInline(line, `p${index}`)}</p>)
  })
  flush('b-end')
  return <>{blocks}</>
}
