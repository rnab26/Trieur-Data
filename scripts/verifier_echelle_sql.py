#!/usr/bin/env python3
"""Banc de non-régression SQL de la migration 0034 (recherche, filtres, total
plafonné, curseur d'export) -- chantier cockpit 6547bd6a.

Crée un schéma JETABLE `test_echelle_<aléatoire>` (jamais une vraie table :
copie de structure de trieur_data.records, 5 000 lignes fictives), y applique
le texte de supabase/migrations/0034_records_echelle.sql avec `trieur_data`
remplacé par le schéma jetable, compare chaque résultat de search_records à un
comptage SQL indépendant, puis supprime le schéma. Passe par scripts/sql.sh
(clé en variable d'environnement, jamais l'outil MCP). Ne mesure pas la
vitesse : le volume est trop petit (voir PROJECT_LOG.md pour les mesures à
500 000 lignes).

    python3 scripts/verifier_echelle_sql.py
"""
import json
import pathlib
import re
import secrets
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SQL = ROOT / "scripts" / "sql.sh"
SCHEMA = "test_echelle_" + secrets.token_hex(4)
ORG = "11111111-1111-1111-1111-111111111111"
USER = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
CLAIMS = "set_config('request.jwt.claims','{\"sub\":\"%s\"}', true)" % USER


def sql(q):
    r = subprocess.run([str(SQL), " ".join(l.strip() for l in q.split("\n"))], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{q[:90]}...\n{r.stdout}{r.stderr}")
    return json.loads(r.stdout).get("rows")


def migration_statements():
    t = (ROOT / "supabase/migrations/0034_records_echelle.sql").read_text(encoding="utf-8")
    t = re.sub(r"--[^\n]*", "", t).replace("trieur_data", SCHEMA)
    t = t.replace("create extension if not exists pg_trgm with schema extensions;", "")
    out, cur, in_fn = [], [], False
    for line in t.split("\n"):
        cur.append(line)
        in_fn ^= (line.count("$fn$") + line.count("$$")) % 2 == 1
        if not in_fn and line.rstrip().endswith(";"):
            out.append("\n".join(cur))
            cur = []
    return [s for s in out if s.strip()]


def main():
    failures = 0
    try:
        sql(f"create schema {SCHEMA}")
        sql(f"create table {SCHEMA}.import_batches (like trieur_data.import_batches including all)")
        sql(f"create table {SCHEMA}.records (like trieur_data.records including all)")
        sql(f"create table {SCHEMA}.record_tags (like trieur_data.record_tags including all)")
        sql(f"create table {SCHEMA}.memberships (user_id uuid, org_id uuid)")
        sql(f"insert into {SCHEMA}.memberships values ('{USER}', '{ORG}')")
        sql(
            f"create function {SCHEMA}.is_org_member(o uuid) returns boolean language sql stable security definer "
            f"set search_path to '{SCHEMA}' as $f$ select exists (select 1 from {SCHEMA}.memberships "
            f"where user_id = auth.uid() and org_id = o) $f$"
        )
        sql(
            f"insert into {SCHEMA}.import_batches (id, org_id, source_filename, imported_by, imported_at, row_count) "
            f"select ('00000000-0000-0000-0000-'||lpad(g::text,12,'0'))::uuid, '{ORG}', 'fichier_'||g||'.xlsx', null, "
            f"now(), 100 from generate_series(1,5) g"
        )
        sql(
            f"insert into {SCHEMA}.records (org_id, batch_id, data, created_at) select '{ORG}', "
            f"('00000000-0000-0000-0000-'||lpad((1+(g%5))::text,12,'0'))::uuid, "
            f"jsonb_build_object('nom','Nom'||g,'ville','Ville'||(g%50),'statut',(array['actif','suspendu'])[1+g%2],"
            f"'vide',case when g%4=0 then '' else 'x' end), now() - (g||' seconds')::interval "
            f"from generate_series(1,5000) g"
        )
        sql(
            f"insert into {SCHEMA}.record_tags (org_id, record_id, tag, created_by) "
            f"select '{ORG}', id, 'VIP', null from {SCHEMA}.records where (data->>'nom') = 'Nom10'"
        )
        for st in migration_statements():
            sql(st)

        def got(search, filters, **kw):
            lit = lambda x: x.replace("'", "''")
            args = f"'{ORG}','{lit(search)}','{lit(json.dumps(filters, ensure_ascii=False))}'::jsonb,{kw.get('limit', 50)},0,null,null,true,{kw.get('cap', 100000)}"
            r = sql(f"with c as (select {CLAIMS}) select max(total) tot, count(*) nb from c, lateral {SCHEMA}.search_records({args})")
            return int(r[0]["tot"] or 0)

        def expect(where):
            return int(sql(f"select count(*) c from {SCHEMA}.records r where org_id='{ORG}' and ({where})")[0]["c"])

        txt = "lower((data->>'nom')||' '||(data->>'ville')||' '||(data->>'statut')||' '||(data->>'vide'))"
        fich = lambda cond: f"batch_id in (select id from {SCHEMA}.import_batches where {cond})"
        cases = [
            ("recherche dans les valeurs", got("ville12", {}), expect(f"position('ville12' in {txt})>0")),
            ("recherche insensible à la casse", got("VILLE12", {}), expect(f"position('ville12' in {txt})>0")),
            ("recherche : jamais dans les noms de colonnes", got("statut", {}), 0),
            ("recherche par nom de fichier", got("fichier_2.", {}), expect(fich("source_filename like 'fichier_2.%'"))),
            ("recherche par étiquette", got("vip", {}), 1),
            ("filtre contient", got("", {"ville": {"op": "contient", "value": "Ville1"}}), expect("lower(data->>'ville') like '%ville1%'")),
            ("filtre égal à", got("", {"ville": {"op": "égal à", "value": "ville7"}}), expect("lower(data->>'ville') = 'ville7'")),
            ("filtre ne contient pas", got("", {"ville": {"op": "ne contient pas", "value": "ville1"}}), expect("lower(data->>'ville') not like '%ville1%'")),
            ("filtre vide", got("", {"vide": {"op": "vide", "value": ""}}), expect("coalesce(data->>'vide','') = ''")),
            ("filtre non vide", got("", {"vide": {"op": "non vide", "value": ""}}), expect("coalesce(data->>'vide','') <> ''")),
            ("filtre Fichier source (contient)", got("", {"Fichier source": {"op": "contient", "value": "fichier_3"}}), expect(fich("source_filename like 'fichier_3%'"))),
            ("filtre Fichier source (ne contient pas)", got("", {"Fichier source": {"op": "ne contient pas", "value": "fichier_3"}}), expect("not (" + fich("source_filename like 'fichier_3%'") + ")")),
            ("filtre Étiquettes", got("", {"Étiquettes": {"op": "contient", "value": "vip"}}), 1),
            ("caractère % dans la valeur = littéral", got("", {"ville": {"op": "contient", "value": "%"}}), 0),
            ("apostrophe dans la recherche", got("l'", {}), 0),
            ("filtres combinés (ET)", got("nom1", {"ville": {"op": "contient", "value": "ville1"}, "statut": {"op": "égal à", "value": "actif"}}),
             expect(f"position('nom1' in {txt})>0 and lower(data->>'ville') like '%ville1%' and lower(data->>'statut') = 'actif'")),
            ("total plafonné (cap 10 => 11)", got("", {"statut": {"op": "égal à", "value": "actif"}}, cap=10), 11),
        ]
        # pagination par curseur : toutes les lignes, une seule fois chacune
        seen, after, pages = [], None, 0
        while True:
            a = "null,null" if after is None else f"'{after[0]}','{after[1]}'"
            rows = sql(
                f"with c as (select {CLAIMS}) select s.id, s.created_at from c, lateral "
                f"{SCHEMA}.search_records('{ORG}','','{{}}'::jsonb,1200,0,{a},false) s"
            )
            if not rows:
                break
            pages += 1
            seen += [r["id"] for r in rows]
            after = (rows[-1]["created_at"], rows[-1]["id"])
        cases.append(("curseur : 5000 lignes, sans doublon", len(seen) == len(set(seen)) == 5000 and pages == 5, True))
        # appartenance : un autre utilisateur ne voit rien
        other = sql(
            f"with c as (select set_config('request.jwt.claims','{{\"sub\":\"bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb\"}}', true)) "
            f"select count(*) n from c, lateral {SCHEMA}.search_records('{ORG}','','{{}}'::jsonb,50,0)"
        )
        cases.append(("non-membre : aucune ligne", int(other[0]["n"]), 0))
        cnt = sql(
            f"with c as (select set_config('request.jwt.claims','{{\"sub\":\"bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb\"}}', true)) "
            f"select {SCHEMA}.count_org_records('{ORG}') n from c"
        )
        cases.append(("non-membre : comptage 0", int(cnt[0]["n"]), 0))
        ok_cnt = sql(
            f"with c as (select {CLAIMS}) select {SCHEMA}.count_org_records('{ORG}') n from c"
        )
        cases.append(("membre : comptage exact", int(ok_cnt[0]["n"]), 5000))

        for label, a, b in cases:
            ok = a == b
            failures += 0 if ok else 1
            print(("OK  " if ok else "KO  ") + label + ("" if ok else f"  (obtenu {a}, attendu {b})"))
    finally:
        try:
            sql(f"drop schema if exists {SCHEMA} cascade")
        except Exception as exc:  # noqa: BLE001
            print(f"ATTENTION : schéma jetable {SCHEMA} à supprimer à la main : {exc}", file=sys.stderr)
    print(f"{len(cases) - failures}/{len(cases)} contrôles OK")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
