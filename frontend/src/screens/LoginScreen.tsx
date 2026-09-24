import { useEffect, useState, type FormEvent } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { ThemeToggle } from '@/components/ThemeToggle'
import { useAuth } from '@/lib/AuthContext'

export function LoginScreen() {
  const { signIn } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  // Posé par lib/api.ts:handleUnauthorized (401 global -- jeton révoqué,
  // compte sans profil...) juste avant la déconnexion forcée qui ramène
  // ici. Sans ce message, l'utilisateur revoit un simple formulaire de
  // connexion sans comprendre pourquoi il a été déconnecté.
  const [sessionExpired, setSessionExpired] = useState(false)

  useEffect(() => {
    try {
      if (sessionStorage.getItem('td_session_expired')) {
        setSessionExpired(true)
        sessionStorage.removeItem('td_session_expired')
      }
    } catch {
      // stockage indisponible -- pas bloquant, le message reste absent
    }
  }, [])

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    const { error: signInError } = await signIn(email, password)
    setSubmitting(false)
    if (signInError) {
      setError(`Connexion refusée : ${signInError}`)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="fixed right-4 top-4">
        <ThemeToggle />
      </div>
      <Card className="w-full max-w-sm">
        <CardHeader>
          <h1 className="text-lg font-semibold">Trieur de Data</h1>
        </CardHeader>
        <CardContent>
          {sessionExpired && (
            <p className="mb-3 rounded-md shadow-[var(--ring-card)] bg-[var(--card)] px-3 py-2 text-sm text-[var(--foreground)]">
              Ta session a expiré ou n'est plus valide. Reconnecte-toi.
            </p>
          )}
          <form onSubmit={handleSubmit} className="flex flex-col gap-3">
            <div>
              <label htmlFor="email" className="mb-1 block text-sm text-[var(--muted)]">
                Email
              </label>
              <Input
                id="email"
                type="email"
                autoComplete="username"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>
            <div>
              <label htmlFor="password" className="mb-1 block text-sm text-[var(--muted)]">
                Mot de passe
              </label>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>
            {error && <p className="text-sm text-[var(--danger)]">{error}</p>}
            <Button type="submit" disabled={submitting}>
              {submitting ? 'Connexion…' : 'Se connecter'}
            </Button>
            <p className="text-xs text-[var(--muted)]">
              Pas encore de compte ? Demande une invitation à l'administrateur.
            </p>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
