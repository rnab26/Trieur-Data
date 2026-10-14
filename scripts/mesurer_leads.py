#!/usr/bin/env python3
"""Mesures de volume de la base Leads (chantier cockpit 6547bd6a) sur un schéma JETABLE.

La base est PARTAGÉE (Jarvis, cockpit) et le forfait gratuit passe en lecture seule à
500 Mo : chaque chargement vérifie la taille de la base et s'arrête au plafond fixé
(--plafond-mo, 340 par défaut). Données fictives, schéma supprimé à la fin.

    python3 scripts/mesurer_leads.py --lignes 200000
"""
import argparse
import json
import secrets
import sys
import time

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from verifier_leads_sql import CLAIMS, creer_schema, rows_json, sql, supprimer_schema  # noqa: E402


def taille_base_mo():
    return int(sql("select pg_database_size(current_database())/1024/1024 mb")[0]["mb"])


def charger_direct(S, debut, n, dept=None):
    """Insertion directe (sans passer par l'import) de n lignes fictives réalistes."""
    g = "g"
    sql(
        f"insert into {S}.leads (dept,cle,tel_mobile,tel_fixe,naissance,job_no,source_id,civilite,nom,prenom,email,adresse,cp,ville) "
        f"select d, 600000000+g, 600000000+g, case when g%10<3 then 100000000+g end, date '1950-01-01' + (g%20000), 1, 1+g%12, 1+g%2, "
        f"upper(substr(md5(g::text),1,6+g%5)), initcap(substr(md5((g+1)::text),1,5+g%4)), "
        f"substr(md5((g+2)::text),1,8+g%8)||'@'||(array['gmail.com','orange.fr','free.fr','hotmail.fr','sfr.fr'])[1+g%5], "
        f"(1+g%150)||' rue '||initcap(substr(md5((g+3)::text),1,10)), lpad(d::text,2,'0')||lpad((g%900)::text,3,'0'), "
        f"initcap(substr(md5((g+4)::text),1,6+g%7)) "
        f"from (select g, " + (f"{dept}::smallint d" if dept else "(case when 1+(g*31)%95=20 then 21 else 1+(g*31)%95 end)::smallint d") + f" from generate_series({debut},{debut+n-1}) g) t"
    )
    # statistiques tenues à jour comme le fait l'import
    sql(
        f"insert into {S}.leads_stats (dept, source_id, n) select d, (1+g%12)::smallint, count(*) "
        f"from (select g, " + (f"{dept}::smallint d" if dept else "(case when 1+(g*31)%95=20 then 21 else 1+(g*31)%95 end)::smallint d") + f" from generate_series({debut},{debut+n-1}) g) t "
        f"group by 1,2 on conflict (dept, source_id) do update set n = {S}.leads_stats.n + excluded.n"
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lignes", type=int, default=200000)
    ap.add_argument("--pas", type=int, default=50000)
    ap.add_argument("--plafond-mo", type=int, default=340)
    ap.add_argument("--pleins", default="", help="départements chargés à fond, ex. 75:630000,13:300000 (taille d'un département à 60 M)")
    ap.add_argument("--import-lots", type=int, default=20, help="lots de 5000 lignes via la fonction d'import (débit)")
    a = ap.parse_args()
    S = "test_leads_" + secrets.token_hex(4)
    avant = taille_base_mo()
    print(f"base avant : {avant} Mo ; schéma {S}", flush=True)
    try:
        creer_schema(S)
        base_schema = int(sql(f"select sum(pg_total_relation_size(c.oid))/1024 k from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='{S}'")[0]["k"])
        print(f"schéma vide : {base_schema} Ko", flush=True)
        for i in range(1, 13):
            sql(f"insert into {S}.leads_sources(nom) values ('source {i}')")
        sql(f"insert into {S}.leads_jobs(kind, filename) values ('import','charge')")
        # 1) débit de l'import RPC (le chemin réel)
        job = sql(f"with c as (select {CLAIMS}) select {S}.leads_job_creer('import', 1::smallint, 'debit.csv', null, null) j from c")[0]["j"]
        t0 = time.time()
        for k in range(a.import_lots):
            t1 = time.time()
            sql(f"with c as (select {CLAIMS}) select {S}.leads_importer_lot('{job['id']}', 1::smallint, {rows_json('m', 5000, start=1 + k * 5000)}, 5000) from c")
            if k in (0, a.import_lots - 1):
                print(f"  lot {k+1}: {time.time()-t1:.2f}s (aller-retour compris)", flush=True)
        dt = time.time() - t0
        n_imp = a.import_lots * 5000
        print(f"IMPORT RPC : {n_imp} lignes en {dt:.1f}s = {n_imp/dt:.0f} lignes/s (client distant, lots de 5000)", flush=True)
        # 2) chargement direct jusqu'au volume demandé
        deja = n_imp
        debut = 10_000_000
        while deja < a.lignes:
            if taille_base_mo() >= a.plafond_mo:
                print(f"PLAFOND {a.plafond_mo} Mo atteint : arrêt à {deja} lignes", flush=True)
                break
            n = min(a.pas, a.lignes - deja)
            t1 = time.time()
            charger_direct(S, debut, n)
            debut += n
            deja += n
            print(f"  chargé {deja} ({time.time()-t1:.1f}s) base={taille_base_mo()} Mo", flush=True)
        for spec in [x for x in a.pleins.split(",") if x]:
            d, n = (int(v) for v in spec.split(":"))
            fait = 0
            while fait < n:
                if taille_base_mo() >= a.plafond_mo:
                    print(f"PLAFOND {a.plafond_mo} Mo atteint dans le département {d} : arrêt à {fait}", flush=True)
                    break
                m = min(a.pas, n - fait)
                charger_direct(S, debut, m, dept=d)
                debut += m
                fait += m
            print(f"  département {d} : {fait} lignes ajoutées, base={taille_base_mo()} Mo", flush=True)
        for nom in ("leads_p075", "leads_p013"):
            try:
                sql(f"analyze {S}.{nom}")
            except RuntimeError:
                print(f"  (analyse de {nom} trop longue, ignorée)", flush=True)
        total = int(sql(f"select count(*) c from {S}.leads")[0]["c"])
        r = sql(
            f"select pg_total_relation_size('{S}.leads') tot, "
            f"(select sum(pg_relation_size(c.oid)) from pg_class c join pg_inherits i on i.inhrelid=c.oid where i.inhparent='{S}.leads'::regclass) heap, "
            f"(select sum(pg_relation_size(x.indexrelid)) from pg_index x join pg_inherits i on i.inhrelid=x.indrelid where i.inhparent='{S}.leads'::regclass) idx"
        )[0]
        tot, heap, idx = int(r["tot"]), int(r["heap"]), int(r["idx"])
        print(f"TAILLE {total} lignes : total {tot/1e6:.1f} Mo = tables {heap/1e6:.1f} + index {idx/1e6:.1f} ; "
              f"{tot/total:.0f} octets/ligne (tables {heap/total:.0f} + index {idx/total:.0f})", flush=True)
        # 3) requêtes
        def temps(label, query, n=3):
            ts = []
            for _ in range(n):
                t = time.time()
                sql(f"with c as (select {CLAIMS}) {query}")
                ts.append(time.time() - t)
            print(f"  {label}: " + " / ".join(f"{x*1000:.0f} ms" for x in ts) + " (aller-retour compris)", flush=True)
        print("REQUÊTES (aller-retour client compris, 3 passages) :", flush=True)
        temps("aperçu 300 lignes (tous départements)", f"select {S}.leads_lire(null, null, '{{}}'::jsonb, null, null, 300, 3000, 'apercu') from c")
        temps("aperçu 300 lignes, département 75", f"select {S}.leads_lire(array[75]::smallint[], null, '{{}}'::jsonb, null, null, 300, 3000, 'apercu') from c")
        temps("aperçu filtre rare (ville) dpt 75", f"select {S}.leads_lire(array[75]::smallint[], null, '{{\"ville\":{{\"op\":\"égal à\",\"value\":\"zzzz\"}}}}'::jsonb, null, null, 300, 3000, 'apercu') from c")
        temps("comptage instantané (stats), 20 dpts, sources exclues", f"select {S}.leads_compter(array[1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,21]::smallint[], array[2,5]::smallint[]) from c")
        t = time.time()
        n_c, dept, apres, appels = 0, None, None, 0
        while True:
            d = "null" if dept is None else str(dept)
            ap_ = "null" if apres is None else f"'{apres}'"
            rr = sql(f"with c as (select {CLAIMS}) select {S}.leads_lire(array[75]::smallint[], array[2]::smallint[], '{{}}'::jsonb, {d}::smallint, {ap_}, null, 100000, 'compte') r from c")[0]["r"]
            n_c += rr["n"]
            appels += 1
            if not rr["suite"]:
                break
            dept, apres = rr["suite"]["dept"], rr["suite"]["apres"]
        print(f"  comptage exact dpt 75 (1re lecture après import) : {n_c} lignes en {time.time()-t:.1f}s, {appels} requêtes", flush=True)
        temps("comptage exact dpt 75 (2e lecture)", f"select {S}.leads_lire(array[75]::smallint[], array[2]::smallint[], '{{}}'::jsonb, null, null, null, 100000, 'compte') from c")
        # export d'un département complet en CSV (fenêtres)
        t = time.time()
        n_csv, octets, dept, apres, appels = 0, 0, None, None, 0
        while True:
            d = "null" if dept is None else str(dept)
            ap_ = "null" if apres is None else f"'{apres}'"
            rr = sql(f"with c as (select {CLAIMS}) select {S}.leads_lire(array[75,13]::smallint[], array[2]::smallint[], '{{}}'::jsonb, {d}::smallint, {ap_}, null, 1000, 'csv') r from c")[0]["r"]
            n_csv += rr["n"]
            octets += len((rr["csv"] or "").encode())
            appels += 1
            if not rr["suite"]:
                break
            dept, apres = rr["suite"]["dept"], rr["suite"]["apres"]
        dt = time.time() - t
        print(f"EXPORT CSV départements 75+13 : {n_csv} lignes, {octets/1e6:.1f} Mo, {appels} requêtes, {dt:.1f}s = {n_csv/dt:.0f} lignes/s (aller-retour compris)", flush=True)
        print(f"base à la fin : {taille_base_mo()} Mo", flush=True)
    finally:
        supprimer_schema(S)
        reste = sql(f"select count(*) c from pg_namespace where nspname='{S}'")[0]["c"]
        print(f"schéma supprimé (restant : {reste}) ; base après : {taille_base_mo()} Mo", flush=True)


if __name__ == "__main__":
    main()
