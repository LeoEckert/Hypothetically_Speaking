import { useCallback, useEffect, useState } from "react"
import { fetchTools, setToolEnabled } from "@/lib/api"
import type { ToolInfo } from "@/types"

export function useTools() {
  const [tools, setTools] = useState<ToolInfo[]>([])
  const [loading, setLoading] = useState(true)

  const reload = useCallback(async () => {
    try {
      const data = await fetchTools()
      setTools(data)
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

  return { tools, loading, toggle }
}
