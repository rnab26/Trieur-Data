#!/usr/bin/env python3
"""Banc de non-régression SQL de la migration 0035 (base Leads à très grand volume)
-- chantier cockpit 6547bd6a.

Crée un schéma JETABLE `test_leads_<aléatoire>` (jamais une vraie table, données
fictives), y applique le texte de supabase/migrations/0035_leads_massifs.sql avec
`trieur_data` remplacé par le schéma jetable, vérifie chaque règle (normalisation,
dédoublonnage, comptes exacts, aperçu par curseur, export CSV par fenêtres, droits),
puis supprime le schéma. Passe par scripts/sql.sh (jamais l'outil MCP).

    python3 scripts/verifier_leads_sql.py            # contrôles de justesse (petit volume)
    python3 scripts/verifier_leads_sql.py --garder   # ne supprime pas le schéma (mesures)

Le module est aussi utilisé par scripts/mesurer_leads.py (mesures de volume).
"""
import json
import pathlib
import re
import secrets
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SQL = ROOT / "scripts" / "sql.sh"
MIGRATION = ROOT / "supabase" / "migrations" / "0035_leads_massifs.sql"
ORG = "11111111-1111-1111-1111-111111111111"
USER = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
OTHER = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
CLAIMS = "set_config('request.jwt.claims','{\"sub\":\"%s\"}', true)" % USER


def sql(q):
    r = subprocess.run([str(SQL), " ".join(l.strip() for l in q.split("\n"))], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{q[:120]}...\n{r.stdout}{r.stderr}")
    return json.loads(r.stdout).get("rows")


def migration_statements(schema):
    t = MIGRATION.read_text(encoding="utf-8")
    t = re.sub(r"--[^\n]*", "", t).replace("trieur_data", schema)
    out, cur, in_fn = [], [], False
    for line in t.split("\n"):
        cur.append(line)
        in_fn ^= (line.count("$fn$") + line.count("$$")) % 2 == 1
        if not in_fn and line.rstrip().endswith(";"):
            out.append("\n".join(cur))
            cur = []
    return [s for s in out if s.strip()]


def creer_schema(schema):
    """Schéma jetable : même structure que la vraie base (migration appliquée telle quelle)."""
    sql(f"create schema {schema}")
    sql(f"create table {schema}.organizations (id uuid primary key, slug text unique)")
    sql(f"insert into {schema}.organizations values ('{ORG}', 'leads')")
    sql(f"create table {schema}.memberships (user_id uuid, org_id uuid, role text)")
    sql(f"insert into {schema}.memberships values ('{USER}', '{ORG}', 'member'), ('{OTHER}', '{ORG}', 'lecture_seule')")
    sql(f"create function {schema}.is_super_admin() returns boolean language sql stable as $f$ select auth.uid() = '{USER}'::uuid $f$")
    sql(
        f"create function {schema}.is_org_member(o uuid) returns boolean language sql stable security definer "
        f"set search_path to '{schema}' as $f$ select exists (select 1 from {schema}.memberships "
        f"where user_id = auth.uid() and org_id = o) $f$"
    )
    sql(
        f"create function {schema}.can_write(o uuid) returns boolean language sql stable security definer "
        f"set search_path to '{schema}' as $f$ select exists (select 1 from {schema}.memberships "
        f"where user_id = auth.uid() and org_id = o and role in ('member','org_admin')) $f$"
    )
    for st in migration_statements(schema):
        sql(st)


def supprimer_schema(schema):
    sql(f"drop schema if exists {schema} cascade")


def rows_json(prefix, n, depts=95, start=1):
    """SQL : tableau JSON de n lignes fictives réalistes (téléphone unique par numéro)."""
    return (
        f"(select jsonb_agg(jsonb_build_object('nom','NOM'||g,'prenom','Prenom'||(g%500),"
        f"'email','{prefix}'||g||'@exemple.fr','tel_mobile','06'||lpad((g)::text,8,'0'),'tel_fixe',null,"
        f"'adresse',(g%200)||' rue des Tests','cp',lpad((1+(g%{depts}))::text,2,'0')||'000','ville','Ville'||(g%800),"
        f"'civilite',case g%2 when 0 then 'M' else 'Mme' end,'naissance','19'||(50+g%40)||'-0'||(1+g%9)||'-1'||(g%9)))"
        f" from generate_series({start},{start + n - 1}) g)"
    )


def main():
    garder = "--garder" in sys.argv
    schema = "test_leads_" + secrets.token_hex(4)
    resultats = []

    def ok(label, obtenu, attendu):
        resultats.append((label, obtenu == attendu, obtenu, attendu))

    def q(query, claims=CLAIMS):
        return sql(f"with c as (select {claims}) {query}")

    try:
        creer_schema(schema)
        S = schema
        # --- normalisation
        r = sql(
            f"select {S}.leads_dept('75001') a, {S}.leads_dept('1000') b, {S}.leads_dept('20100') c, {S}.leads_dept('20200') d, "
            f"{S}.leads_dept('97100') e, {S}.leads_dept('') f, {S}.leads_dept('99999') g, {S}.leads_dept('1234') h, "
            f"{S}.leads_tel('+33 6 12 34 56 78') t1, {S}.leads_tel('06.12.34.56.78') t2, {S}.leads_tel('0033612345678') t3, "
            f"{S}.leads_tel('1234') t4, {S}.leads_email('  A@B.fr ') e1, {S}.leads_email('pas un mail') e2, "
            f"{S}.leads_cle(null, null, 'a@b.fr') k1, {S}.leads_cle(null, null, 'A@B.fr ') k2, {S}.leads_cle('0612345678', null, 'a@b.fr') k3, "
            f"{S}.leads_date('25/12/1980') d1, {S}.leads_date('1980-12-25') d2, {S}.leads_date('31/02/1980') d3, {S}.leads_date('abc') d4"
        )[0]
        ok("département : 75001 -> 75", r["a"], 75)
        ok("département : code postal à 4 chiffres (1000) -> 1", r["b"], 1)
        ok("département : Corse 20100 -> 201 (2A)", r["c"], 201)
        ok("département : Corse 20200 -> 202 (2B)", r["d"], 202)
        ok("département : 97100 -> 971", r["e"], 971)
        ok("département : vide -> 0 (inconnu)", r["f"], 0)
        ok("département : 99999 -> 0 (inconnu)", r["g"], 0)
        ok("département : 4 chiffres (1234) -> 1", r["h"], 1)
        ok("téléphone : +33 6 12 34 56 78", r["t1"], 612345678)
        ok("téléphone : 06.12.34.56.78 (même numéro)", r["t2"], 612345678)
        ok("téléphone : 0033612345678 (même numéro)", r["t3"], 612345678)
        ok("téléphone : trop court -> null", r["t4"], None)
        ok("e-mail : minuscules et espaces", r["e1"], "a@b.fr")
        ok("e-mail : sans @ -> null", r["e2"], None)
        ok("clé e-mail insensible à la casse/espaces", r["k1"] == r["k2"] and r["k1"] < 0, True)
        ok("clé : le téléphone prime sur l'e-mail", r["k3"], 612345678)
        ok("date 25/12/1980", r["d1"], "1980-12-25")
        ok("date ISO", r["d2"], "1980-12-25")
        ok("date impossible -> null", r["d3"], None)
        ok("date illisible -> null", r["d4"], None)

        # --- sources + import
        job = q(f"select {S}.leads_job_creer('import', {S}.leads_source_obtenir('Fichier A'), 'a.csv', 1000, null) j from c")[0]["j"]
        ok("source créée à 'a_verifier'", q(f"select statut from {S}.leads_sources where nom = 'Fichier A'")[0]["statut"], "a_verifier")
        sa = int(q(f"select id from {S}.leads_sources where nom='Fichier A'")[0]["id"])
        rep = q(f"select {S}.leads_importer_lot('{job['id']}', {sa}::smallint, {rows_json('a', 1000, depts=10)}, 1000) r from c")[0]["r"]
        ok("import 1000 lignes : toutes insérées", (rep["inserees"], rep["doublons"], rep["invalides"]), (1000, 0, 0))
        # même fichier rejoué (autre source) : 100 % doublons
        job2 = q(f"select {S}.leads_job_creer('import', {S}.leads_source_obtenir('Fichier B'), 'b.csv', 1000, null) j from c")[0]["j"]
        sb = int(q(f"select id from {S}.leads_sources where nom='Fichier B'")[0]["id"])
        rep = q(f"select {S}.leads_importer_lot('{job2['id']}', {sb}::smallint, {rows_json('a', 1000, depts=10)}, 1000) r from c")[0]["r"]
        ok("même fichier rejoué : 1000 doublons, 0 inséré", (rep["inserees"], rep["doublons"]), (0, 1000))
        # mélange : 500 connus + 500 nouveaux, plus 3 invalides et 2 doublons internes
        extra = (
            f"(select jsonb_agg(x.value) from (select value from jsonb_array_elements({rows_json('a', 500, depts=10, start=501)}) "
            f"union all select value from jsonb_array_elements({rows_json('n', 500, depts=10, start=2001)}) "
            f"union all select '{{\"nom\":\"vide\"}}'::jsonb union all select '{{\"nom\":\"vide2\",\"cp\":\"75001\"}}'::jsonb "
            f"union all select '{{\"tel_mobile\":\"abc\"}}'::jsonb "
            f"union all select jsonb_build_object('tel_mobile','0699999999','cp','75001') union all select jsonb_build_object('tel_mobile','06 99 99 99 99','cp','75001')) x)"
        )
        rep = q(f"select {S}.leads_importer_lot('{job2['id']}', {sb}::smallint, {extra}, 1005) r from c")[0]["r"]
        ok("lot mixte : insérées", rep["inserees"], 501)
        ok("lot mixte : doublons (500 connus + 1 interne)", rep["doublons"], 501)
        ok("lot mixte : invalides (3)", rep["invalides"], 3)
        tot = int(sql(f"select count(*) c from {S}.leads")[0]["c"])
        ok("total en base = 1000 + 501", tot, 1501)
        st = sql(f"select sum(n) n from {S}.leads_stats")[0]["n"]
        ok("statistiques = lignes réelles", int(st), tot)
        ok("progression de la tâche (lignes lues)", int(q(f"select lignes_lues from {S}.leads_jobs where id='{job2['id']}'")[0]["lignes_lues"]), 2005)
        ok("doublons d'exemple gardés", int(q(f"select count(*) c from {S}.leads_doublons_exemples where job_id='{job2['id']}'")[0]["c"]) > 0, True)
        ok("compteur doublons de la source B", int(sql(f"select doublons_rejetes d from {S}.leads_sources where id={sb}")[0]["d"]), 1000 + 501)
        # comptes exacts
        r = q(f"select {S}.leads_compter(null, null) a, {S}.leads_compter(array[1,2]::smallint[], null) b, {S}.leads_compter(null, array[{sb}]::smallint[]) c from c")[0]
        ok("compter : tous", sum(x["n"] for x in r["a"]), tot)
        ok("compter : départements 1 et 2 seulement", {x["dept"] for x in r["b"]} <= {1, 2}, True)
        ok("compter : source B exclue", sum(x["n"] for x in r["c"]), int(sql(f"select count(*) c from {S}.leads where source_id={sa}")[0]["c"]))
        # le statut d'une source
        q(f"select {S}.leads_source_regler({sb}::smallint, 'mauvaise') from c")
        ok("source marquée mauvaise", sql(f"select statut from {S}.leads_sources where id={sb}")[0]["statut"], "mauvaise")
        try:
            q(f"select {S}.leads_source_regler({sb}::smallint, 'nimporte') from c")
            ok("statut invalide refusé", False, True)
        except RuntimeError:
            ok("statut invalide refusé", True, True)

        # --- lecture : aperçu par curseur, comptage, CSV par fenêtres
        vus, dept, apres, pages = [], None, None, 0
        while True:
            d = "null" if dept is None else str(dept)
            a = "null" if apres is None else f"'{apres}'"
            r = q(f"select {S}.leads_lire(null, null, '{{}}'::jsonb, {d}::smallint, {a}, 100, 100000, 'apercu') r from c")[0]["r"]
            vus += [x["curseur"] + "|" + (x["dept"] or "") for x in r["rows"]]
            pages += 1
            if not r["suite"] or pages > 60:
                break
            dept, apres = r["suite"]["dept"], r["suite"]["apres"]
        ok("aperçu : toutes les lignes, une seule fois, par pages de 100", (len(vus), len(set(vus))), (tot, tot))
        r = q(f"select {S}.leads_lire(null, null, '{{}}'::jsonb, null, null, 100, 100000, 'apercu') r from c")[0]["r"]
        ok("aperçu : première page = 100 lignes + une suite", (len(r["rows"]), bool(r["suite"])), (100, True))
        r = q(f"select {S}.leads_lire(array[3]::smallint[], null, '{{}}'::jsonb, null, null, 1000, 100000, 'apercu') r from c")[0]["r"]
        ok("aperçu : département 3 seulement", {x["dept"] for x in r["rows"]}, {"03"})
        r = q(f"select {S}.leads_lire(null, array[{sb}]::smallint[], '{{}}'::jsonb, null, null, 5000, 100000, 'apercu') r from c")[0]["r"]
        ok("aperçu : source B exclue", {x["source"] for x in r["rows"]}, {"Fichier A"})
        r = q(f"select {S}.leads_lire(null, null, '{{\"ville\":{{\"op\":\"égal à\",\"value\":\"ville7\"}}}}'::jsonb, null, null, 5000, 100000, 'apercu') r from c")[0]["r"]
        attendu = int(sql(f"select count(*) c from {S}.leads where lower(ville)='ville7'")[0]["c"])
        ok("aperçu : filtre colonne (égal à)", len(r["rows"]), attendu)
        try:
            q(f"select {S}.leads_lire(null, null, '{{\"data\":{{\"op\":\"vide\"}}}}'::jsonb, null, null, 5, 10, 'apercu') from c")
            ok("filtre sur une colonne inconnue refusé", False, True)
        except RuntimeError:
            ok("filtre sur une colonne inconnue refusé", True, True)
        r = q(f"select {S}.leads_lire(null, null, '{{\"nom\":{{\"op\":\"contient\",\"value\":\"o''x\"}}}}'::jsonb, null, null, 10, 100000, 'apercu') r from c")[0]["r"]
        ok("apostrophe dans une valeur de filtre : pas d'injection", len(r["rows"]), 0)
        # CSV : fenêtres de 1 bloc pour forcer plusieurs appels
        sql(f"update {S}.leads_reglages set valeur='1' where cle='pas_blocs'")
        total, dept, apres, appels, lignes = 0, None, None, 0, []
        while True:
            d = "null" if dept is None else str(dept)
            a = "null" if apres is None else f"'{apres}'"
            r = q(f"select {S}.leads_lire(null, null, '{{}}'::jsonb, {d}::smallint, {a}, null, 1, 'csv') r from c")[0]["r"]
            total += r["n"]
            if r["csv"]:
                lignes += r["csv"].split("\n")
            appels += 1
            if not r["suite"] or appels > 400:
                break
            dept, apres = r["suite"]["dept"], r["suite"]["apres"]
        ok("export CSV par fenêtres : toutes les lignes", (total, len(lignes)), (tot, tot))
        ok("export CSV : plusieurs appels (reprise par fenêtre)", appels > 3, True)
        ok("export CSV : téléphone avec le 0 devant", any(",0699999999," in x for x in lignes) or any("0699999999" in x for x in lignes), True)
        ok("export CSV : 12 colonnes", {len(x.split(",")) for x in lignes if '"' not in x} <= {12}, True)
        c = q(f"select {S}.leads_lire(null, null, '{{}}'::jsonb, null, null, null, 100000, 'compte') r from c")[0]["r"]
        ok("comptage exact en fenêtres = lignes", c["n"], tot)
        ok("blocs à lire (barre de progression) > 0", int(q(f"select {S}.leads_blocs(null) b from c")[0]["b"]) > 0, True)
        # --- droits
        autre = "set_config('request.jwt.claims','{\"sub\":\"%s\"}', true)" % OTHER
        try:
            q(f"select {S}.leads_importer_lot('{job['id']}', {sa}::smallint, '[]'::jsonb, 0) from c", autre)
            ok("lecture seule : import refusé", False, True)
        except RuntimeError:
            ok("lecture seule : import refusé", True, True)
        ok("lecture seule : lecture permise", len(q(f"select {S}.leads_sources_lister() r from c", autre)[0]["r"]), 2)
        inconnu = "set_config('request.jwt.claims','{\"sub\":\"cccccccc-cccc-cccc-cccc-cccccccccccc\"}', true)"
        try:
            q(f"select {S}.leads_compter(null, null) from c", inconnu)
            ok("non-membre : lecture refusée", False, True)
        except RuntimeError:
            ok("non-membre : lecture refusée", True, True)
        ok("tables fermées en accès direct (aucune politique)", sql(
            f"select count(*) c from pg_policies where schemaname='{S}' and tablename like 'leads%'")[0]["c"], 0)
        # annulation d'une tâche : l'import suivant refuse
        q(f"select {S}.leads_job_annuler('{job2['id']}') from c")
        try:
            q(f"select {S}.leads_importer_lot('{job2['id']}', {sb}::smallint, '[]'::jsonb, 0) from c")
            ok("tâche annulée : le lot suivant est refusé", False, True)
        except RuntimeError as exc:
            ok("tâche annulée : le lot suivant est refusé", "tache_annule" in str(exc), True)
    finally:
        if garder:
            print("schéma gardé :", schema)
        else:
            try:
                supprimer_schema(schema)
            except Exception as exc:  # noqa: BLE001
                print(f"ATTENTION : schéma jetable {schema} à supprimer à la main : {exc}", file=sys.stderr)

    bad = 0
    for label, good, got, want in resultats:
        print(("OK  " if good else "KO  ") + label + ("" if good else f"  (obtenu {got!r}, attendu {want!r})"))
        bad += 0 if good else 1
    print(f"{len(resultats) - bad}/{len(resultats)} contrôles OK")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
