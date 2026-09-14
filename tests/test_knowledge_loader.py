"""Teste pentru baza de cunostinte de marketing (principii de persuasiune)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ppc_agent.campaign_objective import CampaignObjective
from ppc_agent.copywriter.knowledge_loader import (
    MarketingKnowledgeBase,
    MarketingPrinciple,
    default_knowledge_base_path,
    frameworks_for_objective,
    load_knowledge_base,
    render_frameworks,
)
from ppc_agent.errors import KnowledgeBaseError


def test_default_knowledge_base_path_exists() -> None:
    assert default_knowledge_base_path().is_file()


def test_load_knowledge_base_default_has_both_objectives() -> None:
    knowledge_base = load_knowledge_base()
    assert len(knowledge_base.sales_frameworks) >= 3
    assert len(knowledge_base.lead_gen_frameworks) >= 3


def test_frameworks_for_sales_objective() -> None:
    knowledge_base = load_knowledge_base()
    principles = frameworks_for_objective(knowledge_base, CampaignObjective.SALES)
    names = {p.name for p in principles}
    assert any("Urgenta" in name for name in names)
    assert any("Raritate" in name for name in names)


def test_frameworks_for_lead_gen_objective() -> None:
    knowledge_base = load_knowledge_base()
    principles = frameworks_for_objective(knowledge_base, CampaignObjective.LEAD_GEN)
    names = {p.name for p in principles}
    assert any("PAS" in name for name in names)
    assert any("Dovada Sociala" in name for name in names)


def test_sales_and_lead_gen_frameworks_are_disjoint() -> None:
    knowledge_base = load_knowledge_base()
    sales_names = {p.name for p in knowledge_base.sales_frameworks}
    lead_gen_names = {p.name for p in knowledge_base.lead_gen_frameworks}
    assert sales_names.isdisjoint(lead_gen_names)


def test_render_frameworks_formats_as_bullet_list() -> None:
    principles = [
        MarketingPrinciple(name="A", guidance="explicatie A"),
        MarketingPrinciple(name="B", guidance="explicatie B"),
    ]
    rendered = render_frameworks(principles)
    assert rendered == "- A: explicatie A\n- B: explicatie B"


def test_load_knowledge_base_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(KnowledgeBaseError):
        load_knowledge_base(tmp_path / "nu_exista.json")


def test_load_knowledge_base_invalid_json_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(KnowledgeBaseError):
        load_knowledge_base(bad)


def test_load_knowledge_base_schema_mismatch_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad_schema.json"
    bad.write_text(json.dumps({"sales_frameworks": "nu e o lista"}), encoding="utf-8")
    with pytest.raises(KnowledgeBaseError):
        load_knowledge_base(bad)


def test_load_knowledge_base_custom_path(tmp_path: Path) -> None:
    custom = tmp_path / "custom_kb.json"
    custom.write_text(
        json.dumps(
            {
                "sales_frameworks": [{"name": "X", "guidance": "y"}],
                "lead_gen_frameworks": [],
            }
        ),
        encoding="utf-8",
    )
    knowledge_base = load_knowledge_base(custom)
    assert isinstance(knowledge_base, MarketingKnowledgeBase)
    assert knowledge_base.sales_frameworks[0].name == "X"
