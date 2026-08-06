"""Filtres code postal / departements (pur Python), et deduplication."""


def dedupe_dataframe(df, column, keep="first"):
    """Supprime les lignes en doublon sur `column`.

    keep="first"    : garde la premiere ligne rencontree (ordre d'origine).
    keep="complete" : garde, parmi chaque groupe de doublons, la ligne ayant
                       le moins de valeurs vides (NaN) sur l'ensemble des
                       colonnes -- utile quand plusieurs imports partiels du
                       meme contact se completent mutuellement.
    """
    if column not in df.columns:
        return df
    if keep == "complete":
        order = df.notna().sum(axis=1).sort_values(ascending=False).index
        deduped = df.loc[order].drop_duplicates(subset=[column], keep="first")
        return deduped.sort_index()
    return df.drop_duplicates(subset=[column], keep="first")


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
