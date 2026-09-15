import { useCallback, useSyncExternalStore } from "react"
import { clearApiKey, getApiKeysSnapshot, setApiKey, subscribeApiKeys, type ApiKeyName } from "@/store/apiKeysStore"

export function useApiKeys() {
  const keys = useSyncExternalStore(subscribeApiKeys, getApiKeysSnapshot)
  const setKey = useCallback((name: ApiKeyName, value: string) => setApiKey(name, value), [])
  const clearKey = useCallback((name: ApiKeyName) => clearApiKey(name), [])
  return { keys, setKey, clearKey }
}
