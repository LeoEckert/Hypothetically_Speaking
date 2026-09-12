import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { EvalPreview } from './dev/EvalPreview.tsx'

// `?evalpreview` renders the evaluation diff view against a saved fixture,
// with no backend and no run required. Dev builds only — the constant folds
// to false in production, so the preview and its fixture drop out.
const previewEval =
  import.meta.env.DEV && new URLSearchParams(window.location.search).has('evalpreview')

createRoot(document.getElementById('root')!).render(
  <StrictMode>{previewEval ? <EvalPreview /> : <App />}</StrictMode>,
)
