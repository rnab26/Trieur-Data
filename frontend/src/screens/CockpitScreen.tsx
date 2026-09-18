import { useCallback, useEffect, useMemo, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { useAuth } from '@/lib/AuthContext'
import { useOrgs } from '@/lib/useAccount'
import {
  ApiError,
  CHANTIER_PRIORITIES,
  createChantier,
  createSection,
  listChantiers,
  listSections,
  type Chantier,
  type ChantierPriority,
  type ChantierStatus,
  type Section,
} from '@/lib/api'
import { ChantierCard, STATUT_LABELS } from './ChantierCard'

const SANS_SECTION = '— Sans section —'
const NOUVELLE_SECTION = '+ Nouvelle section…'

// Ordre d'affichage : ce qui a besoin de toi d'abord, ce qui est clos
// en dernier -- même règle que views/tab_cockpit.py.
const STATUT_ACTIFS: ChantierStatus[] = ['attente_retour', 'en_cours', 'a_faire']
const STATUT_ARCHIVES: ChantierStatus[] = ['termine', 'abandonne']

function isToday(iso: string | null | undefined): boolean {
  if (!iso) return false
  const d = new Date(iso)
  const now = new Date()
  return (
    d.getUTCFullYear() === now.getUTCFullYear() &&
    d.getUTCMonth() === now.getUTCMonth() &&
    d.getUTCDate() === now.getUTCDate()
  )
}

/** Le résumé "où j'en suis" -- quatre nombres, jamais cinq : un
 * chantier "abandonne" ne compte dans AUCUNE colonne plutôt que de
 * forcer une case qui mentirait sur son vrai état (même règle que
 * views/tab_cockpit.py:_render_ou_jen_suis). */
function OuJenSuis({ chantiers }: { chantiers: Chantier[] }) {
  const bouge = chantiers.filter((c) => c.status === 'en_cours').length
  const livre = chantiers.filter((c) => c.status === 'termine' && isToday(c.updated_at)).length
  const pourToi = chantiers.filter((c) => c.status === 'attente_retour').length
  const dort = chantiers.filter((c) => c.status === 'a_faire').length

  const tiles: { label: string; value: number; accent?: boolean }[] = [
    { label: 'Bouge', value: bouge },
    { label: "Livré aujourd'hui", value: livre },
    { label: 'Pour toi', value: pourToi, accent: pourToi > 0 },
    { label: 'Dort', value: dort },
  ]

  return (
    <Card>
      <CardContent className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {tiles.map((t) => (
          <div key={t.label} className="flex flex-col gap-0.5">
            <span className="text-xs text-[var(--muted)]">{t.label}</span>
            <span className={'text-2xl font-semibold ' + (t.accent ? 'text-[var(--danger)]' : 'text-[var(--foreground)]')}>
              {t.value}
            </span>
          </div>
        ))}
      </CardContent>
    </Card>
  )
}

export function CockpitScreen() {
  const { session, signOut } = useAuth()
  const { orgs, orgsError, orgId, setOrgId } = useOrgs()

  const [chantiers, setChantiers] = useState<Chantier[] | null>(null)
  const [chantiersError, setChantiersError] = useState<string | null>(null)
  const [chantiersLoading, setChantiersLoading] = useState(false)

  const [sections, setSections] = useState<Section[]>([])
  const [sectionsError, setSectionsError] = useState<string | null>(null)

  const [refreshKey, setRefreshKey] = useState(0)

  const [recherche, setRecherche] = useState('')
  const [filtreStatut, setFiltreStatut] = useState<'tous' | ChantierStatus>('tous')

  const [archivesOuvertes, setArchivesOuvertes] = useState(false)

  const [formOpen, setFormOpen] = useState(false)
  const [newTitle, setNewTitle] = useState('')
  const [newPriority, setNewPriority] = useState<ChantierPriority>('normale')
  const [newSectionChoice, setNewSectionChoice] = useState(SANS_SECTION)
  const [newSectionName, setNewSectionName] = useState('')
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)

  const [sectionFormOpen, setSectionFormOpen] = useState(false)
  const [sectionName, setSectionName] = useState('')
  const [creatingSection, setCreatingSection] = useState(false)
  const [sectionCreateError, setSectionCreateError] = useState<string | null>(null)

  const fetchAll = useCallback((org: string) => {
    setChantiersLoading(true)
    setChantiersError(null)
    listChantiers(org)
      .then(setChantiers)
      .catch((err: unknown) => setChantiersError(err instanceof ApiError ? err.message : 'Erreur inconnue.'))
      .finally(() => setChantiersLoading(false))

    setSectionsError(null)
    listSections(org)
      .then(setSections)
      .catch((err: unknown) => setSectionsError(err instanceof ApiError ? err.message : 'Erreur inconnue.'))
  }, [])

  useEffect(() => {
    if (!orgId) return
    fetchAll(orgId)
  }, [orgId, refreshKey, fetchAll])

  function refresh() {
    setRefreshKey((k) => k + 1)
  }

  async function handleCreateChantier(e: React.FormEvent) {
    e.preventDefault()
    if (!orgId || !newTitle.trim()) return
    setCreating(true)
    setCreateError(null)
    try {
      let theme: string | null = null
      if (newSectionChoice === NOUVELLE_SECTION && newSectionName.trim()) {
        await createSection(orgId, newSectionName.trim())
        theme = newSectionName.trim()
      } else if (newSectionChoice !== SANS_SECTION) {
        theme = newSectionChoice
      }
      await createChantier(orgId, { title: newTitle.trim(), priority: newPriority, theme })
      setNewTitle('')
      setNewPriority('normale')
      setNewSectionChoice(SANS_SECTION)
      setNewSectionName('')
      setFormOpen(false)
      refresh()
    } catch (err) {
      setCreateError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setCreating(false)
    }
  }

  async function handleCreateSection(e: React.FormEvent) {
    e.preventDefault()
    if (!orgId || !sectionName.trim()) return
    setCreatingSection(true)
    setSectionCreateError(null)
    try {
      await createSection(orgId, sectionName.trim())
      setSectionName('')
      refresh()
    } catch (err) {
      setSectionCreateError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setCreatingSection(false)
    }
  }

  const correspond = useCallback(
    (ch: Chantier) => {
      if (recherche.trim() && !ch.title.toLowerCase().includes(recherche.trim().toLowerCase())) return false
      if (filtreStatut !== 'tous' && ch.status !== filtreStatut) return false
      return true
    },
    [recherche, filtreStatut],
  )

  const byStatus = useMemo(() => {
    const map: Record<string, Chantier[]> = {}
    for (const ch of chantiers ?? []) {
      map[ch.status] = map[ch.status] ?? []
      map[ch.status].push(ch)
    }
    return map
  }, [chantiers])

  const actifs = useMemo(
    () => STATUT_ACTIFS.flatMap((s) => byStatus[s] ?? []),
    [byStatus],
  )
  const actifsVisibles = useMemo(() => actifs.filter(correspond), [actifs, correspond])

  // Groupés par section déclarée, dans l'ordre choisi, puis les
  // chantiers dont le thème ne correspond à aucune section déclarée
  // sous "À classer" -- même règle que views/tab_cockpit.py.
  const parTheme = useMemo(() => {
    const map = new Map<string | null, Chantier[]>()
    for (const ch of actifsVisibles) {
      const key = ch.theme ?? null
      map.set(key, [...(map.get(key) ?? []), ch])
    }
    return map
  }, [actifsVisibles])

  const groupes = useMemo(() => {
    const restant = new Map(parTheme)
    const out: { nom: string | null; chantiers: Chantier[] }[] = []
    for (const s of sections) {
      const chs = restant.get(s.nom) ?? []
      restant.delete(s.nom)
      if (chs.length === 0 && (recherche.trim() || filtreStatut !== 'tous')) continue
      out.push({ nom: s.nom, chantiers: chs })
    }
    const aClasser = [...restant.values()].flat()
    if (aClasser.length > 0) out.push({ nom: null, chantiers: aClasser })
    return out
  }, [parTheme, sections, recherche, filtreStatut])

  const archives = useMemo(() => STATUT_ARCHIVES.flatMap((s) => byStatus[s] ?? []), [byStatus])

  return (
    <div className="cockpit-dark">
      <div className="mx-auto max-w-6xl p-4">
        <header className="mb-4 flex flex-wrap items-center justify-between gap-2">
          <h1 className="text-lg font-semibold">Cockpit</h1>
          <div className="flex items-center gap-2 text-sm text-[var(--muted)]">
            <span>{session?.user.email}</span>
            <Button variant="secondary" onClick={() => void signOut()}>
              Se déconnecter
            </Button>
          </div>
        </header>

        {orgsError && (
          <p className="mb-4 text-sm text-[var(--danger)]">
            Impossible de charger les environnements : {orgsError}
          </p>
        )}

        {orgs && orgs.length === 0 && !orgsError && (
          <p className="text-sm text-[var(--muted)]">
            Ton compte n'a accès à aucun environnement pour l'instant.
          </p>
        )}

        {orgs && orgs.length > 0 && (
          <div className="mb-4 flex flex-wrap items-center gap-3">
            <label htmlFor="cockpit-org-switcher" className="text-sm text-[var(--muted)]">
              Environnement
            </label>
            <select
              id="cockpit-org-switcher"
              className="rounded-md border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-sm"
              value={orgId ?? ''}
              onChange={(e) => setOrgId(e.target.value)}
            >
              {orgs.map((org) => (
                <option key={org.id} value={org.id}>
                  {org.name}
                </option>
              ))}
            </select>
          </div>
        )}

        {!orgId ? null : chantiersError ? (
          <p className="text-sm text-[var(--danger)]">
            Erreur : {chantiersError}. Le Cockpit est réservé aux administrateurs.
          </p>
        ) : chantiersLoading && chantiers === null ? (
          <p className="text-sm text-[var(--muted)]">Chargement…</p>
        ) : (
          <div className="flex flex-col gap-4">
            <OuJenSuis chantiers={chantiers ?? []} />

            <Card>
              <CardContent className="flex flex-col gap-2">
                <button
                  type="button"
                  className="self-start text-sm font-medium text-[var(--primary)]"
                  onClick={() => setFormOpen((v) => !v)}
                >
                  {formOpen ? '▾ Nouveau chantier' : '▸ Nouveau chantier'}
                </button>
                {formOpen && (
                  <form onSubmit={(e) => void handleCreateChantier(e)} className="flex flex-col gap-2">
                    <Input
                      placeholder="Titre du chantier / de la demande"
                      value={newTitle}
                      onChange={(e) => setNewTitle(e.target.value)}
                    />
                    <div className="flex flex-wrap gap-2">
                      <select
                        className="rounded-md border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-sm"
                        value={newPriority}
                        onChange={(e) => setNewPriority(e.target.value as ChantierPriority)}
                      >
                        {CHANTIER_PRIORITIES.map((p) => (
                          <option key={p} value={p}>
                            Priorité {p}
                          </option>
                        ))}
                      </select>
                      <select
                        className="min-w-[180px] flex-1 rounded-md border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-sm"
                        value={newSectionChoice}
                        onChange={(e) => setNewSectionChoice(e.target.value)}
                      >
                        <option value={SANS_SECTION}>{SANS_SECTION}</option>
                        {sections.map((s) => (
                          <option key={s.id} value={s.nom}>
                            {s.nom}
                          </option>
                        ))}
                        <option value={NOUVELLE_SECTION}>{NOUVELLE_SECTION}</option>
                      </select>
                    </div>
                    {newSectionChoice === NOUVELLE_SECTION && (
                      <Input
                        placeholder="Nom de la nouvelle section"
                        value={newSectionName}
                        onChange={(e) => setNewSectionName(e.target.value)}
                      />
                    )}
                    {createError && <p className="text-sm text-[var(--danger)]">{createError}</p>}
                    <Button type="submit" disabled={creating || !newTitle.trim()}>
                      {creating ? 'Création…' : 'Créer'}
                    </Button>
                  </form>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardContent className="flex flex-col gap-2">
                <button
                  type="button"
                  className="self-start text-sm font-medium text-[var(--primary)]"
                  onClick={() => setSectionFormOpen((v) => !v)}
                >
                  {sectionFormOpen ? '▾ Sections' : '▸ Sections'}
                </button>
                {sectionFormOpen && (
                  <div className="flex flex-col gap-2">
                    {sectionsError && <p className="text-sm text-[var(--danger)]">{sectionsError}</p>}
                    {sections.length > 0 ? (
                      <ul className="text-sm text-[var(--muted)]">
                        {sections.map((s) => (
                          <li key={s.id}>• {s.nom}</li>
                        ))}
                      </ul>
                    ) : (
                      <p className="text-sm text-[var(--muted)]">Aucune section déclarée pour l'instant.</p>
                    )}
                    <form onSubmit={(e) => void handleCreateSection(e)} className="flex gap-2">
                      <Input
                        placeholder="Ex. Export, Imports, Interface…"
                        value={sectionName}
                        onChange={(e) => setSectionName(e.target.value)}
                      />
                      <Button type="submit" variant="secondary" disabled={creatingSection || !sectionName.trim()}>
                        {creatingSection ? '…' : 'Créer la section'}
                      </Button>
                    </form>
                    {sectionCreateError && (
                      <p className="text-sm text-[var(--danger)]">{sectionCreateError}</p>
                    )}
                  </div>
                )}
              </CardContent>
            </Card>

            {(chantiers ?? []).length === 0 && sections.length === 0 && (
              <p className="text-sm text-[var(--muted)]">Aucun chantier pour cet environnement pour l'instant.</p>
            )}

            {((chantiers ?? []).length > 0 || sections.length > 0) && (
              <div className="flex flex-wrap items-center gap-2">
                <Input
                  className="max-w-xs"
                  placeholder="Chercher un chantier…"
                  value={recherche}
                  onChange={(e) => setRecherche(e.target.value)}
                />
                <select
                  className="rounded-md border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-sm"
                  value={filtreStatut}
                  onChange={(e) => setFiltreStatut(e.target.value as 'tous' | ChantierStatus)}
                >
                  <option value="tous">Tous les statuts actifs</option>
                  {STATUT_ACTIFS.map((s) => (
                    <option key={s} value={s}>
                      {STATUT_LABELS[s]}
                    </option>
                  ))}
                </select>
              </div>
            )}

            {actifsVisibles.length === 0 && actifs.length > 0 && (
              <p className="text-sm text-[var(--muted)]">Aucun chantier actif ne correspond à cette recherche/ce filtre.</p>
            )}
            {actifs.length === 0 && sections.length === 0 && chantiers && chantiers.length > 0 && (
              <p className="text-sm text-[var(--muted)]">Aucun chantier actif — tout est terminé ou abandonné.</p>
            )}

            {groupes.map((groupe) => (
              <div key={groupe.nom ?? '__a_classer__'} className="flex flex-col gap-2">
                <h2 className="text-sm font-semibold text-[var(--muted)]">
                  {groupe.nom ?? (sections.length > 0 ? 'À classer' : 'Chantiers')}
                </h2>
                {groupe.chantiers.length === 0 ? (
                  <p className="text-xs text-[var(--muted)]">Aucun chantier actif dans cette section.</p>
                ) : (
                  groupe.chantiers.map((ch) => (
                    <ChantierCard key={ch.id} orgId={orgId} chantier={ch} onStatusChanged={refresh} />
                  ))
                )}
              </div>
            ))}

            {archives.length > 0 && (
              <Card>
                <CardContent className="flex flex-col gap-2">
                  <button
                    type="button"
                    className="self-start text-sm font-medium text-[var(--muted)]"
                    onClick={() => setArchivesOuvertes((v) => !v)}
                  >
                    {archivesOuvertes ? '▾' : '▸'} Chantiers clos ({archives.length})
                  </button>
                  {archivesOuvertes && (
                    <div className="flex flex-col gap-2">
                      {archives.map((ch) => (
                        <ChantierCard key={ch.id} orgId={orgId} chantier={ch} compact onStatusChanged={refresh} />
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
