import { Badge } from "@/components/ui/badge"
import { Switch } from "@/components/ui/switch"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import { useTools } from "@/hooks/useTools"
import { toolLabel } from "@/lib/toolLabels"

export function ToolsPanel({ isRunLive }: { isRunLive: boolean }) {
  const { tools, loading, toggle } = useTools()

  return (
    <Collapsible defaultOpen className="border rounded-lg p-3">
      <CollapsibleTrigger className="text-sm font-semibold cursor-pointer">Available tools</CollapsibleTrigger>
      <CollapsibleContent className="mt-2 space-y-3">
        {isRunLive && (
          <p className="text-xs text-muted-foreground">
            A run is in progress — toggles here apply to the next run, not the one currently running.
          </p>
        )}
        {loading && <p className="text-xs text-muted-foreground">Loading…</p>}
        {tools.map((tool) => (
          <div key={tool.name} className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium">{toolLabel(tool.name)}</span>
                <Badge variant={tool.enabled ? "secondary" : "outline"} className="text-[10px]">
                  {tool.enabled ? "enabled" : "disabled"}
                </Badge>
              </div>
              <p className="text-xs text-muted-foreground">{tool.description}</p>
            </div>
            <Switch
              checked={tool.enabled}
              onCheckedChange={(checked) => toggle(tool.name, checked)}
              className="mt-1 shrink-0"
            />
          </div>
        ))}
      </CollapsibleContent>
    </Collapsible>
  )
}
