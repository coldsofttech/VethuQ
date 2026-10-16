"""The licence request forms in `.github/ISSUE_TEMPLATE`: they match what VethuQ prefills, and
they say what a public issue must never hold."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from vethuq.licences import _FORMS, REQUEST_FIELDS

ROOT = Path(__file__).resolve().parents[3]
FORMS = ROOT / ".github" / "ISSUE_TEMPLATE"
LABELS = {
    "licence-request.yml": "licence-request",
    "topup-request.yml": "top-up-request",
    "rebind-request.yml": "rebind-request",
}


def form(name: str) -> dict:
    return yaml.safe_load((FORMS / name).read_text(encoding="utf-8"))


def fields(data: dict) -> dict[str, dict]:
    return {item["id"]: item for item in data["body"] if "id" in item}


@pytest.mark.parametrize("kind", sorted(_FORMS))
def test_every_request_kind_has_a_form_with_the_prefilled_fields(kind):
    template, title = _FORMS[kind]
    data = form(template)
    assert data["title"] == title and data["name"]
    ids = set(fields(data))
    assert "request_code" in ids and ids - {"public"} <= set(REQUEST_FIELDS)
    assert fields(data)["request_code"]["validations"]["required"] is True


@pytest.mark.parametrize("name, label", sorted(LABELS.items()))
def test_each_form_applies_its_label(name, label):
    assert form(name)["labels"] == [label]


@pytest.mark.parametrize("name", sorted(LABELS))
def test_each_form_says_it_is_public_and_what_not_to_paste(name):
    data = form(name)
    text = " ".join(
        item["attributes"].get("value", "") for item in data["body"] if item["type"] == "markdown"
    ).lower()
    for phrase in ("public", "do not paste", "licence key", "token", "e-mail", "file names"):
        assert phrase in text, phrase
    assert "never posted here" in text
    box = fields(data)["public"]
    assert box["type"] == "checkboxes" and box["attributes"]["options"][0]["required"] is True


@pytest.mark.parametrize("name", sorted(LABELS))
def test_no_form_asks_for_anything_personal(name):
    labels = " ".join(
        str(item["attributes"].get("label", "")).lower()
        for item in form(name)["body"]
        if "attributes" in item
    )
    for word in ("mail", "name", "phone", "address", "key", "token", "path", "password"):
        assert word not in labels.replace("licence key", ""), word


def test_the_chooser_links_to_the_privacy_doc_and_keeps_blank_issues():
    data = yaml.safe_load((FORMS / "config.yml").read_text(encoding="utf-8"))
    assert data["blank_issues_enabled"] is True
    assert all("licence-requests.md" in link["url"] for link in data["contact_links"])


def test_the_privacy_doc_exists_and_is_linked_from_the_forms():
    doc = (ROOT / "docs" / "licence-requests.md").read_text(encoding="utf-8")
    assert "never posted in the issue" in doc and "What must never be in a request" in doc
    for name in LABELS:
        assert "docs/licence-requests.md" in (FORMS / name).read_text(encoding="utf-8")
