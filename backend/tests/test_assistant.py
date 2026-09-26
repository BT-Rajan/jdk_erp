"""JDK Assistant: read-only, permission-scoped lookups; Claude and DeepSeek
providers (faked here -- no network); fixed cacheable prompt; answer
cache for how-to answers only; Admin-only encrypted key."""

import json
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.api import quotations as quotations_api
from app.core.roles import ADMIN, TEAM_MEMBER
from app.core.security import hash_password
from app.core.timezone import JDK_TIMEZONE
from app.models.audit_event import ASSISTANT_KEY_UPDATED, AuditEvent
from app.models.customer import Customer
from app.models.organisation import Organisation
from app.models.user import User
from app.services import assistant_lookup_service, assistant_service, working_calendar_service

MONDAY_9AM_KUWAIT = datetime(2026, 9, 28, 9, 0, tzinfo=JDK_TIMEZONE)
CLAUDE_KEY = "sk-ant-test-key-1234"


def _user(db_session, organisation, username, role):
    user = User(
        organisation_id=organisation.id, role=role, full_name=username.title(), email=f"{username}@example.com",
        username=username, password_hash=hash_password("Str0ng!Pass"), is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return user


def _headers(client, username):
    login = client.post("/api/auth/login", json={"username": username, "password": "Str0ng!Pass"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


class FakeClaude:
    """Stands in for anthropic.Anthropic: replays scripted responses and
    records every request."""

    requests: list[dict] = []
    script: list = []

    def __init__(self, **kwargs):
        self.messages = self

    def create(self, **kwargs):
        FakeClaude.requests.append(json.loads(json.dumps(kwargs, default=lambda o: o.__dict__)))
        return FakeClaude.script.pop(0)


def _text(text):
    return SimpleNamespace(
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=10, cache_creation_input_tokens=0, cache_read_input_tokens=5000, output_tokens=20),
    )


def _lookup(name, args):
    return SimpleNamespace(
        stop_reason="tool_use",
        content=[SimpleNamespace(type="tool_use", id="toolu_1", name=name, input=args)],
        usage=SimpleNamespace(input_tokens=10, cache_creation_input_tokens=0, cache_read_input_tokens=5000, output_tokens=20),
    )


@pytest.fixture()
def setup(db_session, organisation, widget_product, monkeypatch):
    for module in (working_calendar_service, quotations_api, assistant_service):
        monkeypatch.setattr(module, "now_jdk", lambda: MONDAY_9AM_KUWAIT)
    monkeypatch.setattr(assistant_service.anthropic, "Anthropic", FakeClaude)
    FakeClaude.requests, FakeClaude.script = [], []
    assistant_service.clear_answer_cache()
    a = _user(db_session, organisation, "salesman_a", TEAM_MEMBER)
    _user(db_session, organisation, "salesman_b", TEAM_MEMBER)
    _user(db_session, organisation, "boss", ADMIN)
    customer = Customer(organisation_id=organisation.id, code="300001", name="Acme Trading", assigned_to_user_id=a.id)
    widget_product.min_selling_price, widget_product.max_selling_price = Decimal("90"), Decimal("110")
    db_session.add(customer)
    db_session.commit()
    body = {
        "customer_id": customer.id,
        "requested_delivery_date": "2026-10-05",
        "lines": [{"product_id": widget_product.id, "quantity": "3", "unit_of_measure_id": widget_product.unit_of_measure_id, "unit_price": "100"}],
    }
    # The quotation itself is created through the API in each test that needs it.
    return customer, body


def _set_key(client, key=CLAUDE_KEY):
    return client.put("/api/assistant/settings", json={"api_key": key}, headers=_headers(client, "boss"))


def _ask(client, username, message, history=None):
    return client.post("/api/assistant/chat", json={"message": message, "history": history or []}, headers=_headers(client, username))


def test_only_admin_sets_the_key_which_is_stored_encrypted(client, db_session, organisation, setup):
    assert _ask(client, "salesman_a", "How do I create a quotation?").json()["reply"] == assistant_service.NOT_CONFIGURED
    assert client.put("/api/assistant/settings", json={"api_key": CLAUDE_KEY}, headers=_headers(client, "salesman_a")).status_code == 403
    assert client.get("/api/assistant/settings", headers=_headers(client, "salesman_a")).status_code == 403

    saved = _set_key(client).json()
    assert saved == {"configured": True, "provider": "claude", "key_hint": "...1234"}
    stored = db_session.get(Organisation, organisation.id).ai_api_key_encrypted
    assert stored and CLAUDE_KEY not in stored
    event = db_session.query(AuditEvent).filter(AuditEvent.action == ASSISTANT_KEY_UPDATED).one()
    assert CLAUDE_KEY not in (event.details or "") and "claude" in event.details
    assert _set_key(client, "sk-deepseek-9999").json()["provider"] == "deepseek"
    assert _set_key(client, "").json() == {"configured": False, "provider": None, "key_hint": None}


def test_status_is_looked_up_live_within_the_users_scope(client, db_session, setup):
    customer, body = setup
    quotation = client.post("/api/quotations", json=body, headers=_headers(client, "salesman_a")).json()
    _set_key(client)

    FakeClaude.script = [_lookup("find_quotations", {"number": quotation["quotation_number"]}), _text("It is a draft.")]
    reply = _ask(client, "salesman_a", f"What's the status of quotation {quotation['quotation_number']}?").json()
    assert reply == {"reply": "It is a draft.", "cached": False}
    first, second = FakeClaude.requests
    # Haiku 4.5, cached fixed prefix, lookups offered; who/when only in the user turn.
    assert first["model"] == "claude-haiku-4-5" and first["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert first["system"][0]["text"] == assistant_service.SYSTEM_PROMPT
    assert [t["name"] for t in first["tools"]] == sorted(t["name"] for t in assistant_lookup_service.TOOLS)
    assert "Asked by Salesman_A (team_member)" in first["messages"][-1]["content"]
    result = json.loads(second["messages"][-1]["content"][0]["content"])
    assert result["results"][0]["number"] == quotation["quotation_number"]
    assert result["results"][0]["status"] == "draft" and result["results"][0]["customer"] == "Acme Trading"

    # Another salesman's lookup of the same number finds nothing.
    FakeClaude.script = [_lookup("find_quotations", {"number": quotation["quotation_number"]}), _text("Not found.")]
    _ask(client, "salesman_b", "Status of that quotation?")
    assert "Nothing found" in FakeClaude.requests[-1]["messages"][-1]["content"][0]["content"]
    # A status answer is never cached: asking again calls the model again.
    FakeClaude.script = [_lookup("find_quotations", {"number": quotation["quotation_number"]}), _text("It is a draft.")]
    assert _ask(client, "salesman_a", f"What's the status of quotation {quotation['quotation_number']}?").json()["cached"] is False


def test_how_to_answers_are_cached_per_role_but_not_mid_conversation(client, setup):
    _set_key(client)
    FakeClaude.script = [_text("- Open **Sales > Quotations**\n- Click **New Quotation**")]
    first = _ask(client, "salesman_a", "How do I create a quotation?").json()
    again = _ask(client, "salesman_b", "how do I create a quotation").json()
    assert (first["cached"], again["cached"], again["reply"]) == (False, True, first["reply"])
    assert len(FakeClaude.requests) == 1

    FakeClaude.script = [_text("Admin answer.")]
    assert _ask(client, "boss", "How do I create a quotation?").json()["cached"] is False  # different role
    FakeClaude.script = [_text("Follow-up answer.")]
    history = [{"role": "user", "content": "Hi"}, {"role": "assistant", "content": "Hello"}]
    assert _ask(client, "salesman_a", "How do I create a quotation?", history).json()["cached"] is False
    assert len(FakeClaude.requests) == 3


def test_deepseek_key_uses_deepseek_with_the_same_fixed_prompt(client, setup, monkeypatch):
    customer, body = setup
    quotation = client.post("/api/quotations", json=body, headers=_headers(client, "salesman_a")).json()
    _set_key(client, "sk-deepseek-9999")
    sent = []
    replies = [
        {"choices": [{"message": {"content": "", "tool_calls": [
            {"id": "call_1", "type": "function", "function": {"name": "find_quotations", "arguments": json.dumps({"party": "acme"})}}
        ]}}], "usage": {}},
        {"choices": [{"message": {"content": "One draft quotation."}}], "usage": {}},
    ]

    def fake_request(api_key, body):
        sent.append(json.loads(json.dumps(body)))
        return replies.pop(0)

    monkeypatch.setattr(assistant_service, "_deepseek_request", fake_request)
    assert _ask(client, "salesman_a", "Any quotations for Acme?").json()["reply"] == "One draft quotation."
    assert sent[0]["model"] == "deepseek-chat" and sent[0]["messages"][0] == {"role": "system", "content": assistant_service.SYSTEM_PROMPT}
    tool_result = json.loads(sent[1]["messages"][-1]["content"])
    assert tool_result["results"][0]["number"] == quotation["quotation_number"]
    assert FakeClaude.requests == []


def test_lookups_only_read_and_respect_module_permissions(client, db_session, setup):
    salesman = db_session.query(User).filter(User.username == "salesman_a").one()
    for tool in assistant_lookup_service.TOOLS:
        assistant_lookup_service.run(db_session, salesman, tool["name"], {"number": "26", "item": "Widget"})
        assert not (db_session.new or db_session.dirty or db_session.deleted)
    for name in ("find_purchase_orders", "find_rfqs", "find_supplier_payments", "get_stock"):
        assert "do not have access" in assistant_lookup_service.run(db_session, salesman, name, {"item": "Widget"})
    assert "Unknown lookup" in assistant_lookup_service.run(db_session, salesman, "delete_everything", {})


def test_write_requests_get_the_fixed_refusal_in_the_prompt(setup):
    # The refusal contract is part of the fixed instructions sent every time.
    assert assistant_service.WRITE_REFUSAL in assistant_service.SYSTEM_PROMPT
    assert "not authorised" in assistant_service.WRITE_REFUSAL
    assert assistant_service.OUT_OF_SCOPE_REFUSAL in assistant_service.SYSTEM_PROMPT
