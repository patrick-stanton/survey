import pandas as pd
import pytest

from ucsurvey import catalog


def make_csv(tmp_path, text):
    p = tmp_path / "uc.csv"
    p.write_text(text)
    return p


def test_minting_and_passthrough(tmp_path):
    p = make_csv(
        tmp_path,
        "id,name,description,category,owner\n"
        "UC-007,Alpha,First,Cat1,alice\n"
        ",Beta,Second,Cat2,bob\n"
        ",Gamma,Third,Cat1,carol\n",
    )
    df = catalog.load_catalog(p)
    assert list(df["id"]) == ["UC-007", "UC-008", "UC-009"]
    assert df.attrs["minted"] == ["UC-008", "UC-009"]
    assert list(df["owner"]) == ["alice", "bob", "carol"]  # passthrough intact


def test_cameo_alias_columns(tmp_path):
    p = make_csv(tmp_path, "surveyId,Name,documentation\nUC-001,Alpha,Desc here\n")
    df = catalog.load_catalog(p)
    assert df.at[0, "id"] == "UC-001"
    assert df.at[0, "description"] == "Desc here"


def test_hash_changes_with_wording_only(tmp_path):
    base = "id,name,description,category\nUC-001,Alpha,First,Cat1\n"
    h1 = catalog.catalog_hash(catalog.load_catalog(make_csv(tmp_path, base)))
    reworded = base.replace("First", "First thing")
    h2 = catalog.catalog_hash(catalog.load_catalog(make_csv(tmp_path, reworded)))
    recategorized = base.replace("Cat1", "Cat2")
    h3 = catalog.catalog_hash(catalog.load_catalog(make_csv(tmp_path, recategorized)))
    assert h1 != h2
    assert h1 == h3  # category is cosmetic: same hash


def test_duplicate_names_rejected(tmp_path):
    p = make_csv(tmp_path, "id,name\nUC-001,Alpha\nUC-002,Alpha\n")
    with pytest.raises(catalog.CatalogError, match="Duplicate use-case names"):
        catalog.load_catalog(p)


def test_lineage_map_and_conflicts(tmp_path):
    p = make_csv(
        tmp_path,
        "id,name,supersedes\nUC-010,Merged,UC-001;UC-002\nUC-011,Kept,\n",
    )
    df = catalog.load_catalog(p)
    assert catalog.lineage_map(df) == {"UC-001": "UC-010", "UC-002": "UC-010"}

    bad = make_csv(tmp_path, "id,name,supersedes\nUC-010,A,UC-011\nUC-011,B,\n")
    with pytest.raises(catalog.CatalogError, match="still\\s+exists"):
        catalog.lineage_map(catalog.load_catalog(bad))


def test_example_catalog_loads():
    df = catalog.load_catalog("data/use_cases.sample.csv")
    assert len(df) == 60
    assert len(df.attrs["minted"]) == 60
    assert df["category"].nunique() == 6
