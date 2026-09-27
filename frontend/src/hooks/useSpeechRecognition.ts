import { useCallback, useEffect, useRef, useState } from "react"

// The Web Speech API isn't in TypeScript's DOM lib; only the parts used here.
interface RecognitionResult {
  isFinal: boolean
  0: { transcript: string }
}
interface RecognitionEvent {
  resultIndex: number
  results: ArrayLike<RecognitionResult>
}
interface Recognition {
  lang: string
  continuous: boolean
  interimResults: boolean
  onresult: ((e: RecognitionEvent) => void) | null
  onerror: ((e: { error: string }) => void) | null
  onend: (() => void) | null
  start(): void
  stop(): void
}
type RecognitionCtor = new () => Recognition

function recognitionCtor(): RecognitionCtor | undefined {
  const w = window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor }
  return w.SpeechRecognition ?? w.webkitSpeechRecognition
}

/** Browser speech-to-text (Chrome/Edge/Safari). `transcript` holds the
 * finalized text and stays editable by the caller via `setTranscript`;
 * `interim` is the not-yet-final tail while speaking. Chrome ends a session
 * on its own after a pause, so it is restarted until `stop()` is called. */
export function useSpeechRecognition(lang: string) {
  const supported = recognitionCtor() !== undefined
  const [listening, setListening] = useState(false)
  const [transcript, setTranscript] = useState("")
  const [interim, setInterim] = useState("")
  const [error, setError] = useState<string | null>(null)
  const recRef = useRef<Recognition | null>(null)
  const wantRef = useRef(false)

  const stop = useCallback(() => {
    wantRef.current = false
    recRef.current?.stop()
  }, [])

  const start = useCallback(() => {
    const Ctor = recognitionCtor()
    if (!Ctor) return
    recRef.current?.stop()
    const rec = new Ctor()
    rec.lang = lang
    rec.continuous = true
    rec.interimResults = true
    rec.onresult = (e) => {
      let finalText = ""
      let pending = ""
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i]
        if (r.isFinal) finalText += r[0].transcript
        else pending += r[0].transcript
      }
      if (finalText) setTranscript((t) => (t ? `${t} ${finalText.trim()}` : finalText.trim()))
      setInterim(pending)
    }
    rec.onerror = (e) => {
      if (e.error === "no-speech" || e.error === "aborted") return
      setError(
        e.error === "not-allowed"
          ? "Kein Zugriff aufs Mikrofon — bitte im Browser erlauben."
          : `Spracherkennung: ${e.error}`
      )
      wantRef.current = false
    }
    rec.onend = () => {
      setInterim("")
      if (wantRef.current) {
        try {
          rec.start()
          return
        } catch {
          // fall through to stopped
        }
      }
      setListening(false)
    }
    recRef.current = rec
    wantRef.current = true
    setError(null)
    setListening(true)
    rec.start()
  }, [lang])

  useEffect(() => () => {
    wantRef.current = false
    recRef.current?.stop()
  }, [])

  return { supported, listening, transcript, setTranscript, interim, error, start, stop }
}
