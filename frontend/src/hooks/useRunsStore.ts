import { useSyncExternalStore } from "react"
import { getSnapshot, subscribe } from "@/store/runsStore"

export function useRunsStore() {
  return useSyncExternalStore(subscribe, getSnapshot)
}
