import { AuthProvider, useAuth } from '@/lib/AuthContext'
import { LoginScreen } from '@/screens/LoginScreen'
import { DatabaseScreen } from '@/screens/DatabaseScreen'

function AppContent() {
  const { session, loading } = useAuth()

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <p className="text-sm text-[var(--muted)]">Chargement…</p>
      </div>
    )
  }

  if (!session) {
    return <LoginScreen />
  }

  return <DatabaseScreen />
}

export default function App() {
  return (
    <AuthProvider>
      <AppContent />
    </AuthProvider>
  )
}
