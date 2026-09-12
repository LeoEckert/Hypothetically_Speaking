export function ReasoningBlock({ text }: { text: string }) {
  return (
    <blockquote className="border-l-2 border-muted-foreground/30 pl-3 py-1 my-2 text-sm italic text-muted-foreground">
      {text.slice(0, 500)}
    </blockquote>
  )
}
