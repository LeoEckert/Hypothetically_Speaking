import { useState } from "react"

const PREVIEW_LENGTH = 500

export function ReasoningBlock({ text }: { text: string }) {
  const [expanded, setExpanded] = useState(false)
  const truncated = text.length > PREVIEW_LENGTH
  const shown = expanded || !truncated ? text : text.slice(0, PREVIEW_LENGTH) + "…"

  return (
    <blockquote className="border-l-2 border-muted-foreground/30 pl-3 py-1 my-2 text-sm italic text-muted-foreground">
      {shown}
      {truncated && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="ml-1.5 not-italic text-xs text-primary hover:underline cursor-pointer"
        >
          {expanded ? "show less" : "show more"}
        </button>
      )}
    </blockquote>
  )
}
