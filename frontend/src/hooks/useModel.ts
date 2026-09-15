import { useCallback, useSyncExternalStore } from "react"
import { getPreferredModel, setPreferredModel, subscribePreferredModel } from "@/store/modelStore"

export function useModel() {
  const preferredModel = useSyncExternalStore(subscribePreferredModel, getPreferredModel)
  const setModel = useCallback((modelId: string) => setPreferredModel(modelId), [])
  return { preferredModel, setModel }
}
