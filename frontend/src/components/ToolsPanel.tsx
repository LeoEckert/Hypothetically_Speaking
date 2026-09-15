import { Badge } from "@/components/ui/badge"
import { Switch } from "@/components/ui/switch"
import { useApiKeys } from "@/hooks/useApiKeys"
import { useTools } from "@/hooks/useTools"
import { toolLabel } from "@/lib/toolLabels"
import { openSettingsDialog } from "@/store/settingsDialogStore"

export function ToolsPanel({ isRunLive }: { isRunLive: boolean }) {
  const { tools, loading, error, toggle } = useTools()
  const { keys } = useApiKeys()

  return (
    <div className="space-y-3">
      {isRunLive && (
        <p className="text-xs text-muted-foreground">
          A run is in progress — toggles here apply to the next run, not the one currently running.
        </p>
      )}
      {loading && <p className="text-xs text-muted-foreground">Loading…</p>}
      {error && <p className="text-xs text-destructive">{error}</p>}
      {tools.map((tool) => {
        // "Enabled" only really means something if the tool can also do
        // something real: a keyed tool with neither a platform key nor the
        // viewer's own BYOK key can only ever mock, so it shouldn't read as
        // ready even while its own toggle is on.
        const hasKey = !tool.key_env_var || tool.key_configured || !!keys[tool.key_env_var as keyof typeof keys]
        const usable = tool.enabled && hasKey
        return (
          <div
            key={tool.name}
            className="flex items-start justify-between gap-3 rounded-md p-1.5 -mx-1.5 hover:bg-accent/40 transition-colors"
          >
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium">{toolLabel(tool.name)}</span>
                <Badge
                  variant="outline"
                  className={
                    usable
                      ? "text-[10px] border-green-300 bg-green-50 text-green-700 dark:border-green-800 dark:bg-green-950/40 dark:text-green-300"
                      : "text-[10px] text-muted-foreground"
                  }
                >
                  {usable ? "enabled" : "disabled"}
                </Badge>
                {tool.paid && (
                  <Badge
                    variant="outline"
                    className="text-[10px] border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-300"
                  >
                    paid
                  </Badge>
                )}
              </div>
              <p className="text-xs text-muted-foreground mt-0.5">{tool.description}</p>
              {!hasKey && (
                <p className="text-xs text-amber-600 dark:text-amber-400 mt-0.5">
                  {tool.paid ? "No free tier for this one — add" : "Runs as a mock without"} your own key in{" "}
                  <button
                    type="button"
                    onClick={openSettingsDialog}
                    className="underline underline-offset-2 hover:text-amber-700 dark:hover:text-amber-300"
                  >
                    Settings
                  </button>{" "}
                  to switch it on.
                </p>
              )}
            </div>
            <Switch
              checked={usable}
              disabled={!hasKey}
              onCheckedChange={(checked) => toggle(tool.name, checked)}
              className="mt-1 shrink-0"
            />
          </div>
        )
      })}
    </div>
  )
}
