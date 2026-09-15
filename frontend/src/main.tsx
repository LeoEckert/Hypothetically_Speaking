import { Analytics } from '@vercel/analytics/react'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { AdminGate } from './components/AdminPage.tsx'
import { EvalPreview } from './dev/EvalPreview.tsx'

// Admin dashboard gate: reached via the `#admin` hash fragment (a login form
// prompts for the token there), or `#token=...` as a shortcut that auto-fills
// and stores the token then rewrites the URL to plain `#admin` — so a
// bookmarked/reloaded admin tab never has the secret sitting in its URL.
// Always a fragment, never a query string: fragments are never sent to any
// server, so this avoids the token ever reaching Vercel/CDN access logs.
const hashMatch = /^#token=(.+)$/.exec(window.location.hash)
if (hashMatch) {
  sessionStorage.setItem('admin_token', decodeURIComponent(hashMatch[1]))
  window.history.replaceState(null, '', window.location.pathname + window.location.search + '#admin')
}
const wantsAdmin = hashMatch !== null || window.location.hash === '#admin'

// `?evalpreview` renders the evaluation diff view against a saved fixture,
// with no backend and no run required. Dev builds only — the constant folds
// to false in production, so the preview and its fixture drop out.
const previewEval =
  import.meta.env.DEV && new URLSearchParams(window.location.search).has('evalpreview')

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {wantsAdmin ? <AdminGate /> : previewEval ? <EvalPreview /> : <App />}
    <Analytics />
  </StrictMode>,
)
