import { useCallback, useEffect, useState } from "react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Textarea } from "@/components/ui/textarea"
import { UsageHistoryChart } from "@/components/UsageHistoryChart"
import { fetchAdminKeys, fetchAdminUsage, fetchAdminUsageHistory, rotateAdminKey } from "@/lib/api"
import type { AdminKeyInfo, AdminUsageHistory, AdminUsageSnapshot } from "@/types"

const ADMIN_TOKEN_KEY = "admin_token"

function usd(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—"
  return `$${value.toFixed(4)}`
}

function RotateKeyDialog({
  name,
  token,
  onRotated,
}: {
  name: string
  token: string
  onRotated: (masked: string) => void
}) {
  const [open, setOpen] = useState(false)
  const [value, setValue] = useState("")
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const save = useCallback(async () => {
    setSaving(true)
    setError(null)
    try {
      const res = await rotateAdminKey(token, name, value)
      onRotated(res.masked)
      setOpen(false)
      setValue("")
    } catch (e) {
      setError(e instanceof Error ? e.message : "rotation failed")
    } finally {
      setSaving(false)
    }
  }, [name, token, value, onRotated])

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          Rotate
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Rotate {name}</DialogTitle>
        </DialogHeader>
        <Textarea
          placeholder="Paste the new key value"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          rows={3}
        />
        {error && <p className="text-xs text-destructive">{error}</p>}
        <div className="flex justify-end">
          <Button onClick={save} disabled={saving || !value.trim()}>
            {saving ? "Saving…" : "Save"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

function KeysSection({ token }: { token: string }) {
  const [keys, setKeys] = useState<AdminKeyInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const reload = useCallback(async () => {
    try {
      setKeys(await fetchAdminKeys(token))
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : "failed to load keys")
    } finally {
      setLoading(false)
    }
  }, [token])

  useEffect(() => {
    reload()
  }, [reload])

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">API keys</CardTitle>
      </CardHeader>
      <CardContent>
        {loading && <p className="text-xs text-muted-foreground">Loading…</p>}
        {error && <p className="text-xs text-destructive">{error}</p>}
        {!loading && !error && (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Key</TableHead>
                <TableHead>Value</TableHead>
                <TableHead>Source</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {keys.map((k) => (
                <TableRow key={k.name}>
                  <TableCell className="font-mono text-xs">{k.name}</TableCell>
                  <TableCell className="font-mono text-xs">{k.masked ?? "not set"}</TableCell>
                  <TableCell>
                    <Badge variant="outline" className="text-[10px]">
                      {k.source}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <RotateKeyDialog
                      name={k.name}
                      token={token}
                      onRotated={(masked) =>
                        setKeys((prev) => prev.map((p) => (p.name === k.name ? { ...p, masked, source: "override" } : p)))
                      }
                    />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  )
}

function UsageRow({
  label,
  rateConfigured,
  primary,
  note,
}: {
  label: string
  rateConfigured: boolean
  primary: string
  note?: string
}) {
  return (
    <div className="flex items-center justify-between py-1.5 text-sm border-b last:border-b-0">
      <div>
        <span className="font-medium">{label}</span>
        {note && <span className="block text-xs text-muted-foreground">{note}</span>}
      </div>
      <span className="font-mono text-xs">{rateConfigured ? primary : "not configured"}</span>
    </div>
  )
}

function UsageSection({ token }: { token: string }) {
  const [usage, setUsage] = useState<AdminUsageSnapshot | null>(null)
  const [error, setError] = useState<string | null>(null)

  const reload = useCallback(async () => {
    try {
      setUsage(await fetchAdminUsage(token))
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : "failed to load usage")
    }
  }, [token])

  useEffect(() => {
    reload()
  }, [reload])

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm flex items-center gap-2">
          Usage &amp; credits
          <Button variant="ghost" size="sm" onClick={reload}>
            Refresh
          </Button>
        </CardTitle>
      </CardHeader>
      <CardContent>
        {error && <p className="text-xs text-destructive">{error}</p>}
        {usage && (
          <div>
            <UsageRow
              label="Amass"
              rateConfigured={usage.amass.rate_configured}
              primary={`${usage.amass.remaining_credits ?? "—"} credits remaining`}
              note={usage.amass.note}
            />
            <UsageRow
              label="Anthropic"
              rateConfigured={usage.anthropic.rate_configured}
              primary={`${usd(usage.anthropic.total_usd_last_7d)} last 7 days`}
              note={usage.anthropic.note}
            />
            <UsageRow
              label="Tavily"
              rateConfigured={usage.tavily.rate_configured}
              primary={`${usd(usage.tavily.usd)} · ${usage.tavily.calls} calls`}
              note={usage.tavily.source}
            />
            <UsageRow
              label="Nebius"
              rateConfigured={usage.nebius.rate_configured}
              primary={`${usd(usage.nebius.usd)} · ${usage.nebius.calls} calls`}
              note={usage.nebius.source}
            />
            <p className="pt-2 text-xs text-muted-foreground">
              Tavily/Nebius figures are estimates aggregated from {usage.runs_counted} saved run report
              {usage.runs_counted === 1 ? "" : "s"} — neither provider exposes a live balance API.
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

type HistoryRange = "24h" | "7d" | "30d"

function UsageHistorySection({ token }: { token: string }) {
  const [range, setRange] = useState<HistoryRange>("24h")
  const [history, setHistory] = useState<AdminUsageHistory | null>(null)
  const [error, setError] = useState<string | null>(null)

  const reload = useCallback(async () => {
    try {
      const opts =
        range === "24h" ? { granularity: "hour" as const, hours: 24 } : { granularity: "day" as const, days: range === "7d" ? 7 : 30 }
      setHistory(await fetchAdminUsageHistory(token, opts))
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : "failed to load usage history")
    }
  }, [token, range])

  useEffect(() => {
    reload()
  }, [reload])

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm flex items-center gap-2">
          Usage over time
          <div className="flex gap-1">
            {(["24h", "7d", "30d"] as const).map((r) => (
              <Button key={r} variant={range === r ? "secondary" : "ghost"} size="sm" onClick={() => setRange(r)}>
                {r}
              </Button>
            ))}
          </div>
        </CardTitle>
      </CardHeader>
      <CardContent>
        {error && <p className="text-xs text-destructive">{error}</p>}
        {history && <UsageHistoryChart series={history.series} granularity={history.granularity} />}
      </CardContent>
    </Card>
  )
}

export function AdminPage({ token, onSignOut }: { token: string; onSignOut?: () => void }) {
  return (
    <div className="min-h-screen bg-muted/20">
      <div className="max-w-3xl mx-auto p-4 sm:p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h1 className="text-lg font-semibold">Admin</h1>
          {onSignOut && (
            <Button variant="ghost" size="sm" onClick={onSignOut}>
              Sign out
            </Button>
          )}
        </div>
        <UsageHistorySection token={token} />
        <UsageSection token={token} />
        <KeysSection token={token} />
      </div>
    </div>
  )
}

function AdminLogin({ onSubmit }: { onSubmit: (token: string) => void }) {
  const [value, setValue] = useState("")
  return (
    <div className="min-h-screen flex items-center justify-center bg-muted/20 p-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle className="text-sm">Admin sign-in</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <Textarea
            placeholder="Paste the admin token"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            rows={2}
            autoFocus
          />
          <Button className="w-full" disabled={!value.trim()} onClick={() => onSubmit(value.trim())}>
            Continue
          </Button>
        </CardContent>
      </Card>
    </div>
  )
}

export function AdminGate() {
  const [token, setToken] = useState<string | null>(() => sessionStorage.getItem(ADMIN_TOKEN_KEY))

  if (!token) {
    return (
      <AdminLogin
        onSubmit={(t) => {
          sessionStorage.setItem(ADMIN_TOKEN_KEY, t)
          setToken(t)
        }}
      />
    )
  }

  return (
    <AdminPage
      token={token}
      onSignOut={() => {
        sessionStorage.removeItem(ADMIN_TOKEN_KEY)
        setToken(null)
      }}
    />
  )
}
