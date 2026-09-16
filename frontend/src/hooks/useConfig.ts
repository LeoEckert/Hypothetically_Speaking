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
          max_tool_calls_default: 15,
          max_tool_calls_ceiling: 25,
          anthropic_key_configured: false,
          openrouter_key_configured: false,
          default_provider: "openrouter",
          provider_order: ["anthropic", "openrouter"],
        })
      )
  }, [])

  return config
}
