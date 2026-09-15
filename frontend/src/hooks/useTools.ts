import { useCallback, useEffect, useState } from "react"
import { fetchTools, setToolEnabled } from "@/lib/api"
import type { ToolInfo } from "@/types"

export function useTools() {
  const [tools, setTools] = useState<ToolInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const reload = useCallback(async () => {
    try {
      const data = await fetchTools()
      setTools(data)
      setError(null)
    } catch {
      // A silently-empty panel reads as "no tools exist" — surface the
      // failure instead so it's clear this is a fetch problem, not zero tools.
      setError("Could not load the tool roster — try reloading.")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    reload()
  }, [reload])

  const toggle = useCallback(async (name: string, enabled: boolean) => {
    // optimistic update
    setTools((prev) => prev.map((t) => (t.name === name ? { ...t, enabled } : t)))
    try {
      await setToolEnabled(name, enabled)
    } catch {
      // revert on failure
      setTools((prev) => prev.map((t) => (t.name === name ? { ...t, enabled: !enabled } : t)))
    }
  }, [])

  return { tools, loading, error, toggle }
}
