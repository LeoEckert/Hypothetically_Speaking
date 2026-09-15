// Lets any component (e.g. ToolsPanel's "add a key in Settings" link) open
// the Settings dialog without a prop-drilled callback — SettingsDialog lives
// in AppHeader, ToolsPanel lives inside ComposeDialog, and there's no shared
// parent worth threading a callback through. Same vanilla subscribe pattern
// as apiKeysStore.ts/modelStore.ts, but pure in-memory UI state — nothing
// here is persisted.
let isOpen = false
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

export function setSettingsDialogOpen(open: boolean): void {
  isOpen = open
  notify()
}

export function openSettingsDialog(): void {
  setSettingsDialogOpen(true)
}
