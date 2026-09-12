import { useEffect, useState } from "react"

/** Seconds elapsed since `since` (a Date.now() timestamp), ticking once a
 * second while `active`. Used anywhere a wait has no finer-grained progress
 * signal of its own (a phase step, a single in-flight tool call). */
export function useElapsedSeconds(since: number | undefined, active: boolean): number {
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    if (!active) return
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [active])
  return since ? Math.max(0, Math.floor((now - since) / 1000)) : 0
}
