import pandas as pd

from trieur.perf_cache import (
    build_final_df_cached,
    dataframe_content_hash,
    input_signature,
    local_upload_signature,
    rebuild_key,
    serialize_mappings_for_build,
    serialize_sheets_for_build,
)


def test_local_upload_signature_stable_same_content():
    content = b"abc,def\n1,2\n"
    sig1 = local_upload_signature("leads.csv", len(content), content)
    sig2 = local_upload_signature("leads.csv", len(content), content)
    assert sig1 == sig2


def test_local_upload_signature_changes_when_content_changes():
    a = local_upload_signature("leads.csv", 3, b"abc")
    b = local_upload_signature("leads.csv", 3, b"abd")
    assert a != b


def test_input_signature_uses_normalized_google_url():
    upload_sigs = [local_upload_signature("f.csv", 1, b"x")]
    sig1 = input_signature(upload_sigs, "  https://docs.google.com/spreadsheets/d/ABC/edit ")
    sig2 = input_signature(upload_sigs, "https://docs.google.com/spreadsheets/d/ABC/edit")
    assert sig1 == sig2


def test_rebuild_key_stable_with_mapping_order():
    loaded = (("file.csv", 5, "hash"), ("__google__", ""))
    active_keys = ["f1 :: s1", "f2 :: s2"]
    mappings_a = {
        "f1 :: s1": {"A": "NOM", "B": "(non assigne)"},
        "f2 :: s2": {"C": "EMAIL"},
    }
    mappings_b = {
        "f2 :: s2": {"C": "EMAIL"},
        "f1 :: s1": {"B": "(non assigne)", "A": "NOM"},
    }
    master_cols = ["NOM", "EMAIL", "Source Data"]
    assert rebuild_key(loaded, active_keys, mappings_a, master_cols) == rebuild_key(
        loaded, list(reversed(active_keys)), mappings_b, master_cols
    )


def test_dataframe_content_hash_changes_when_values_change():
    df1 = pd.DataFrame({"NOM": ["A"], "EMAIL": ["a@x.fr"]})
    df2 = pd.DataFrame({"NOM": ["A"], "EMAIL": ["b@x.fr"]})
    assert dataframe_content_hash(df1) != dataframe_content_hash(df2)


def test_build_final_df_cached_keeps_source_data_from_serialized_sheets():
    active_sheets = {
        "f.csv :: Feuil1": pd.DataFrame(
            {
                "NOM_SRC": ["Dupont"],
                "EMAIL_SRC": ["dupont@x.fr"],
                "__source_file__": ["f.csv"],
                "__source_sheet__": ["Feuil1"],
            }
        )
    }
    mappings = {"f.csv :: Feuil1": {"NOM_SRC": "NOM", "EMAIL_SRC": "EMAIL"}}
    built = build_final_df_cached(
        serialize_sheets_for_build(active_sheets),
        serialize_mappings_for_build(mappings),
        ("NOM", "EMAIL", "Source Data"),
    )
    assert built["NOM"].tolist() == ["Dupont"]
    assert built["EMAIL"].tolist() == ["dupont@x.fr"]
    assert built["Source Data"].tolist() == ["f.csv (Feuil1)"]
