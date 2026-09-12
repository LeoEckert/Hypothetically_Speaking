/** A three-dot "..." indicator for a wait with no finer-grained progress
 * signal (a slow external tool call, or Claude "thinking" between tool
 * calls) — built from Tailwind's built-in animate-bounce plus staggered
 * delays, no new dependency or custom keyframes. */
export function WaitingDots({ className = "" }: { className?: string }) {
  return (
    <span className={`inline-flex items-center gap-0.5 align-middle ${className}`} aria-hidden="true">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="size-1 rounded-full bg-primary/70 animate-bounce"
          style={{ animationDelay: `${i * 150}ms`, animationDuration: "900ms" }}
        />
      ))}
    </span>
  )
}
