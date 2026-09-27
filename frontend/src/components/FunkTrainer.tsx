import { useEffect, useState } from "react"
import { ArrowLeftIcon, CheckCircle2Icon, CircleAlertIcon, MicIcon, ShuffleIcon, SquareIcon, XCircleIcon } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Textarea } from "@/components/ui/textarea"
import { TooltipProvider } from "@/components/ui/tooltip"
import { SettingsDialog } from "@/components/SettingsDialog"
import { useApiKeys } from "@/hooks/useApiKeys"
import { useSpeechRecognition } from "@/hooks/useSpeechRecognition"
import { fetchFunkTasks, gradeFunkTask, type FunkGrade, type FunkShip, type FunkTask } from "@/lib/api"
import { hasUsableLlmKey, loadApiKeys } from "@/store/apiKeysStore"
import { openSettingsDialog } from "@/store/settingsDialogStore"
import { getModelPrefs } from "@/store/modelStore"

const LANGS = [
  { id: "en-GB", label: "Englisch (UK)" },
  { id: "en-US", label: "Englisch (US)" },
  { id: "de-DE", label: "Deutsch" },
]

function ShipLine({ label, ship }: { label: string; ship: FunkShip }) {
  return (
    <div className="text-sm">
      <span className="text-muted-foreground">{label}: </span>
      <span className="font-semibold">{ship.name}</span> · Rufzeichen{" "}
      <span className="font-mono">{ship.call_sign}</span> · MMSI{" "}
      <span className="font-mono">{ship.mmsi}</span>
    </div>
  )
}

const STATUS_ICON = {
  ok: <CheckCircle2Icon className="size-4 text-green-600 shrink-0 mt-0.5" />,
  fehlerhaft: <CircleAlertIcon className="size-4 text-amber-600 shrink-0 mt-0.5" />,
  fehlt: <XCircleIcon className="size-4 text-red-600 shrink-0 mt-0.5" />,
}

function GradeView({ grade }: { grade: FunkGrade }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-3 flex-wrap">
          <Badge variant={grade.passed ? "default" : "destructive"} className="text-sm">
            {grade.passed ? "Bestanden" : "Nicht bestanden"}
          </Badge>
          <span className="text-2xl tabular-nums">{grade.score}/100</span>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-5">
        {grade.summary && <p>{grade.summary}</p>}
        <ul className="space-y-2">
          {grade.checklist.map((c, i) => (
            <li key={i} className="flex gap-2 text-sm">
              {STATUS_ICON[c.status]}
              <div>
                <span className="font-medium">{c.item}</span>
                {c.comment && <span className="text-muted-foreground"> — {c.comment}</span>}
              </div>
            </li>
          ))}
        </ul>
        {grade.tips.length > 0 && (
          <div>
            <h3 className="font-semibold mb-1">Tipps</h3>
            <ul className="list-disc pl-5 text-sm space-y-1">
              {grade.tips.map((t, i) => (
                <li key={i}>{t}</li>
              ))}
            </ul>
          </div>
        )}
        <details>
          <summary className="cursor-pointer font-semibold">Musterlösung</summary>
          <pre className="mt-2 whitespace-pre-wrap rounded-md bg-muted p-3 text-sm font-mono">{grade.reference}</pre>
        </details>
        {grade.model && <p className="text-xs text-muted-foreground">Bewertet von {grade.model}</p>}
      </CardContent>
    </Card>
  )
}

export function FunkTrainer() {
  const { keys } = useApiKeys()
  const [tasks, setTasks] = useState<FunkTask[]>([])
  const [loadError, setLoadError] = useState<string | null>(null)
  const [taskId, setTaskId] = useState("")
  const [lang, setLang] = useState("en-GB")
  const speech = useSpeechRecognition(lang)
  const [grading, setGrading] = useState(false)
  const [grade, setGrade] = useState<FunkGrade | null>(null)
  const [gradeError, setGradeError] = useState<string | null>(null)

  useEffect(() => {
    fetchFunkTasks()
      .then((t) => {
        setTasks(t)
        if (t.length) setTaskId(t[Math.floor(Math.random() * t.length)].id)
      })
      .catch((e: Error) => setLoadError(e.message))
  }, [])

  const task = tasks.find((t) => t.id === taskId)

  function reset(nextId: string) {
    speech.stop()
    speech.setTranscript("")
    setGrade(null)
    setGradeError(null)
    setTaskId(nextId)
  }

  function randomTask() {
    const others = tasks.filter((t) => t.id !== taskId)
    if (others.length) reset(others[Math.floor(Math.random() * others.length)].id)
  }

  async function handleGrade() {
    if (!task) return
    if (!hasUsableLlmKey(keys)) {
      openSettingsDialog("OPENROUTER_API_KEY")
      return
    }
    speech.stop()
    setGrading(true)
    setGradeError(null)
    setGrade(null)
    try {
      setGrade(await gradeFunkTask(task.id, speech.transcript, { ...loadApiKeys(), ...getModelPrefs() }))
    } catch (e) {
      setGradeError((e as Error).message)
    } finally {
      setGrading(false)
    }
  }

  const categories = [...new Set(tasks.map((t) => t.category))]

  return (
    <TooltipProvider>
      <div className="mx-auto max-w-3xl px-4 py-6 space-y-6">
        <div className="pb-4 border-b flex items-start justify-between gap-4 flex-wrap">
          <div className="flex items-start gap-3">
            <Button variant="outline" size="icon-lg" asChild title="Zurück zur App">
              <a href="#">
                <ArrowLeftIcon className="size-4" />
              </a>
            </Button>
            <div>
              <h1 className="text-2xl font-bold tracking-tight">SRC Funktrainer</h1>
              <p className="text-muted-foreground mt-1">
                Aufgabe lesen, Funkspruch einsprechen, vom LLM bewerten lassen.
              </p>
            </div>
          </div>
          <SettingsDialog />
        </div>

        {loadError && <p className="text-destructive">{loadError}</p>}
        {!hasUsableLlmKey(keys) && (
          <p className="text-sm rounded-md border p-3">
            Für die Bewertung wird ein LLM-Key gebraucht (kostenloser OpenRouter-Key oder Anthropic-Key).{" "}
            <button className="underline" onClick={() => openSettingsDialog("OPENROUTER_API_KEY")}>
              In den Einstellungen hinterlegen
            </button>
          </p>
        )}

        <div className="flex gap-2 flex-wrap items-center">
          <select
            className="h-9 rounded-md border bg-background px-3 text-sm flex-1 min-w-0"
            value={taskId}
            onChange={(e) => reset(e.target.value)}
          >
            {categories.map((cat) => (
              <optgroup key={cat} label={cat}>
                {tasks
                  .filter((t) => t.category === cat)
                  .map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.title}
                    </option>
                  ))}
              </optgroup>
            ))}
          </select>
          <Button variant="outline" onClick={randomTask} disabled={tasks.length < 2}>
            <ShuffleIcon /> Zufällig
          </Button>
        </div>

        {task && (
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 flex-wrap">
                <Badge variant="secondary">{task.category}</Badge>
                {task.title}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <p>{task.situation}</p>
              <ShipLine label="Eigenes Schiff" ship={task.own_ship} />
              {task.other_ship && <ShipLine label="Anderes Schiff" ship={task.other_ship} />}
            </CardContent>
          </Card>
        )}

        {task && (
          <div className="space-y-3">
            <div className="flex gap-2 flex-wrap items-center">
              {speech.listening ? (
                <Button variant="destructive" size="lg" onClick={speech.stop}>
                  <SquareIcon /> Aufnahme beenden
                </Button>
              ) : (
                <Button size="lg" onClick={speech.start} disabled={!speech.supported || grading}>
                  <MicIcon /> {speech.transcript ? "Weiter sprechen" : "Sprechen"}
                </Button>
              )}
              <select
                className="h-10 rounded-md border bg-background px-3 text-sm"
                value={lang}
                onChange={(e) => setLang(e.target.value)}
                disabled={speech.listening}
                title="Sprache der Spracherkennung"
              >
                {LANGS.map((l) => (
                  <option key={l.id} value={l.id}>
                    {l.label}
                  </option>
                ))}
              </select>
              {speech.transcript && !speech.listening && (
                <Button variant="ghost" onClick={() => speech.setTranscript("")}>
                  Löschen
                </Button>
              )}
              {speech.listening && <span className="text-sm text-red-600 animate-pulse">● Aufnahme läuft</span>}
            </div>
            {!speech.supported && (
              <p className="text-sm text-muted-foreground">
                Dieser Browser unterstützt keine Spracherkennung (am besten Chrome oder Edge). Du kannst den Funkspruch
                unten auch eintippen.
              </p>
            )}
            {speech.error && <p className="text-sm text-destructive">{speech.error}</p>}
            <Textarea
              rows={8}
              placeholder="Hier erscheint dein gesprochener Funkspruch. Erkennungsfehler kannst du korrigieren."
              value={speech.transcript + (speech.interim ? ` ${speech.interim}` : "")}
              onChange={(e) => speech.setTranscript(e.target.value)}
              readOnly={speech.listening}
              className="font-mono"
            />
            <Button onClick={handleGrade} disabled={grading || speech.listening || !speech.transcript.trim()}>
              {grading ? "Wird bewertet…" : "Bewerten"}
            </Button>
            {gradeError && <p className="text-sm text-destructive">{gradeError}</p>}
          </div>
        )}

        {grade && <GradeView grade={grade} />}
      </div>
    </TooltipProvider>
  )
}
