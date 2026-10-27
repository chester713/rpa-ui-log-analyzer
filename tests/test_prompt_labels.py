"""The four LLM prompts are labelled where they act: P1 and P2 as well as P3 and P4.

P1 proposes the activity-name attribute (attribute-selection page), P2 identifies the attribute
roles (shown with step 1), P3 abstracts UI activities (step 2) and P4 normalises them (step 3).
"""

from pathlib import Path

from flask import render_template

import app as webapp
from src.web.progressive import STAGE_LOGIC
from src.web.step_store import StepStore

README = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")


def test_attribute_selection_page_labels_prompt_p1() -> None:
    with webapp.app.test_request_context():
        html = render_template(
            "columns.html", columns=["Event", "Application"], detected_column="Event",
            llm_recommended=True, rows=[{"Event": "click", "Application": "Excel"}], filename="log.csv",
        )

    assert 'LLM · P1</span>' in html
    assert "The LLM (prompt P1) proposes which attribute holds the activity names" in html
    assert "recommended by the LLM (P1)" in html
    assert '" (LLM · P1)"' in html  # the suggested column header carries the label too


def _workspace_html(monkeypatch, tmp_path) -> str:
    monkeypatch.setattr("src.web.step_store._STORE_DIR", str(tmp_path / "progressive"))
    store = StepStore("a1")
    store.save("meta", {"aid": "a1", "history_id": "h1", "filename": "f.csv", "filepath": str(tmp_path / "none.csv")})
    store.save_step(1, {
        "segments": [{"segment_index": 0, "rows": [0], "labels": ["click"], "boundary": None}],
        "groups": [{"group_index": 0, "events": [{"event": "click", "row_index": 0, "attributes": {}}]}],
    })
    monkeypatch.setattr(
        webapp, "get_history",
        lambda: [{"id": "h1", "filename": "f.csv", "timestamp": "t", "progressive_aid": "a1"}],
    )
    return webapp.app.test_client().get("/workspace/h1").get_data(as_text=True)


def _section(html: str, key: str, next_key: str) -> str:
    start = html.index(f'data-stage="{key}"')
    return html[start:html.index(f'data-stage="{next_key}"', start)]


def test_step_1_shows_rules_and_the_llm_prompts_that_prepare_it(monkeypatch, tmp_path) -> None:
    html = _workspace_html(monkeypatch, tmp_path)

    step1 = _section(html, "segment", "abstract")
    assert ">Rules</span>" in step1
    assert ">LLM · attribute roles · P1, P2</span>" in step1
    assert "(prompt P2)" in html and "(prompt P1)" in html  # in the attribute-roles panel text


def test_steps_2_and_3_keep_their_p3_and_p4_labels(monkeypatch, tmp_path) -> None:
    html = _workspace_html(monkeypatch, tmp_path)

    assert ">LLM in place of the SME · P3</span>" in _section(html, "abstract", "normalise")
    assert ">LLM in place of the SME · P4</span>" in _section(html, "normalise", "implicit")


def test_steps_without_a_model_call_carry_no_llm_label(monkeypatch, tmp_path) -> None:
    html = _workspace_html(monkeypatch, tmp_path)

    for key, following in (("implicit", "match"), ("match", "environment"),
                           ("environment", "methods")):
        assert "LLM ·" not in _section(html, key, following)
    methods = html[html.index('data-stage="methods"'):]
    assert "LLM ·" not in methods[:methods.index("</section>")]


def test_step_explanation_names_p1_and_p2() -> None:
    roles = dict(STAGE_LOGIC["segment"])["Attribute roles"]

    assert "an LLM (prompt P2) identifies the role of each attribute" in roles
    assert "proposed by the LLM (prompt P1)" in roles


def test_readme_defines_all_four_prompts() -> None:
    for label in ("**P1**", "**P2**", "**P3**", "**P4**"):
        assert label in README
