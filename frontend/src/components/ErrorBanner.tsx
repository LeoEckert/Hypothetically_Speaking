import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"

export function ErrorBanner({ error }: { error: string }) {
  return (
    <Alert variant="destructive" className="my-2">
      <AlertTitle>Error</AlertTitle>
      <AlertDescription>{error}</AlertDescription>
    </Alert>
  )
}
