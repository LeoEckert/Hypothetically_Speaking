import { Badge } from "@/components/ui/badge"
import { Switch } from "@/components/ui/switch"
import { useApiKeys } from "@/hooks/useApiKeys"
import { useTools } from "@/hooks/useTools"
import { toolLabel } from "@/lib/toolLabels"

export function ToolsPanel({ isRunLive }: { isRunLive: boolean }) {
  const { tools, loading, toggle } = useTools()
  const { keys } = useApiKeys()

  return (
    <div className="space-y-3">
      {isRunLive && (
        <p className="text-xs text-muted-foreground">
          A run is in progress — toggles here apply to the next run, not the one currently running.
        </p>
      )}
      {loading && <p className="text-xs text-muted-foreground">Loading…</p>}
      {tools.map((tool) => (
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
                  tool.enabled
                    ? "text-[10px] border-green-300 bg-green-50 text-green-700 dark:border-green-800 dark:bg-green-950/40 dark:text-green-300"
                    : "text-[10px] text-muted-foreground"
                }
              >
                {tool.enabled ? "enabled" : "disabled"}
              </Badge>
            </div>
            <p className="text-xs text-muted-foreground mt-0.5">{tool.description}</p>
            {tool.key_env_var && !tool.key_configured && !keys[tool.key_env_var as keyof typeof keys] && (
              <p className="text-xs text-amber-600 dark:text-amber-400 mt-0.5">
                Runs as a mock — bring your own key in Settings for live results.
              </p>
            )}
          </div>
          <Switch
            checked={tool.enabled}
            onCheckedChange={(checked) => toggle(tool.name, checked)}
            className="mt-1 shrink-0"
          />
        </div>
      ))}
    </div>
  )
}
