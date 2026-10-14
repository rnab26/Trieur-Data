import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import {
  ApiError,
  FILTER_OPERATORS,
  leadsAbandonner,
  leadsAnnuler,
  leadsApercu,
  leadsComptage,
  leadsCompter,
  leadsCreerExport,
  leadsDoublons,
  leadsImporter,
  leadsJob,
  leadsJobs,
  leadsRegler,
  leadsReprendreExport,
  leadsSources,
  leadsUrlTelechargement,
  type FilterOperator,
  type LeadsApercu,
  type LeadsCurseur,
  type LeadsDept,
  type LeadsJob,
  type LeadsSelection,
  type LeadsSource,
  type LeadsStatut,
} from '@/lib/api'
import { cn } from '@/lib/utils'

// Page dédiée à la base Leads (50 à 60 millions de lignes) : on ne cherche jamais « dans tout » à la main.
// Un aperçu de quelques centaines de lignes (taille = réglage du serveur), des comptes exacts instantanés,
// un export en flux. Tout ce qui est long (import, export, comptage exact) est une tâche suivie ici.

type Onglet = 'export' | 'import' | 'sources'

// Colonnes filtrables côté base (mêmes noms que api/leads.py)
const COLONNES_FILTRE: [string, string][] = [
  ['nom', 'Nom'],
  ['prenom', 'Prénom'],
  ['email', 'Email'],
  ['ville', 'Ville'],
  ['cp', 'Code postal'],
  ['adresse', 'Adresse'],
]

const COLONNES_APERCU: [string, string][] = [
  ['dept', 'Dép.'],
  ['source', 'Source'],
  ['nom', 'Nom'],
  ['prenom', 'Prénom'],
  ['email', 'Email'],
  ['tel_mobile', 'Mobile'],
  ['tel_fixe', 'Fixe'],
  ['cp', 'CP'],
  ['ville', 'Ville'],
  ['adresse', 'Adresse'],
  ['naissance', 'Naissance'],
]

// Intervalles de rafraîchissement des tâches en cours (ms) -- pas de valeur cachée dans le code
const INTERVALLE_TACHE_MS = 2000
const DELAI_SAISIE_MS = 400
const DUREE_MESSAGE_MS = 5000
const FILTRES_MAX = 5

const LIBELLE_STATUT: Record<LeadsStatut, string> = { bonne: 'Bonne', a_verifier: 'À vérifier', mauvaise: 'Mauvaise' }
const COULEUR_STATUT: Record<LeadsStatut, string> = {
  bonne: 'bg-green-600 text-white',
  a_verifier: 'bg-amber-500 text-white',
  mauvaise: 'bg-red-600 text-white',
}

function nombre(n: number | null | undefined): string {
  return n == null ? '—' : n.toLocaleString('fr-FR')
}

function messageErreur(e: unknown): string {
  return e instanceof ApiError ? e.message : 'Erreur inattendue. Réessaie.'
}

type Notice = { ok: boolean; texte: string } | null

function useNotice() {
  const [notice, setNotice] = useState<Notice>(null)
  const minuteur = useRef<ReturnType<typeof setTimeout> | null>(null)
  const montrer = useCallback((ok: boolean, texte: string) => {
    setNotice({ ok, texte })
    if (minuteur.current) clearTimeout(minuteur.current)
    minuteur.current = setTimeout(() => setNotice(null), DUREE_MESSAGE_MS)
  }, [])
  useEffect(
    () => () => {
      if (minuteur.current) clearTimeout(minuteur.current)
    },
    [],
  )
  return { notice, montrer }
}

function Message({ notice }: { notice: Notice }) {
  if (!notice) return null
  return (
    <p
      role="status"
      className={cn(
        'rounded-lg px-3 py-2 text-sm',
        notice.ok ? 'bg-green-600/10 text-green-700 dark:text-green-400' : 'bg-red-600/10 text-red-700 dark:text-red-400',
      )}
    >
      {notice.texte}
    </p>
  )
}

function Erreur({ texte, onRetry }: { texte: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex items-center justify-between gap-3 rounded-lg bg-red-600/10 px-3 py-2 text-sm text-red-700 dark:text-red-400">
      <span>{texte}</span>
      {onRetry && (
        <Button variant="secondary" onClick={onRetry} className="shrink-0">
          Réessayer
        </Button>
      )}
    </div>
  )
}

function Barre({ lues, total }: { lues: number; total: number | null }) {
  const pct = total && total > 0 ? Math.min(100, Math.round((lues / total) * 100)) : null
  return (
    <div className="space-y-1">
      <div className="h-2 w-full overflow-hidden rounded-full bg-[var(--muted-bg)]">
        <div
          className={cn('h-full rounded-full bg-[var(--primary)]', pct == null && 'w-1/3 animate-pulse')}
          style={pct == null ? undefined : { width: `${pct}%` }}
        />
      </div>
      <p className="text-xs text-[var(--muted)]">
        {nombre(lues)}
        {total ? ` sur ${nombre(total)}` : ''} lignes{pct != null ? ` · ${pct} %` : ''}
      </p>
    </div>
  )
}

// Suit une tâche : relit son état tant qu'elle est en cours.
function useTache(id: string | null) {
  const [tache, setTache] = useState<LeadsJob | null>(null)
  const [erreur, setErreur] = useState<string | null>(null)
  useEffect(() => {
    if (!id) {
      setTache(null)
      return
    }
    let stop = false
    let t: ReturnType<typeof setTimeout>
    const boucle = async () => {
      try {
        const j = await leadsJob(id)
        if (stop) return
        setTache(j)
        setErreur(null)
        if (j.status === 'en_cours' && !j.silencieuse) t = setTimeout(boucle, INTERVALLE_TACHE_MS)
      } catch (e) {
        if (stop) return
        setErreur(messageErreur(e))
        t = setTimeout(boucle, INTERVALLE_TACHE_MS * 3)
      }
    }
    void boucle()
    return () => {
      stop = true
      clearTimeout(t)
    }
  }, [id])
  return { tache, erreur, setTache }
}

// ---------------------------------------------------------------
// Onglet Exporter : sélection (départements, sources, filtres), compte, aperçu, export
// ---------------------------------------------------------------

type LigneFiltre = { col: string; op: FilterOperator; value: string }

function OngletExport({ sources, rechargerSources }: { sources: LeadsSource[]; rechargerSources: () => void }) {
  const { notice, montrer } = useNotice()
  const [exclues, setExclues] = useState<Set<number> | null>(null)
  const [choisis, setChoisis] = useState<Set<number>>(new Set())
  const [filtres, setFiltres] = useState<LigneFiltre[]>([])
  const [parDept, setParDept] = useState<LeadsDept[] | null>(null)
  const [erreurCompte, setErreurCompte] = useState<string | null>(null)
  const [apercu, setApercu] = useState<LeadsApercu | null>(null)
  const [pile, setPile] = useState<LeadsCurseur[]>([null])
  const [chargeApercu, setChargeApercu] = useState(false)
  const [erreurApercu, setErreurApercu] = useState<string | null>(null)
  const [deptsOuverts, setDeptsOuverts] = useState(false)
  const [exportId, setExportId] = useState<string | null>(null)
  const [comptageId, setComptageId] = useState<string | null>(null)
  const [erreurExport, setErreurExport] = useState<string | null>(null)
  const [lance, setLance] = useState(false)
  const export_ = useTache(exportId)
  const comptage = useTache(comptageId)

  // Premier affichage : les sources « mauvaise » sont exclues d'office (on peut les remettre).
  useEffect(() => {
    if (exclues === null && sources.length >= 0) {
      setExclues(new Set(sources.filter((s) => s.statut === 'mauvaise').map((s) => s.id)))
    }
  }, [sources, exclues])

  const selection: LeadsSelection = useMemo(() => {
    const f: LeadsSelection['filtres'] = {}
    for (const l of filtres) {
      if (l.op === 'vide' || l.op === 'non vide' || l.value.trim() !== '') f[l.col] = { op: l.op, value: l.value }
    }
    return { depts: [...choisis].sort((a, b) => a - b), exclues: [...(exclues ?? [])].sort((a, b) => a - b), filtres: f }
  }, [choisis, exclues, filtres])
  const cleSelection = JSON.stringify(selection)
  const avecFiltres = Object.keys(selection.filtres).length > 0

  // Comptes exacts par département (statistiques tenues par l'import) -- instantané
  const chargerComptes = useCallback(async () => {
    if (exclues === null) return
    try {
      const r = await leadsCompter([], [...exclues])
      setParDept(r.par_departement)
      setErreurCompte(null)
    } catch (e) {
      setErreurCompte(messageErreur(e))
    }
  }, [exclues])
  useEffect(() => {
    void chargerComptes()
  }, [chargerComptes])

  const totalSelection = useMemo(() => {
    if (!parDept) return null
    return parDept.filter((d) => choisis.size === 0 || choisis.has(d.dept)).reduce((s, d) => s + Number(d.n), 0)
  }, [parDept, choisis])

  // Aperçu : repart de la première page quand la sélection change (saisie différée)
  const chargerPage = useCallback(
    async (curseur: LeadsCurseur) => {
      setChargeApercu(true)
      try {
        const r = await leadsApercu(JSON.parse(cleSelection) as LeadsSelection, curseur)
        setApercu(r)
        setErreurApercu(null)
      } catch (e) {
        setErreurApercu(messageErreur(e))
      } finally {
        setChargeApercu(false)
      }
    },
    [cleSelection],
  )
  useEffect(() => {
    if (exclues === null) return
    setPile([null])
    setComptageId(null)
    const t = setTimeout(() => void chargerPage(null), DELAI_SAISIE_MS)
    return () => clearTimeout(t)
  }, [cleSelection, exclues, chargerPage])

  function suivante() {
    if (!apercu?.suite) return
    setPile((p) => [...p, apercu.suite])
    void chargerPage(apercu.suite)
  }
  function precedente() {
    if (pile.length < 2) return
    const p = pile.slice(0, -1)
    setPile(p)
    void chargerPage(p[p.length - 1])
  }

  function basculerDept(d: number) {
    setChoisis((s) => {
      const n = new Set(s)
      if (n.has(d)) n.delete(d)
      else n.add(d)
      return n
    })
  }
  function basculerSource(id: number) {
    setExclues((s) => {
      const n = new Set(s ?? [])
      if (n.has(id)) n.delete(id)
      else n.add(id)
      return n
    })
  }

  async function lancerExport(reprise = false) {
    setLance(true)
    setErreurExport(null)
    try {
      const r = reprise && exportId ? await leadsReprendreExport(exportId) : await leadsCreerExport(selection)
      setExportId(r.job.id)
      window.location.assign(leadsUrlTelechargement(r.url))
      montrer(true, reprise ? 'Reprise du téléchargement.' : 'Téléchargement lancé : le fichier arrive dans tes téléchargements.')
    } catch (e) {
      setErreurExport(messageErreur(e))
    } finally {
      setLance(false)
    }
  }
  async function annulerExport() {
    if (!exportId) return
    try {
      await leadsAnnuler(exportId)
      export_.setTache((t) => (t ? { ...t, status: 'annule' } : t))
      montrer(true, 'Export annulé.')
    } catch (e) {
      montrer(false, messageErreur(e))
    }
  }
  async function compterExact() {
    try {
      const r = await leadsComptage(selection)
      setComptageId(r.job.id)
    } catch (e) {
      montrer(false, messageErreur(e))
    }
  }

  const t = export_.tache
  const enCours = t?.status === 'en_cours' && !t.silencieuse
  const reprenable = t && (t.status === 'interrompu' || t.status === 'erreur' || (t.status === 'en_cours' && t.silencieuse))
  const exact = comptage.tache?.status === 'termine' ? Number((comptage.tache.params as { resultat?: number } | null)?.resultat ?? 0) : null

  const nbPages = pile.length
  const exclusNoms = sources.filter((s) => exclues?.has(s.id))

  return (
    <div className="space-y-4">
      <Message notice={notice} />

      <Card>
        <CardHeader>
          <p className="text-xs uppercase tracking-wide text-[var(--muted)]">Lignes pour cette sélection</p>
          {erreurCompte ? (
            <Erreur texte={erreurCompte} onRetry={() => void chargerComptes()} />
          ) : totalSelection == null ? (
            <p className="text-sm text-[var(--muted)]">Chargement…</p>
          ) : (
            <>
              <p className="text-3xl font-semibold" data-testid="total">
                {avecFiltres ? (exact != null ? nombre(exact) : `jusqu'à ${nombre(totalSelection)}`) : nombre(totalSelection)}
              </p>
              <p className="text-xs text-[var(--muted)]">
                {avecFiltres
                  ? exact != null
                    ? 'Compte exact avec tes filtres.'
                    : 'Avec des filtres sur les colonnes, le compte exact se calcule en tâche de fond.'
                  : 'Compte exact et instantané (départements et sources).'}
              </p>
              {avecFiltres && exact == null && (
                <div className="mt-2 space-y-2">
                  {comptage.tache?.status === 'en_cours' ? (
                    <Barre lues={comptage.tache.lignes_lues} total={null} />
                  ) : (
                    <Button variant="secondary" onClick={() => void compterExact()}>
                      Compter exactement
                    </Button>
                  )}
                  {comptage.tache && comptage.tache.status !== 'en_cours' && comptage.tache.status !== 'termine' && (
                    <Erreur texte={comptage.tache.message ?? 'Le comptage a échoué.'} onRetry={() => void compterExact()} />
                  )}
                </div>
              )}
            </>
          )}
        </CardHeader>
      </Card>

      <Card>
        <CardHeader>
          <button
            type="button"
            className="flex min-h-11 w-full items-center justify-between text-left"
            onClick={() => setDeptsOuverts((o) => !o)}
            aria-expanded={deptsOuverts}
          >
            <span className="text-sm font-semibold">
              Départements · {choisis.size === 0 ? 'tous' : `${choisis.size} choisi${choisis.size > 1 ? 's' : ''}`}
            </span>
            <span className="text-xs text-[var(--muted)]">{deptsOuverts ? 'Replier' : 'Choisir'}</span>
          </button>
        </CardHeader>
        {deptsOuverts && (
          <CardContent className="space-y-3 pt-0">
            {parDept && parDept.length === 0 ? (
              <p className="text-sm text-[var(--muted)]">Aucune ligne en base pour l'instant. Importe un fichier.</p>
            ) : (
              <>
                <div className="flex gap-2">
                  <Button variant="secondary" onClick={() => setChoisis(new Set((parDept ?? []).map((d) => d.dept)))}>
                    Tout cocher
                  </Button>
                  <Button variant="secondary" onClick={() => setChoisis(new Set())}>
                    Tous (aucun filtre)
                  </Button>
                </div>
                <div className="grid grid-cols-3 gap-2 sm:grid-cols-5 md:grid-cols-8">
                  {(parDept ?? []).map((d) => (
                    <label
                      key={d.dept}
                      className={cn(
                        'flex min-h-11 cursor-pointer flex-col justify-center rounded-lg px-2 py-1 text-center text-xs shadow-[var(--ring-card)]',
                        choisis.has(d.dept) && 'bg-[var(--primary)] text-[var(--primary-foreground)]',
                      )}
                    >
                      <input type="checkbox" className="sr-only" checked={choisis.has(d.dept)} onChange={() => basculerDept(d.dept)} />
                      <span className="font-semibold">{d.libelle}</span>
                      <span className="opacity-70">{nombre(Number(d.n))}</span>
                    </label>
                  ))}
                </div>
              </>
            )}
          </CardContent>
        )}
      </Card>

      <Card>
        <CardHeader>
          <p className="text-sm font-semibold">Sources à exclure</p>
          <p className="text-xs text-[var(--muted)]">Les sources marquées « mauvaise » sont exclues d'office.</p>
        </CardHeader>
        <CardContent className="space-y-2 pt-0">
          {sources.length === 0 ? (
            <p className="text-sm text-[var(--muted)]">Aucune source pour l'instant.</p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {sources.map((s) => {
                const exclue = exclues?.has(s.id)
                return (
                  <button
                    key={s.id}
                    type="button"
                    onClick={() => basculerSource(s.id)}
                    aria-pressed={Boolean(exclue)}
                    className={cn(
                      'min-h-11 rounded-lg px-3 text-xs shadow-[var(--ring-card)]',
                      exclue ? 'bg-red-600/15 text-red-700 line-through dark:text-red-400' : 'bg-[var(--card)]',
                    )}
                  >
                    {s.nom} · {nombre(s.lignes)}
                  </button>
                )
              })}
            </div>
          )}
          {exclusNoms.length > 0 && <p className="text-xs text-[var(--muted)]">{exclusNoms.length} source(s) exclue(s).</p>}
          <Button variant="ghost" onClick={rechargerSources}>
            Actualiser les sources
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <p className="text-sm font-semibold">Filtres sur les colonnes</p>
        </CardHeader>
        <CardContent className="space-y-3 pt-0">
          {filtres.map((f, i) => (
            <div key={i} className="grid grid-cols-2 gap-2 sm:grid-cols-[1fr_1fr_2fr_auto]">
              <select
                aria-label="Colonne"
                className="min-h-11 rounded-lg bg-[var(--card)] px-2 text-sm shadow-[var(--ring-card)]"
                value={f.col}
                onChange={(e) => setFiltres((l) => l.map((x, j) => (j === i ? { ...x, col: e.target.value } : x)))}
              >
                {COLONNES_FILTRE.map(([k, lib]) => (
                  <option key={k} value={k}>
                    {lib}
                  </option>
                ))}
              </select>
              <select
                aria-label="Condition"
                className="min-h-11 rounded-lg bg-[var(--card)] px-2 text-sm shadow-[var(--ring-card)]"
                value={f.op}
                onChange={(e) => setFiltres((l) => l.map((x, j) => (j === i ? { ...x, op: e.target.value as FilterOperator } : x)))}
              >
                {FILTER_OPERATORS.map((o) => (
                  <option key={o} value={o}>
                    {o}
                  </option>
                ))}
              </select>
              <Input
                aria-label="Valeur"
                className="col-span-2 sm:col-span-1"
                value={f.value}
                disabled={f.op === 'vide' || f.op === 'non vide'}
                onChange={(e) => setFiltres((l) => l.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))}
              />
              <Button variant="ghost" aria-label="Retirer ce filtre" onClick={() => setFiltres((l) => l.filter((_, j) => j !== i))}>
                Retirer
              </Button>
            </div>
          ))}
          {filtres.length < FILTRES_MAX && (
            <Button variant="secondary" onClick={() => setFiltres((l) => [...l, { col: 'ville', op: 'contient', value: '' }])}>
              + Ajouter un filtre
            </Button>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <p className="text-sm font-semibold">Aperçu</p>
          <p className="text-xs text-[var(--muted)]">
            {apercu ? `${nombre(apercu.rows.length)} lignes affichées (page ${nbPages}).` : ''} Ce n'est qu'un aperçu : l'export prend tout.
          </p>
        </CardHeader>
        <CardContent className="space-y-3 pt-0">
          {erreurApercu ? (
            <Erreur texte={erreurApercu} onRetry={() => void chargerPage(pile[pile.length - 1])} />
          ) : !apercu ? (
            <p className="text-sm text-[var(--muted)]">Chargement…</p>
          ) : apercu.rows.length === 0 && !apercu.suite ? (
            <p className="text-sm text-[var(--muted)]">Aucune ligne ne correspond à cette sélection.</p>
          ) : (
            <div className={cn('overflow-x-auto rounded-lg shadow-[var(--ring-card)]', chargeApercu && 'opacity-60')}>
              <table className="min-w-[900px] w-full text-left text-xs">
                <thead className="sticky top-0 bg-[var(--muted-bg)]">
                  <tr>
                    {COLONNES_APERCU.map(([k, lib]) => (
                      <th key={k} className="whitespace-nowrap px-2 py-2 font-semibold">
                        {lib}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {apercu.rows.map((r, i) => (
                    <tr key={String(r.curseur ?? i) + String(r.dept)} className="border-t border-[var(--border)]">
                      {COLONNES_APERCU.map(([k]) => (
                        <td key={k} className="max-w-[16rem] truncate whitespace-nowrap px-2 py-1.5">
                          {r[k] ?? ''}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="flex items-center justify-between gap-2">
            <Button variant="secondary" disabled={pile.length < 2 || chargeApercu} onClick={precedente}>
              ← Précédent
            </Button>
            <Button variant="secondary" disabled={!apercu?.suite || chargeApercu} onClick={suivante}>
              Suivant →
            </Button>
          </div>
          {apercu && apercu.rows.length === 0 && apercu.suite && (
            <p className="text-xs text-[var(--muted)]">Cette page n'a rien trouvé dans la zone lue : touche « Suivant » pour continuer la recherche.</p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <p className="text-sm font-semibold">Exporter</p>
          <p className="text-xs text-[var(--muted)]">Fichier CSV de toute la sélection (pas seulement l'aperçu), envoyé en continu.</p>
        </CardHeader>
        <CardContent className="space-y-3 pt-0">
          {erreurExport && <Erreur texte={erreurExport} />}
          {t && (
            <div className="space-y-2" data-testid="suivi-export">
              {t.status === 'en_cours' && !t.silencieuse && <Barre lues={t.lignes_lues} total={t.lignes_total} />}
              <p className="text-sm">
                {t.status === 'termine' && `Terminé : ${nombre(t.lignes_lues)} lignes exportées.`}
                {t.status === 'annule' && 'Export annulé.'}
                {enCours && 'Téléchargement en cours…'}
                {reprenable && (t.message ?? 'Export interrompu.')}
              </p>
              {export_.erreur && <p className="text-xs text-red-600">{export_.erreur}</p>}
            </div>
          )}
          <div className="flex flex-wrap gap-2">
            {!enCours && (
              <Button disabled={lance || (!avecFiltres && totalSelection === 0)} onClick={() => void lancerExport(false)}>
                {lance ? 'Préparation…' : `Exporter ${!avecFiltres && totalSelection != null ? nombre(totalSelection) + ' lignes' : 'la sélection'}`}
              </Button>
            )}
            {enCours && (
              <Button variant="danger" onClick={() => void annulerExport()}>
                Annuler l'export
              </Button>
            )}
            {reprenable && (
              <Button variant="secondary" onClick={() => void lancerExport(true)}>
                Reprendre le fichier
              </Button>
            )}
            {t?.status === 'en_cours' && t.silencieuse && exportId && (
              <Button
                variant="ghost"
                onClick={() => void leadsAbandonner(exportId).then(() => leadsJob(exportId).then(export_.setTache))}
              >
                Marquer comme interrompu
              </Button>
            )}
          </div>
          {reprenable && (
            <p className="text-xs text-[var(--muted)]">
              La reprise donne un second fichier (sans entête) à coller à la suite du premier ; quelques lignes de la jonction peuvent y
              être en double.
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

// ---------------------------------------------------------------
// Onglet Importer
// ---------------------------------------------------------------

function OngletImport({ sources, rechargerSources }: { sources: LeadsSource[]; rechargerSources: () => void }) {
  const { notice, montrer } = useNotice()
  const [source, setSource] = useState('')
  const [fichier, setFichier] = useState<File | null>(null)
  const [envoi, setEnvoi] = useState(false)
  const [erreur, setErreur] = useState<string | null>(null)
  const [dernier, setDernier] = useState<{ reconnues: Record<string, string>; ignorees: string[] } | null>(null)
  const [jobs, setJobs] = useState<LeadsJob[] | null>(null)
  const [erreurJobs, setErreurJobs] = useState<string | null>(null)
  const [reprise, setReprise] = useState<LeadsJob | null>(null)
  const [doublons, setDoublons] = useState<{ job: string; lignes: { dept: string; nom: string | null; source: string; source_existante: string | null }[] } | null>(null)
  const entree = useRef<HTMLInputElement | null>(null)
  const entreeReprise = useRef<HTMLInputElement | null>(null)

  const charger = useCallback(async () => {
    try {
      const r = await leadsJobs('import')
      setJobs(r.jobs)
      setErreurJobs(null)
    } catch (e) {
      setErreurJobs(messageErreur(e))
    }
  }, [])
  useEffect(() => {
    void charger()
  }, [charger])
  const actifs = jobs?.some((j) => j.status === 'en_cours' && !j.silencieuse) ?? false
  useEffect(() => {
    if (!actifs) return
    const t = setInterval(() => void charger(), INTERVALLE_TACHE_MS)
    return () => clearInterval(t)
  }, [actifs, charger])
  // à la fin d'une tâche, les sources (comptes) changent
  const etatsVus = useRef('')
  useEffect(() => {
    const etats = (jobs ?? []).map((j) => j.id + j.status).join('|')
    if (etatsVus.current && etats !== etatsVus.current) rechargerSources()
    etatsVus.current = etats
  }, [jobs, rechargerSources])

  async function envoyer(f: File, nom: string, reprendre?: string) {
    setEnvoi(true)
    setErreur(null)
    try {
      const r = await leadsImporter(f, nom, reprendre)
      setDernier({ reconnues: r.colonnes_reconnues, ignorees: r.colonnes_ignorees })
      montrer(true, reprendre ? 'Import repris.' : 'Import lancé : il continue même si tu changes d\'écran.')
      setFichier(null)
      setReprise(null)
      if (entree.current) entree.current.value = ''
      await charger()
    } catch (e) {
      setErreur(messageErreur(e))
    } finally {
      setEnvoi(false)
    }
  }

  async function annuler(j: LeadsJob) {
    if (!window.confirm(`Annuler l'import de « ${j.filename} » ? Les lignes déjà importées restent en base.`)) return
    try {
      await leadsAnnuler(j.id)
      montrer(true, 'Import annulé.')
      await charger()
    } catch (e) {
      montrer(false, messageErreur(e))
    }
  }
  async function abandonner(j: LeadsJob) {
    try {
      await leadsAbandonner(j.id)
      montrer(true, 'Tâche marquée comme interrompue : tu peux la reprendre.')
      await charger()
    } catch (e) {
      montrer(false, messageErreur(e))
    }
  }
  async function voirDoublons(j: LeadsJob) {
    try {
      const r = await leadsDoublons(j.id)
      setDoublons({ job: j.id, lignes: r.doublons })
    } catch (e) {
      montrer(false, messageErreur(e))
    }
  }
  const nomSource = (id: number | null) => sources.find((s) => s.id === id)?.nom ?? ''

  return (
    <div className="space-y-4">
      <Message notice={notice} />
      <Card>
        <CardHeader>
          <p className="text-sm font-semibold">Importer un fichier</p>
          <p className="text-xs text-[var(--muted)]">
            CSV ou Excel. Les doublons (même téléphone ou même e-mail dans le même département) sont écartés et comptés. Le fichier part
            en tâche de fond.
          </p>
        </CardHeader>
        <CardContent className="space-y-3 pt-0">
          <label className="block space-y-1 text-sm">
            <span>Nom de la source</span>
            <Input list="sources-existantes" value={source} onChange={(e) => setSource(e.target.value)} placeholder="Ex. Salon 2026, Fournisseur X" />
            <datalist id="sources-existantes">
              {sources.map((s) => (
                <option key={s.id} value={s.nom} />
              ))}
            </datalist>
          </label>
          <label className="block space-y-1 text-sm">
            <span>Fichier</span>
            <input
              ref={entree}
              type="file"
              accept=".csv,.xlsx,.xls,text/csv"
              className="block min-h-11 w-full text-sm"
              onChange={(e) => setFichier(e.target.files?.[0] ?? null)}
            />
          </label>
          {erreur && <Erreur texte={erreur} />}
          <Button disabled={envoi || !fichier || !source.trim()} onClick={() => fichier && void envoyer(fichier, source.trim())}>
            {envoi ? 'Envoi du fichier…' : 'Importer'}
          </Button>
          {envoi && <p className="text-xs text-[var(--muted)]">Envoi en cours : ne quitte pas la page tant que le fichier n'est pas parti.</p>}
          {dernier && (
            <div className="rounded-lg bg-[var(--muted-bg)] p-3 text-xs" data-testid="colonnes">
              <p className="font-semibold">Colonnes reconnues</p>
              <p>{Object.entries(dernier.reconnues).map(([k, v]) => `${v} → ${k}`).join(' · ')}</p>
              {dernier.ignorees.length > 0 && <p className="mt-1 text-[var(--muted)]">Ignorées : {dernier.ignorees.join(', ')}</p>}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <p className="text-sm font-semibold">Imports récents</p>
        </CardHeader>
        <CardContent className="space-y-3 pt-0">
          {erreurJobs ? (
            <Erreur texte={erreurJobs} onRetry={() => void charger()} />
          ) : jobs == null ? (
            <p className="text-sm text-[var(--muted)]">Chargement…</p>
          ) : jobs.length === 0 ? (
            <p className="text-sm text-[var(--muted)]">Aucun import pour l'instant.</p>
          ) : (
            jobs.map((j) => {
              const vivant = j.status === 'en_cours' && !j.silencieuse
              const reprenable = j.status === 'interrompu' || j.status === 'erreur' || (j.status === 'en_cours' && j.silencieuse)
              return (
                <div key={j.id} className="space-y-2 rounded-lg p-3 shadow-[var(--ring-card)]" data-testid="import-job">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-semibold">{j.filename}</p>
                      <p className="text-xs text-[var(--muted)]">{nomSource(j.source_id)}</p>
                    </div>
                    <span className="shrink-0 rounded-md bg-[var(--muted-bg)] px-2 py-1 text-xs">
                      {j.status === 'termine' ? 'Terminé' : j.status === 'annule' ? 'Annulé' : vivant ? 'En cours' : 'Interrompu'}
                    </span>
                  </div>
                  {(vivant || reprenable) && <Barre lues={j.lignes_lues} total={j.lignes_total} />}
                  <p className="text-xs">
                    {nombre(j.inserees)} ajoutées · {nombre(j.doublons)} doublons écartés · {nombre(j.invalides)} sans téléphone ni e-mail
                  </p>
                  {j.message && j.status !== 'termine' && <p className="text-xs text-[var(--muted)]">{j.message}</p>}
                  <div className="flex flex-wrap gap-2">
                    {vivant && (
                      <Button variant="danger" onClick={() => void annuler(j)}>
                        Annuler
                      </Button>
                    )}
                    {reprenable && (
                      <Button
                        variant="secondary"
                        onClick={() => {
                          setReprise(j)
                          entreeReprise.current?.click()
                        }}
                      >
                        Reprendre
                      </Button>
                    )}
                    {j.status === 'en_cours' && j.silencieuse && (
                      <Button variant="ghost" onClick={() => void abandonner(j)}>
                        Marquer comme interrompu
                      </Button>
                    )}
                    {j.doublons > 0 && (
                      <Button variant="ghost" onClick={() => void voirDoublons(j)}>
                        Voir des doublons
                      </Button>
                    )}
                  </div>
                </div>
              )
            })
          )}
          <input
            ref={entreeReprise}
            type="file"
            accept=".csv,.xlsx,.xls,text/csv"
            className="sr-only"
            aria-label="Choisir le même fichier pour reprendre"
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f && reprise) void envoyer(f, nomSource(reprise.source_id), reprise.id)
              e.target.value = ''
            }}
          />
          <p className="text-xs text-[var(--muted)]">Pour reprendre un import, choisis le même fichier : il repart là où il s'est arrêté.</p>
        </CardContent>
      </Card>

      {doublons && (
        <Card>
          <CardHeader className="flex items-center justify-between">
            <p className="text-sm font-semibold">Exemples de doublons écartés</p>
            <Button variant="ghost" onClick={() => setDoublons(null)}>
              Fermer
            </Button>
          </CardHeader>
          <CardContent className="space-y-1 pt-0 text-xs">
            {doublons.lignes.length === 0 ? (
              <p className="text-[var(--muted)]">Aucun exemple gardé (les doublons de cet import sont comptés, pas listés).</p>
            ) : (
              doublons.lignes.slice(0, 50).map((d, i) => (
                <p key={i}>
                  {d.nom ?? '(sans nom)'} · dép. {d.dept} · déjà présent via « {d.source_existante ?? '?'} »
                </p>
              ))
            )}
          </CardContent>
        </Card>
      )}
    </div>
  )
}

// ---------------------------------------------------------------
// Onglet Sources
// ---------------------------------------------------------------

function OngletSources({ sources, erreur, rechargerSources }: { sources: LeadsSource[] | null; erreur: string | null; rechargerSources: () => void }) {
  const { notice, montrer } = useNotice()
  const [recherche, setRecherche] = useState('')
  const [enCours, setEnCours] = useState<number | null>(null)

  async function regler(s: LeadsSource, statut: LeadsStatut) {
    if (s.statut === statut) return
    setEnCours(s.id)
    try {
      await leadsRegler(s.id, statut)
      montrer(true, `« ${s.nom} » : ${LIBELLE_STATUT[statut].toLowerCase()}.`)
      rechargerSources()
    } catch (e) {
      montrer(false, messageErreur(e))
    } finally {
      setEnCours(null)
    }
  }

  const liste = (sources ?? []).filter((s) => s.nom.toLowerCase().includes(recherche.trim().toLowerCase()))
  return (
    <div className="space-y-4">
      <Message notice={notice} />
      {erreur && <Erreur texte={erreur} onRetry={rechargerSources} />}
      {sources == null && !erreur && <p className="text-sm text-[var(--muted)]">Chargement…</p>}
      {sources && sources.length === 0 && (
        <p className="rounded-lg bg-[var(--muted-bg)] p-4 text-sm">Aucune source pour l'instant. Elles apparaissent quand tu importes un fichier.</p>
      )}
      {sources && sources.length > 6 && <Input placeholder="Chercher une source…" value={recherche} onChange={(e) => setRecherche(e.target.value)} />}
      {liste.map((s) => (
        <Card key={s.id}>
          <CardContent className="space-y-2">
            <div className="flex items-start justify-between gap-2">
              <p className="min-w-0 truncate text-sm font-semibold">{s.nom}</p>
              <span className={cn('shrink-0 rounded-md px-2 py-1 text-xs', COULEUR_STATUT[s.statut])}>{LIBELLE_STATUT[s.statut]}</span>
            </div>
            <p className="text-xs text-[var(--muted)]">
              {nombre(s.lignes)} lignes en base · {nombre(s.doublons_rejetes)} doublons écartés · {nombre(s.invalides)} sans contact
            </p>
            <div className="grid grid-cols-3 gap-2" role="group" aria-label={`Statut de ${s.nom}`}>
              {(['bonne', 'a_verifier', 'mauvaise'] as LeadsStatut[]).map((st) => (
                <Button
                  key={st}
                  variant={s.statut === st ? 'primary' : 'secondary'}
                  disabled={enCours === s.id}
                  aria-pressed={s.statut === st}
                  onClick={() => void regler(s, st)}
                  className="px-1 text-xs"
                >
                  {LIBELLE_STATUT[st]}
                </Button>
              ))}
            </div>
          </CardContent>
        </Card>
      ))}
      {sources && sources.length > 0 && liste.length === 0 && <p className="text-sm text-[var(--muted)]">Aucune source ne correspond.</p>}
    </div>
  )
}

// ---------------------------------------------------------------

export function LeadsScreen() {
  const [onglet, setOnglet] = useState<Onglet>('export')
  const [sources, setSources] = useState<LeadsSource[] | null>(null)
  const [erreur, setErreur] = useState<string | null>(null)

  const chargerSources = useCallback(async () => {
    try {
      const r = await leadsSources()
      setSources(r.sources)
      setErreur(null)
    } catch (e) {
      setErreur(messageErreur(e))
    }
  }, [])
  useEffect(() => {
    void chargerSources()
  }, [chargerSources])

  const onglets: [Onglet, string][] = [
    ['export', 'Exporter'],
    ['import', 'Importer'],
    ['sources', 'Sources'],
  ]

  return (
    <main className="mx-auto max-w-5xl space-y-4 px-4 py-4">
      <h1 className="text-lg font-semibold">Leads</h1>
      <div className="grid grid-cols-3 gap-2" role="tablist">
        {onglets.map(([k, lib]) => (
          <Button key={k} role="tab" aria-selected={onglet === k} variant={onglet === k ? 'primary' : 'secondary'} onClick={() => setOnglet(k)}>
            {lib}
          </Button>
        ))}
      </div>
      {erreur && onglet !== 'sources' && <Erreur texte={erreur} onRetry={() => void chargerSources()} />}
      {onglet === 'export' && sources && <OngletExport sources={sources} rechargerSources={() => void chargerSources()} />}
      {onglet === 'export' && !sources && !erreur && <p className="text-sm text-[var(--muted)]">Chargement…</p>}
      {onglet === 'import' && <OngletImport sources={sources ?? []} rechargerSources={() => void chargerSources()} />}
      {onglet === 'sources' && <OngletSources sources={sources} erreur={erreur} rechargerSources={() => void chargerSources()} />}
    </main>
  )
}
