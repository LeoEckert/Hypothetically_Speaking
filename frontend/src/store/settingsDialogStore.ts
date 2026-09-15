// Lets any component (e.g. ToolsPanel's "add a key in Settings" link) open
// the Settings dialog — optionally jumping straight to one key's input field
// — without a prop-drilled callback: SettingsDialog lives in AppHeader,
// ToolsPanel lives inside ComposeDialog, and there's no shared parent worth
// threading a callback through. Same vanilla subscribe pattern as
// apiKeysStore.ts/modelStore.ts, but pure in-memory UI state — nothing here
// is persisted.
import type { ApiKeyName } from "@/store/apiKeysStore"

let isOpen = false
let focusKey: ApiKeyName | null = null
const listeners = new Set<() => void>()

function notify() {
  for (const listener of listeners) listener()
}

export function subscribeSettingsDialog(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function getSettingsDialogOpen(): boolean {
  return isOpen
}

export function getSettingsFocusKey(): ApiKeyName | null {
  return focusKey
}

export function setSettingsDialogOpen(open: boolean): void {
  isOpen = open
  if (!open) focusKey = null
  notify()
}

/** Opens Settings, optionally jumping straight to one key's input — e.g. a
 * paid tool's "needs a key" hint links here with its own key_env_var. */
export function openSettingsDialog(key?: ApiKeyName): void {
  isOpen = true
  focusKey = key ?? null
  notify()
}

/** Consumed once the target field has actually been focused, so re-opening
 * Settings later (without a key argument) doesn't re-jump to a stale target. */
export function clearSettingsFocusKey(): void {
  focusKey = null
  notify()
}
