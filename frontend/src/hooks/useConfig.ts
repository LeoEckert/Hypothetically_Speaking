import { useEffect, useState } from "react"
import { fetchConfig, type ConfigResponse } from "@/lib/api"

export function useConfig() {
  const [config, setConfig] = useState<ConfigResponse | null>(null)

  useEffect(() => {
    fetchConfig()
      .then(setConfig)
      .catch(() =>
        setConfig({ dev_mode: false, demo_question: "", max_tool_calls_default: 30, max_tool_calls_ceiling: 40 })
      )
  }, [])

  return config
}
