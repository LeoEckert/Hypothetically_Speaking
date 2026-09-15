import { useEffect, useState } from "react"
import { fetchConfig, type ConfigResponse } from "@/lib/api"

export function useConfig() {
  const [config, setConfig] = useState<ConfigResponse | null>(null)

  useEffect(() => {
    fetchConfig()
      .then(setConfig)
      .catch(() =>
        setConfig({
          dev_mode: false,
          demo_question: "",
          max_tool_calls_default: 8,
          max_tool_calls_ceiling: 12,
          anthropic_key_configured: false,
          groq_key_configured: false,
          default_provider: "groq",
        })
      )
  }, [])

  return config
}
