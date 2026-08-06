"""Filtres code postal / departements (pur Python), et deduplication."""
import pandas as pd


def _non_empty_mask(df, column):
    """Lignes ou `column` a une VRAIE valeur (ni NaN, ni chaine vide).

    Important : pandas .duplicated()/.drop_duplicates() considerent par
    defaut toutes les valeurs NaN comme egales entre elles -- sans cette
    exclusion, des lignes juste VIDES sur la colonne choisie seraient
    traitees comme des doublons les unes des autres, ce qui n'a pas de sens
    (une case vide n'est pas un doublon d'une autre case vide)."""
    return df[column].notna() & (df[column].astype(str).str.strip() != "")


def dedupe_dataframe(df, column, keep="first"):
    """Supprime les lignes en doublon sur `column` (les lignes SANS valeur
    sur cette colonne sont toujours conservees, voir _non_empty_mask).

    keep="first"    : garde la premiere ligne rencontree (ordre d'origine).
    keep="complete" : garde, parmi chaque groupe de doublons, la ligne ayant
                       le moins de valeurs vides (NaN) sur l'ensemble des
                       colonnes -- utile quand plusieurs imports partiels du
                       meme contact se completent mutuellement.
    """
    if column not in df.columns:
        return df
    non_empty = _non_empty_mask(df, column)
    with_value = df[non_empty]
    without_value = df[~non_empty]
    if keep == "complete":
        order = with_value.notna().sum(axis=1).sort_values(ascending=False).index
        deduped = with_value.loc[order].drop_duplicates(subset=[column], keep="first")
    else:
        deduped = with_value.drop_duplicates(subset=[column], keep="first")
    return pd.concat([deduped, without_value]).sort_index()


def duplicate_groups(df, column):
    """Renvoie la liste des groupes de doublons sur `column` : chaque groupe
    est un tuple (valeur, [index des lignes concernees]), pour les valeurs
    apparaissant sur PLUS D'UNE ligne (les cases vides ne comptent jamais
    comme un groupe -- voir _non_empty_mask). Trie par valeur pour un
    affichage stable."""
    if column not in df.columns:
        return []
    sub = df[_non_empty_mask(df, column)]
    groups = []
    for value, idx in sub.groupby(column, sort=True).groups.items():
        idx_list = list(idx)
        if len(idx_list) > 1:
            groups.append((value, idx_list))
    return groups


def most_complete_row_index(df, indices):
    """Parmi `indices` (lignes d'un meme groupe de doublons), renvoie
    l'index de la ligne ayant le moins de valeurs vides -- le choix par
    defaut propose a l'utilisateur en revue manuelle."""
    counts = df.loc[indices].notna().sum(axis=1)
    return counts.idxmax()


def dedupe_dataframe_manual(df, column, keep_indices):
    """Applique une selection MANUELLE de deduplication sur `column` : les
    lignes qui ne font partie d'AUCUN groupe de doublons (ou sans valeur)
    sont toujours conservees ; parmi les lignes qui font partie d'un
    groupe de doublons, seules celles listees dans `keep_indices` sont
    conservees (un index choisi par groupe, cf duplicate_groups)."""
    if column not in df.columns:
        return df
    non_empty = _non_empty_mask(df, column)
    dup_mask = df[column].duplicated(keep=False) & non_empty
    keep = (~dup_mask) | df.index.isin(keep_indices)
    return df[keep]


def normalize_cp(value):
    s = str(value).strip()
    s = s.split(".")[0]
    if not s.isdigit():
        return None
    if len(s) == 4:
        s = "0" + s
    if len(s) != 5:
        return None
    return s


def cp_matches_prefix(cp_value, prefixes):
    cp5 = normalize_cp(cp_value)
    if cp5 is None:
        return False
    return cp5[:2] in prefixes
