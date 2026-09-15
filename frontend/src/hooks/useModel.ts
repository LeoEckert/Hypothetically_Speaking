import { useCallback, useSyncExternalStore } from "react"
import {
  getModelPrefs,
  getPreferredModel,
  setModelPref,
  setPreferredModel,
  subscribeModelPrefs,
  type ModelPrefName,
} from "@/store/modelStore"

export function useModel() {
  const preferredModel = useSyncExternalStore(subscribeModelPrefs, getPreferredModel)
  const prefs = useSyncExternalStore(subscribeModelPrefs, getModelPrefs)
  const setModel = useCallback((modelId: string) => setPreferredModel(modelId), [])
  const setPref = useCallback((name: ModelPrefName, modelId: string) => setModelPref(name, modelId), [])
  return { preferredModel, setModel, prefs, setPref }
}
