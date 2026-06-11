from __future__ import annotations

import base64
import hashlib
import uuid
from datetime import timedelta
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models.chat import ChatSession
from app.models.desktop_command import DesktopCommand
from app.models.desktop_command_approval_grant import DesktopCommandApprovalGrant
from app.models.desktop_command_envelope_nonce import DesktopCommandEnvelopeNonce
from app.models.desktop_command_event import DesktopCommandEvent
from app.models.device_registry import DeviceRegistry
from app.models.tenant import Tenant
from app.models.tenant_features import TenantFeatures
from app.models.user import User
from app.services import desktop_control_service
from app.services.desktop_control_service import (
    DEFAULT_COMMAND_PENDING_TTL_SECONDS,
    DesktopCommandClaim,
    DesktopCommandApprovalGrantCreate,
    DesktopCommandCompletion,
    DesktopCommandEnqueue,
    DesktopCommandStop,
    _utcnow,
    _verify_envelope_signature,
    claim_next_desktop_command,
    complete_desktop_command,
    create_desktop_approval_grant,
    display_safe_command_status,
    enqueue_desktop_command,
    get_desktop_command_status_snapshot,
    preempt_desktop_commands_for_stop,
)

TENANT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
TENANT_ID_2 = uuid.UUID("11111111-1111-1111-1111-111111111112")
USER_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
USER_ID_2 = uuid.UUID("22222222-2222-2222-2222-222222222223")
SESSION_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
SESSION_ID_2 = uuid.UUID("33333333-3333-3333-3333-333333333334")
SHELL_ID = "desktop-44444444-4444-4444-4444-444444444444"
OTHER_SHELL_ID = "desktop-55555555-5555-5555-5555-555555555555"
DEVICE_ID = uuid.UUID("88888888-8888-8888-8888-888888888888")
DEVICE_ID_2 = uuid.UUID("88888888-8888-8888-8888-888888888889")
DEVICE_TOKEN = "device-token-test"
ED25519_PRIVATE_KEY_BYTES = bytes(range(32))
CANARY_BUNDLE_ID = "com.example.LunaCanaryTarget"
OTHER_CANARY_BUNDLE_ID = "com.example.OtherCanaryTarget"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


@pytest.fixture(autouse=True)
def _default_hmac_envelope_signing(monkeypatch):
    """Pin HMAC-SHA256 envelope signing for this lifecycle suite.

    The global default flipped to Ed25519 (M-11 step 1), which fail-closes (no
    `command_envelope` issued) without a private key. These tests exercise the
    generic command lifecycle (claim / complete / nonce / replay / lease) and use
    HMAC-SHA256 as the no-key signer that still produces a signed envelope. Tests
    that specifically exercise the Ed25519 path override this locally via
    `patch.object(... "DESKTOP_COMMAND_ENVELOPE_SIGNING_ALGORITHM", "Ed25519")`.
    """
    monkeypatch.setattr(
        desktop_control_service.settings,
        "DESKTOP_COMMAND_ENVELOPE_SIGNING_ALGORITHM",
        "HMAC-SHA256",
        raising=False,
    )


@pytest.fixture(name="db_session")
def db_session_fixture():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    yield db
    db.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(name="seeded")
def seeded_fixture(db_session: Session):
    tenant = Tenant(id=TENANT_ID, name="Desktop Command Tenant")
    user = User(
        id=USER_ID,
        tenant_id=TENANT_ID,
        email="desktop-command@example.test",
        hashed_password="x",
    )
    session = ChatSession(
        id=SESSION_ID,
        tenant_id=TENANT_ID,
        owner_user_id=USER_ID,
        title="Desktop command session",
    )
    device = DeviceRegistry(
        id=DEVICE_ID,
        tenant_id=TENANT_ID,
        device_id=f"{TENANT_ID}-desktop-{SHELL_ID.removeprefix('desktop-')}",
        device_name="Luna Desktop",
        device_type="desktop",
        status="online",
        device_token_hash=hashlib.sha256(DEVICE_TOKEN.encode()).hexdigest(),
        capabilities=["can_observe"],
        config={"shell_id": SHELL_ID},
    )
    # PR4b: native-control actuation is gated by per-tenant capability flags. The
    # seeded tenant is an ENABLED operator tenant (master + pointer + keyboard on);
    # tests that exercise the gate flip these off explicitly.
    features = TenantFeatures(
        tenant_id=TENANT_ID,
        desktop_control_enabled=True,
        pointer_control_enabled=True,
        keyboard_control_enabled=True,
        background_control_enabled=True,
        # PR4c: per-tenant target allowlist (effective = per-tenant ∩ floor). The
        # seeded operator opts the canary bundle in so native-control tests (which
        # patch the floor to [CANARY_BUNDLE_ID]) resolve effective=[CANARY];
        # allowlist tests flip this to [] / a non-floor bundle explicitly.
        native_control_target_allowlist=[CANARY_BUNDLE_ID],
    )
    db_session.add_all([tenant, user, session, device, features])
    db_session.commit()
    return user


def _presence(can_observe: bool = True, *, device_id: uuid.UUID = DEVICE_ID):
    return {
        "active_shell": SHELL_ID,
        "connected_shells": [SHELL_ID],
        "shell_capabilities": {
            SHELL_ID: {
                "can_observe": can_observe,
                "can_stop": True,
                "can_control_pointer": False,
                "can_control_keyboard": False,
            },
        },
        "shell_devices": {SHELL_ID: str(device_id)},
        "shell_permission_readiness": {
            SHELL_ID: {
                "screen_recording": {"status": "granted"},
                "accessibility": {"status": "granted"},
                "observed_at": _utcnow().isoformat(),
            },
        },
    }


def _enqueue(db: Session, *, nonce: str | None = None, grant: bool = True):
    command = enqueue_desktop_command(
        db,
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        request=DesktopCommandEnqueue(
            session_id=SESSION_ID,
            action="capture_screenshot",
            tool_name="desktop_observe_screen",
            shell_id=None,
            nonce=nonce,
            payload={
                "reason": "smoke",
                "raw_clipboard_text": "must not persist",
                "screenshot_base64": "must not persist",
            },
        ),
    )[0]
    if grant:
        existing_grant = db.query(DesktopCommandApprovalGrant).filter(
            DesktopCommandApprovalGrant.tenant_id == TENANT_ID,
            DesktopCommandApprovalGrant.desktop_command_id == command.id,
            DesktopCommandApprovalGrant.status == "active",
        ).first()
        if existing_grant is None:
            create_desktop_approval_grant(
                db,
                tenant_id=TENANT_ID,
                user_id=USER_ID,
                request=DesktopCommandApprovalGrantCreate(
                    session_id=SESSION_ID,
                    desktop_command_id=command.id,
                    risk_tier="observe",
                    capability=command.capability,
                    expires_in_seconds=60,
                ),
            )
        db.refresh(command)
    return command


def _native_pending_command(
    db: Session,
    *,
    nonce: str,
    bundle_id: str = CANARY_BUNDLE_ID,
    action: str = "pointer_click",
):
    now = _utcnow()
    command = DesktopCommand(
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        session_id=SESSION_ID,
        shell_id=SHELL_ID,
        device_id=DEVICE_ID,
        capability="pointer_control",
        status="pending",
        source="test",
        nonce=nonce,
        payload={
            "action": action,
            "tool_name": "desktop_pointer_click",
            "mode": "control_locked",
            "target": {
                "bundle_id": bundle_id,
                "action": action,
                "window_title_pattern": "Luna Canary",
            },
        },
        created_at=now,
        updated_at=now,
    )
    db.add(command)
    db.commit()
    db.refresh(command)
    return command


def _completion_metadata(db: Session, command: DesktopCommand, **metadata):
    db.refresh(command)
    envelope = (command.payload or {}).get("command_envelope")
    assert envelope, "claimed command should have a signed envelope"
    return {
        **metadata,
        "envelope_nonce": envelope["nonce"],
    }


def _seed_second_tenant(db_session: Session):
    tenant = Tenant(id=TENANT_ID_2, name="Second Desktop Command Tenant")
    user = User(
        id=USER_ID_2,
        tenant_id=TENANT_ID_2,
        email="desktop-command-2@example.test",
        hashed_password="x",
    )
    session = ChatSession(
        id=SESSION_ID_2,
        tenant_id=TENANT_ID_2,
        owner_user_id=USER_ID_2,
        title="Second desktop command session",
    )
    device = DeviceRegistry(
        id=DEVICE_ID_2,
        tenant_id=TENANT_ID_2,
        device_id=f"{TENANT_ID_2}-desktop-{SHELL_ID.removeprefix('desktop-')}",
        device_name="Luna Desktop 2",
        device_type="desktop",
        status="online",
        device_token_hash=hashlib.sha256("second-token".encode()).hexdigest(),
        capabilities=["can_observe"],
        config={"shell_id": SHELL_ID},
    )
    features = TenantFeatures(
        tenant_id=TENANT_ID_2,
        desktop_control_enabled=True,
        pointer_control_enabled=False,
        keyboard_control_enabled=False,
        background_control_enabled=False,
        native_control_target_allowlist=[],
    )
    db_session.add_all([tenant, user, session, device, features])
    db_session.commit()
    return user


def test_enqueue_and_claim_command_sets_device_bound_lease(db_session, seeded):
    with patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value=_presence(),
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        command = _enqueue(db_session, nonce="nonce-1")
        claimed, event, _session_event = claim_next_desktop_command(
            db_session,
            user=seeded,
            device_token=DEVICE_TOKEN,
            claim=DesktopCommandClaim(session_id=SESSION_ID, shell_id=SHELL_ID, lease_seconds=30),
        )

    assert claimed is not None
    assert claimed.id == command.id
    assert claimed.status == "claimed"
    assert claimed.lease_owner_shell_id == SHELL_ID
    assert claimed.lease_expires_at is not None
    assert claimed.device_id == DEVICE_ID
    assert event.event_type == "desktop_command_claimed"
    assert event.outcome == "started"
    reloaded = db_session.query(DesktopCommand).filter(DesktopCommand.id == command.id).one()
    assert reloaded.status == "claimed"
    assert "must not persist" not in str(reloaded.payload)


def test_claim_issues_signed_command_envelope_and_nonce_row(db_session, seeded):
    with patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value=_presence(),
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        command = _enqueue(db_session, nonce="nonce-envelope-issued")
        claimed, event, _session_event = claim_next_desktop_command(
            db_session,
            user=seeded,
            device_token=DEVICE_TOKEN,
            claim=DesktopCommandClaim(session_id=SESSION_ID, shell_id=SHELL_ID, lease_seconds=30),
        )

    envelope = claimed.payload["command_envelope"]
    assert envelope["schema"] == "agentprovision.desktop_command_envelope.v1"
    assert envelope["signed"] is True
    assert envelope["signature_alg"] == "HMAC-SHA256"
    assert envelope["policy_version"] == 1
    assert envelope["tenant_id"] == str(TENANT_ID)
    assert envelope["user_id"] == str(USER_ID)
    assert envelope["session_id"] == str(SESSION_ID)
    assert envelope["desktop_command_id"] == str(command.id)
    assert envelope["shell_id"] == SHELL_ID
    assert envelope["device_id"] == str(DEVICE_ID)
    assert envelope["action"] == "capture_screenshot"
    assert envelope["capability"] == "screenshot"
    assert envelope["approval_id"] == str(claimed.approval_id)
    assert envelope["approval_risk_tier"] == "observe"
    assert envelope["nonce"]
    assert envelope["signature"]
    assert claimed.payload["approval"]["approval_id"] == str(claimed.approval_id)
    assert claimed.payload["approval"]["risk_tier"] == "observe"
    grant = db_session.query(DesktopCommandApprovalGrant).filter(
        DesktopCommandApprovalGrant.id == claimed.approval_id,
    ).one()
    assert claimed.payload["approval"]["expires_at_ms"] == int(
        grant.expires_at.timestamp() * 1000
    )
    assert grant.status == "consumed"
    assert grant.remaining_actions == 0
    nonce_row = db_session.query(DesktopCommandEnvelopeNonce).filter(
        DesktopCommandEnvelopeNonce.tenant_id == TENANT_ID,
        DesktopCommandEnvelopeNonce.nonce == envelope["nonce"],
    ).one()
    assert nonce_row.desktop_command_id == command.id
    assert nonce_row.session_id == SESSION_ID
    assert nonce_row.shell_id == SHELL_ID
    assert nonce_row.device_id == DEVICE_ID
    assert nonce_row.status == "issued"
    assert event.event_metadata["envelope_nonce"] == envelope["nonce"]
    assert event.event_metadata["envelope_policy_version"] == 1
    assert len(event.event_metadata["envelope_hash"]) == 64


def test_native_control_grant_rejects_missing_or_unallowlisted_target(db_session, seeded):
    with patch.object(
        desktop_control_service.settings,
        "DESKTOP_CONTROL_CANARY_BUNDLE_ALLOWLIST",
        [],
    ), patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value=_presence(),
    ):
        with pytest.raises(HTTPException) as missing:
            create_desktop_approval_grant(
                db_session,
                tenant_id=TENANT_ID,
                user_id=USER_ID,
                request=DesktopCommandApprovalGrantCreate(
                    session_id=SESSION_ID,
                    risk_tier="native_control",
                    capability="pointer_control",
                    target_binding={"action": "pointer_click"},
                ),
            )
        with pytest.raises(HTTPException) as unallowlisted:
            create_desktop_approval_grant(
                db_session,
                tenant_id=TENANT_ID,
                user_id=USER_ID,
                request=DesktopCommandApprovalGrantCreate(
                    session_id=SESSION_ID,
                    risk_tier="native_control",
                    capability="pointer_control",
                    target_binding={
                        "bundle_id": CANARY_BUNDLE_ID,
                        "action": "pointer_click",
                    },
                ),
            )

    assert missing.value.status_code == 422
    assert unallowlisted.value.status_code == 422
    assert "target not allowlisted" in str(unallowlisted.value.detail).lower()
    assert (
        db_session.query(DesktopCommandApprovalGrant)
        .filter(DesktopCommandApprovalGrant.risk_tier == "native_control")
        .count()
        == 0
    )


def test_native_control_grant_persists_only_allowlisted_target(db_session, seeded):
    with patch.object(
        desktop_control_service.settings,
        "DESKTOP_CONTROL_CANARY_BUNDLE_ALLOWLIST",
        [CANARY_BUNDLE_ID],
    ), patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value=_presence(),
    ):
        grant = create_desktop_approval_grant(
            db_session,
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            request=DesktopCommandApprovalGrantCreate(
                session_id=SESSION_ID,
                risk_tier="native_control",
                capability="pointer_control",
                target_binding={
                    "bundle_id": CANARY_BUNDLE_ID,
                    "action": "pointer_click",
                    "window_title_pattern": "Luna Canary",
                },
            ),
        )

    assert grant.target_binding == {
        "bundle_id": CANARY_BUNDLE_ID,
        "action": "pointer_click",
        "window_title_pattern": "Luna Canary",
    }
    assert grant.remaining_actions == 1


def test_native_control_claim_denies_target_binding_mismatch(db_session, seeded):
    encoded_private_key = _b64url(ED25519_PRIVATE_KEY_BYTES)
    # both bundles allowlisted for this tenant — this test exercises the command↔
    # grant target MISMATCH, not the per-tenant allowlist gate (covered separately).
    _seed_tenant_allowlist(db_session, [CANARY_BUNDLE_ID, OTHER_CANARY_BUNDLE_ID])
    command = _native_pending_command(db_session, nonce="nonce-native-target-mismatch")
    with patch.object(
        desktop_control_service.settings,
        "DESKTOP_CONTROL_CANARY_BUNDLE_ALLOWLIST",
        [CANARY_BUNDLE_ID, OTHER_CANARY_BUNDLE_ID],
    ), patch.object(
        desktop_control_service.settings,
        "DESKTOP_COMMAND_ENVELOPE_SIGNING_ALGORITHM",
        "Ed25519",
    ), patch.object(
        desktop_control_service.settings,
        "DESKTOP_COMMAND_ENVELOPE_ED25519_PRIVATE_KEY",
        encoded_private_key,
    ), patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value=_presence(),
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        grant = create_desktop_approval_grant(
            db_session,
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            request=DesktopCommandApprovalGrantCreate(
                session_id=SESSION_ID,
                risk_tier="native_control",
                capability="pointer_control",
                target_binding={
                    "bundle_id": OTHER_CANARY_BUNDLE_ID,
                    "action": "pointer_click",
                    "window_title_pattern": "Luna Canary",
                },
            ),
        )
        command.approval_id = grant.id
        db_session.commit()
        claimed, event, _session_event = claim_next_desktop_command(
            db_session,
            user=seeded,
            device_token=DEVICE_TOKEN,
            claim=DesktopCommandClaim(session_id=SESSION_ID, shell_id=SHELL_ID, lease_seconds=30),
        )

    db_session.refresh(command)
    db_session.refresh(grant)
    assert claimed is None
    assert command.status == "denied"
    assert grant.status == "active"
    assert grant.remaining_actions == 1
    assert event.event_type == "desktop_command_approval_denied"
    assert event.reason == "desktop command approval grant binding mismatch"
    assert event.event_metadata["denial_code"] == "approval_binding_mismatch"


def test_native_control_claim_issues_target_bound_v2_envelope(db_session, seeded):
    encoded_private_key = _b64url(ED25519_PRIVATE_KEY_BYTES)
    command = _native_pending_command(db_session, nonce="nonce-native-target-envelope")
    with patch.object(
        desktop_control_service.settings,
        "DESKTOP_CONTROL_CANARY_BUNDLE_ALLOWLIST",
        [CANARY_BUNDLE_ID],
    ), patch.object(
        desktop_control_service.settings,
        "DESKTOP_COMMAND_ENVELOPE_SIGNING_ALGORITHM",
        "Ed25519",
    ), patch.object(
        desktop_control_service.settings,
        "DESKTOP_COMMAND_ENVELOPE_ED25519_PRIVATE_KEY",
        encoded_private_key,
    ), patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value=_presence(),
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        create_desktop_approval_grant(
            db_session,
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            request=DesktopCommandApprovalGrantCreate(
                session_id=SESSION_ID,
                desktop_command_id=command.id,
                risk_tier="native_control",
                capability="pointer_control",
                target_binding={
                    "bundle_id": CANARY_BUNDLE_ID,
                    "action": "pointer_click",
                    "window_title_pattern": "Luna Canary",
                },
            ),
        )
        claimed, event, _session_event = claim_next_desktop_command(
            db_session,
            user=seeded,
            device_token=DEVICE_TOKEN,
            claim=DesktopCommandClaim(session_id=SESSION_ID, shell_id=SHELL_ID, lease_seconds=30),
        )

    envelope = claimed.payload["command_envelope"]
    assert envelope["signature_alg"] == "Ed25519"
    assert envelope["policy_version"] == 2
    assert envelope["risk_tier"] == "native_control"
    assert envelope["approval_risk_tier"] == "native_control"
    assert envelope["target"]["bundle_id"] == CANARY_BUNDLE_ID
    assert envelope["target"]["window_title_pattern"] == "Luna Canary"
    assert envelope["target"]["window_title_hash"] is None
    with patch.object(
        desktop_control_service.settings,
        "DESKTOP_COMMAND_ENVELOPE_ED25519_PRIVATE_KEY",
        encoded_private_key,
    ):
        assert _verify_envelope_signature(envelope)
    assert event.event_metadata["envelope_policy_version"] == 2


def test_claim_can_issue_ed25519_command_envelope_and_complete(db_session, seeded):
    encoded_private_key = _b64url(ED25519_PRIVATE_KEY_BYTES)
    with patch.object(
        desktop_control_service.settings,
        "DESKTOP_COMMAND_ENVELOPE_SIGNING_ALGORITHM",
        "Ed25519",
    ), patch.object(
        desktop_control_service.settings,
        "DESKTOP_COMMAND_ENVELOPE_ED25519_PRIVATE_KEY",
        encoded_private_key,
    ), patch.object(
        desktop_control_service.settings,
        "DESKTOP_COMMAND_ENVELOPE_ED25519_KEY_ID",
        "agentprovision-desktop-command-ed25519-2026-06",
    ), patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value=_presence(),
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        command = _enqueue(db_session, nonce="nonce-envelope-ed25519")
        claimed, event, _session_event = claim_next_desktop_command(
            db_session,
            user=seeded,
            device_token=DEVICE_TOKEN,
            claim=DesktopCommandClaim(session_id=SESSION_ID, shell_id=SHELL_ID, lease_seconds=30),
        )

        envelope = claimed.payload["command_envelope"]
        assert envelope["signature_alg"] == "Ed25519"
        assert envelope["key_id"] == "agentprovision-desktop-command-ed25519-2026-06"
        assert envelope["signature"]
        assert _verify_envelope_signature(envelope)
        assert not _verify_envelope_signature({**envelope, "action": "read_clipboard"})

        completed, complete_event, _complete_session_event, idempotent = complete_desktop_command(
            db_session,
            user=seeded,
            device_token=DEVICE_TOKEN,
            completion=DesktopCommandCompletion(
                command_id=command.id,
                shell_id=SHELL_ID,
                status="succeeded",
                metadata={"envelope_nonce": envelope["nonce"]},
            ),
        )

    assert claimed.id == command.id
    assert event.event_metadata["envelope_nonce"] == envelope["nonce"]
    assert completed.status == "succeeded"
    assert complete_event.event_type == "desktop_command_completed"
    assert idempotent is False


def test_claim_denies_with_audit_when_ed25519_key_id_is_empty(db_session, seeded):
    encoded_private_key = _b64url(ED25519_PRIVATE_KEY_BYTES)
    with patch.object(
        desktop_control_service.settings,
        "DESKTOP_COMMAND_ENVELOPE_SIGNING_ALGORITHM",
        "Ed25519",
    ), patch.object(
        desktop_control_service.settings,
        "DESKTOP_COMMAND_ENVELOPE_ED25519_PRIVATE_KEY",
        encoded_private_key,
    ), patch.object(
        desktop_control_service.settings,
        "DESKTOP_COMMAND_ENVELOPE_ED25519_KEY_ID",
        " ",
    ), patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value=_presence(),
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        command = _enqueue(db_session, nonce="nonce-envelope-empty-key-id")
        claimed, event, _session_event = claim_next_desktop_command(
            db_session,
            user=seeded,
            device_token=DEVICE_TOKEN,
            claim=DesktopCommandClaim(session_id=SESSION_ID, shell_id=SHELL_ID, lease_seconds=30),
        )

    db_session.refresh(command)
    assert claimed is None
    assert command.status == "denied"
    assert event is not None
    assert event.event_type == "desktop_command_envelope_denied"
    assert event.reason == "desktop command denied"
    assert event.event_metadata["envelope_config_error"] == "RuntimeError"
    assert event.event_metadata["envelope_signing_algorithm"] == "Ed25519"
    assert (
        db_session.query(DesktopCommandEnvelopeNonce)
        .filter(DesktopCommandEnvelopeNonce.desktop_command_id == command.id)
        .count()
        == 0
    )


def test_claim_without_approval_grant_waits_before_lease(db_session, seeded):
    with patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value=_presence(),
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        command = _enqueue(db_session, nonce="nonce-approval-missing", grant=False)
        claimed, event, _session_event = claim_next_desktop_command(
            db_session,
            user=seeded,
            device_token=DEVICE_TOKEN,
            claim=DesktopCommandClaim(session_id=SESSION_ID, shell_id=SHELL_ID, lease_seconds=30),
        )

    assert claimed is None
    assert event is None
    reloaded = db_session.query(DesktopCommand).filter(DesktopCommand.id == command.id).one()
    assert reloaded.status == "pending"
    assert reloaded.lease_owner_shell_id is None
    assert db_session.query(DesktopCommandEnvelopeNonce).count() == 0


def test_claim_with_explicit_missing_approval_id_denies_before_lease(db_session, seeded):
    with patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value=_presence(),
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        command = _enqueue(db_session, nonce="nonce-approval-id-missing", grant=False)
        command.approval_id = uuid.UUID("aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa")
        db_session.commit()
        claimed, event, _session_event = claim_next_desktop_command(
            db_session,
            user=seeded,
            device_token=DEVICE_TOKEN,
            claim=DesktopCommandClaim(session_id=SESSION_ID, shell_id=SHELL_ID, lease_seconds=30),
        )

    assert claimed is None
    assert event.event_type == "desktop_command_approval_denied"
    assert event.reason == "desktop command approval grant missing"
    reloaded = db_session.query(DesktopCommand).filter(DesktopCommand.id == command.id).one()
    assert reloaded.status == "denied"
    assert db_session.query(DesktopCommandEnvelopeNonce).count() == 0


def test_exhausted_approval_grant_denies_claim_before_envelope(db_session, seeded):
    with patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value=_presence(),
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        command = _enqueue(db_session, nonce="nonce-approval-exhausted", grant=False)
        grant = create_desktop_approval_grant(
            db_session,
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            request=DesktopCommandApprovalGrantCreate(
                session_id=SESSION_ID,
                desktop_command_id=command.id,
                risk_tier="observe",
                capability=command.capability,
                expires_in_seconds=60,
            ),
        )
        grant.status = "consumed"
        grant.remaining_actions = 0
        command.approval_id = grant.id
        db_session.commit()
        claimed, event, _session_event = claim_next_desktop_command(
            db_session,
            user=seeded,
            device_token=DEVICE_TOKEN,
            claim=DesktopCommandClaim(session_id=SESSION_ID, shell_id=SHELL_ID, lease_seconds=30),
        )

    assert claimed is None
    assert event.event_type == "desktop_command_approval_denied"
    assert event.reason == "desktop command approval grant exhausted"
    reloaded = db_session.query(DesktopCommand).filter(DesktopCommand.id == command.id).one()
    assert reloaded.status == "denied"
    assert db_session.query(DesktopCommandEnvelopeNonce).count() == 0


def test_approval_grant_rejects_command_not_owned_by_user(db_session, seeded):
    with patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value=_presence(),
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        command = _enqueue(db_session, nonce="nonce-approval-wrong-user", grant=False)
        command.user_id = None
        db_session.commit()
        with pytest.raises(HTTPException) as exc:
            create_desktop_approval_grant(
                db_session,
                tenant_id=TENANT_ID,
                user_id=USER_ID,
                request=DesktopCommandApprovalGrantCreate(
                    session_id=SESSION_ID,
                    desktop_command_id=command.id,
                    risk_tier="observe",
                    capability=command.capability,
                    expires_in_seconds=60,
                ),
            )

    assert exc.value.status_code == 403
    assert exc.value.detail == "Desktop command is not owned by user"


def test_approval_grant_rejects_risk_capability_mismatch(db_session, seeded):
    with patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value=_presence(),
    ):
        with pytest.raises(HTTPException) as exc:
            create_desktop_approval_grant(
                db_session,
                tenant_id=TENANT_ID,
                user_id=USER_ID,
                request=DesktopCommandApprovalGrantCreate(
                    session_id=SESSION_ID,
                    shell_id=SHELL_ID,
                    risk_tier="observe",
                    capability="pointer_control",
                    expires_in_seconds=60,
                ),
            )

    assert exc.value.status_code == 422
    assert exc.value.detail == "Desktop approval capability does not match risk tier"


def test_enqueue_rejects_non_desktop_active_shell_before_command_insert(db_session, seeded):
    non_desktop_presence = {
        "active_shell": "web",
        "connected_shells": ["web"],
        "shell_capabilities": {"web": {"can_observe": True}},
        "shell_devices": {"web": str(DEVICE_ID)},
    }
    with patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value=non_desktop_presence,
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        with pytest.raises(HTTPException) as exc:
            _enqueue(db_session, nonce="nonce-non-desktop-shell")

    assert exc.value.status_code == 409
    assert exc.value.detail == "Desktop shell id is invalid"
    assert db_session.query(DesktopCommand).count() == 0
    assert db_session.query(DesktopCommandEnvelopeNonce).count() == 0


def test_completion_consumes_signed_envelope_nonce(db_session, seeded):
    with patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value=_presence(),
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        command = _enqueue(db_session, nonce="nonce-envelope-consumed")
        claim_next_desktop_command(
            db_session,
            user=seeded,
            device_token=DEVICE_TOKEN,
            claim=DesktopCommandClaim(session_id=SESSION_ID, shell_id=SHELL_ID, lease_seconds=30),
        )
        envelope_nonce = command.payload["command_envelope"]["nonce"]
        completed, event, _session_event, idempotent = complete_desktop_command(
            db_session,
            user=seeded,
            device_token=DEVICE_TOKEN,
            completion=DesktopCommandCompletion(
                command_id=command.id,
                shell_id=SHELL_ID,
                status="denied",
                reason="desktop observe locked; capture_screenshot denied",
                metadata=_completion_metadata(db_session, command, result_kind="error"),
            ),
        )

    assert completed.status == "denied"
    assert event.event_type == "desktop_command_completed"
    assert event.event_metadata["envelope_nonce"] == envelope_nonce
    assert len(event.event_metadata["envelope_hash"]) == 64
    assert idempotent is False
    nonce_row = db_session.query(DesktopCommandEnvelopeNonce).filter(
        DesktopCommandEnvelopeNonce.nonce == envelope_nonce,
    ).one()
    assert nonce_row.status == "consumed"
    assert nonce_row.consumed_at is not None


def test_completion_without_envelope_nonce_is_denied_and_terminal(db_session, seeded):
    with patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value=_presence(),
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        command = _enqueue(db_session, nonce="nonce-envelope-missing")
        claim_next_desktop_command(
            db_session,
            user=seeded,
            device_token=DEVICE_TOKEN,
            claim=DesktopCommandClaim(session_id=SESSION_ID, shell_id=SHELL_ID, lease_seconds=30),
        )
        completed, event, _session_event, idempotent = complete_desktop_command(
            db_session,
            user=seeded,
            device_token=DEVICE_TOKEN,
            completion=DesktopCommandCompletion(
                command_id=command.id,
                shell_id=SHELL_ID,
                status="succeeded",
            ),
        )

    assert completed.status == "denied"
    assert event.event_type == "desktop_command_envelope_denied"
    assert event.reason == "desktop command envelope nonce missing"
    assert idempotent is False
    reloaded = db_session.query(DesktopCommand).filter(DesktopCommand.id == command.id).one()
    assert reloaded.completed_at is not None


def test_tampered_command_envelope_signature_is_denied(db_session, seeded):
    with patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value=_presence(),
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        command = _enqueue(db_session, nonce="nonce-envelope-tampered")
        claim_next_desktop_command(
            db_session,
            user=seeded,
            device_token=DEVICE_TOKEN,
            claim=DesktopCommandClaim(session_id=SESSION_ID, shell_id=SHELL_ID, lease_seconds=30),
        )
        envelope_nonce = command.payload["command_envelope"]["nonce"]
        payload = dict(command.payload)
        payload["command_envelope"] = {
            **payload["command_envelope"],
            "action": "read_clipboard",
        }
        command.payload = payload
        db_session.commit()

        completed, event, _session_event, idempotent = complete_desktop_command(
            db_session,
            user=seeded,
            device_token=DEVICE_TOKEN,
            completion=DesktopCommandCompletion(
                command_id=command.id,
                shell_id=SHELL_ID,
                status="succeeded",
                metadata={"envelope_nonce": envelope_nonce},
            ),
        )

    assert completed.status == "denied"
    assert event.event_type == "desktop_command_envelope_denied"
    assert event.reason == "desktop command envelope signature invalid"
    assert idempotent is False


def test_replayed_envelope_nonce_is_denied_and_audited(db_session, seeded):
    with patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value=_presence(),
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        command = _enqueue(db_session, nonce="nonce-envelope-replayed")
        claim_next_desktop_command(
            db_session,
            user=seeded,
            device_token=DEVICE_TOKEN,
            claim=DesktopCommandClaim(session_id=SESSION_ID, shell_id=SHELL_ID, lease_seconds=30),
        )
        envelope_nonce = command.payload["command_envelope"]["nonce"]
        nonce_row = db_session.query(DesktopCommandEnvelopeNonce).filter(
            DesktopCommandEnvelopeNonce.nonce == envelope_nonce,
        ).one()
        nonce_row.status = "consumed"
        db_session.commit()

        completed, event, _session_event, idempotent = complete_desktop_command(
            db_session,
            user=seeded,
            device_token=DEVICE_TOKEN,
            completion=DesktopCommandCompletion(
                command_id=command.id,
                shell_id=SHELL_ID,
                status="succeeded",
                metadata=_completion_metadata(db_session, command),
            ),
        )

    assert completed.status == "denied"
    assert event.event_type == "desktop_command_envelope_denied"
    assert event.reason == "desktop command envelope replay denied"
    assert event.event_metadata["envelope_nonce"] == envelope_nonce
    assert idempotent is False
    db_session.refresh(nonce_row)
    assert nonce_row.status == "replayed"


def test_pointer_enqueue_rejects_missing_or_unallowlisted_target(db_session, seeded):
    # Phase 3: pointer issuance is enabled, but only against an allowlisted
    # target. A missing or non-allowlisted target is rejected before queuing.
    with patch.object(
        desktop_control_service.settings,
        "DESKTOP_CONTROL_CANARY_BUNDLE_ALLOWLIST",
        [CANARY_BUNDLE_ID],
    ), patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value=_presence(),
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        with pytest.raises(HTTPException) as missing:
            enqueue_desktop_command(
                db_session,
                tenant_id=TENANT_ID,
                user_id=USER_ID,
                request=DesktopCommandEnqueue(
                    session_id=SESSION_ID,
                    action="pointer_click",
                    tool_name="desktop_pointer_click",
                    shell_id=None,
                    nonce="pointer-missing-target",
                    payload={"x": 1, "y": 2},
                ),
            )
        assert missing.value.status_code == 422

        with pytest.raises(HTTPException) as unallowlisted:
            enqueue_desktop_command(
                db_session,
                tenant_id=TENANT_ID,
                user_id=USER_ID,
                request=DesktopCommandEnqueue(
                    session_id=SESSION_ID,
                    action="pointer_click",
                    tool_name="desktop_pointer_click",
                    shell_id=None,
                    nonce="pointer-bad-target",
                    payload={
                        "target": {
                            "bundle_id": OTHER_CANARY_BUNDLE_ID,
                            "action": "pointer_click",
                        }
                    },
                ),
            )
        assert unallowlisted.value.status_code == 422
        assert "target not allowlisted" in str(unallowlisted.value.detail).lower()


def test_pointer_enqueue_queues_pending_for_allowlisted_target(db_session, seeded):
    # An allowlisted pointer command queues a PENDING native-control command
    # (no longer denied at enqueue). Raw coordinates are never persisted.
    with patch.object(
        desktop_control_service.settings,
        "DESKTOP_CONTROL_CANARY_BUNDLE_ALLOWLIST",
        [CANARY_BUNDLE_ID],
    ), patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value=_presence(),
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        command, event, _session_event = enqueue_desktop_command(
            db_session,
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            request=DesktopCommandEnqueue(
                session_id=SESSION_ID,
                action="pointer_move",
                tool_name="desktop_pointer_move",
                shell_id=None,
                nonce="pointer-pending",
                payload={
                    "x": 100,
                    "y": 200,
                    "raw_target_text": "must not persist",
                    "target": {
                        "bundle_id": CANARY_BUNDLE_ID,
                        "action": "pointer_move",
                        "window_title_pattern": "Luna Canary",
                    },
                },
            ),
        )

    assert command.status == "pending"
    assert command.capability == "pointer_control"
    assert command.completed_at is None
    assert command.payload["mode"] == "control_locked"
    assert command.payload["risk_tier"] == "native_control"
    assert command.payload["target"]["bundle_id"] == CANARY_BUNDLE_ID
    assert command.payload["target"]["action"] == "pointer_move"
    assert event.event_type == "desktop_command_queued"
    assert event.outcome == "requested"
    assert "must not persist" not in str(command.payload)
    assert "must not persist" not in str(event.event_metadata)


def test_keyboard_enqueue_requires_allowlisted_target_then_queues(db_session, seeded):
    # Phase 4: keyboard issuance is enabled, but (like pointer) only against an
    # allowlisted target. Missing target -> 422; an allowlisted target -> a pending
    # native-control command, and the typed text is never persisted.
    with patch.object(
        desktop_control_service.settings,
        "DESKTOP_CONTROL_CANARY_BUNDLE_ALLOWLIST",
        [CANARY_BUNDLE_ID],
    ), patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value=_presence(),
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        with pytest.raises(HTTPException) as missing:
            enqueue_desktop_command(
                db_session,
                tenant_id=TENANT_ID,
                user_id=USER_ID,
                request=DesktopCommandEnqueue(
                    session_id=SESSION_ID,
                    action="keyboard_type",
                    tool_name="desktop_keyboard_type",
                    shell_id=None,
                    nonce="keyboard-no-target",
                    payload={"text": "must not persist"},
                ),
            )
        assert missing.value.status_code == 422

        command, event, _session_event = enqueue_desktop_command(
            db_session,
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            request=DesktopCommandEnqueue(
                session_id=SESSION_ID,
                action="keyboard_type",
                tool_name="desktop_keyboard_type",
                shell_id=None,
                nonce="keyboard-allowlisted",
                payload={
                    "text": "must not persist",
                    "target": {"bundle_id": CANARY_BUNDLE_ID, "action": "keyboard_type"},
                },
            ),
        )

    assert command.status == "pending"
    assert command.capability == "keyboard_control"
    assert command.payload["risk_tier"] == "native_control"
    assert command.payload["target"]["bundle_id"] == CANARY_BUNDLE_ID
    assert event.event_type == "desktop_command_queued"
    assert "must not persist" not in str(command.payload)
    assert "must not persist" not in str(event.event_metadata)


def test_pointer_command_claim_issues_signed_native_control_envelope(db_session, seeded):
    # End-to-end server issuance: an allowlisted pointer command backed by a
    # native_control grant is claimed into a SIGNED (Ed25519) envelope and the
    # grant is consumed — this is the envelope the client proves + actuates.
    encoded_private_key = _b64url(ED25519_PRIVATE_KEY_BYTES)
    with patch.object(
        desktop_control_service.settings,
        "DESKTOP_CONTROL_CANARY_BUNDLE_ALLOWLIST",
        [CANARY_BUNDLE_ID],
    ), patch.object(
        desktop_control_service.settings,
        "DESKTOP_COMMAND_ENVELOPE_SIGNING_ALGORITHM",
        "Ed25519",
    ), patch.object(
        desktop_control_service.settings,
        "DESKTOP_COMMAND_ENVELOPE_ED25519_PRIVATE_KEY",
        encoded_private_key,
    ), patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value=_presence(),
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        grant = create_desktop_approval_grant(
            db_session,
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            request=DesktopCommandApprovalGrantCreate(
                session_id=SESSION_ID,
                risk_tier="native_control",
                capability="pointer_control",
                target_binding={
                    "bundle_id": CANARY_BUNDLE_ID,
                    "action": "pointer_click",
                    "window_title_pattern": "Luna Canary",
                },
                expires_in_seconds=60,
            ),
        )
        command, _event, _session_event = enqueue_desktop_command(
            db_session,
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            request=DesktopCommandEnqueue(
                session_id=SESSION_ID,
                action="pointer_click",
                tool_name="desktop_pointer_click",
                shell_id=None,
                nonce="pointer-claim-signed",
                approval_id=grant.id,
                payload={
                    "target": {
                        "bundle_id": CANARY_BUNDLE_ID,
                        "action": "pointer_click",
                        "window_title_pattern": "Luna Canary",
                    },
                },
            ),
        )
        claimed, event, _claim_session_event = claim_next_desktop_command(
            db_session,
            user=seeded,
            device_token=DEVICE_TOKEN,
            claim=DesktopCommandClaim(session_id=SESSION_ID, shell_id=SHELL_ID, lease_seconds=30),
        )

    assert claimed is not None
    assert claimed.id == command.id
    assert claimed.status == "claimed"
    envelope = claimed.payload["command_envelope"]
    assert envelope["signature_alg"] == "Ed25519"
    assert envelope["capability"] == "pointer_control"
    assert envelope["risk_tier"] == "native_control"
    assert envelope["action"] == "pointer_click"
    assert envelope["approval_risk_tier"] == "native_control"
    assert envelope["approval_id"] == str(grant.id)
    assert envelope["target"]["bundle_id"] == CANARY_BUNDLE_ID
    assert envelope["signature"]
    assert event.event_type == "desktop_command_claimed"
    consumed = db_session.query(DesktopCommandApprovalGrant).filter(
        DesktopCommandApprovalGrant.id == grant.id,
    ).one()
    assert consumed.status == "consumed"


def test_native_control_claim_denies_with_audit_when_ed25519_private_key_missing(
    db_session,
    seeded,
):
    command = _native_pending_command(db_session, nonce="native-ed25519-missing-private-key")
    with patch.object(
        desktop_control_service.settings,
        "DESKTOP_CONTROL_CANARY_BUNDLE_ALLOWLIST",
        [CANARY_BUNDLE_ID],
    ), patch.object(
        desktop_control_service.settings,
        "DESKTOP_COMMAND_ENVELOPE_SIGNING_ALGORITHM",
        "Ed25519",
    ), patch.object(
        desktop_control_service.settings,
        "DESKTOP_COMMAND_ENVELOPE_ED25519_PRIVATE_KEY",
        "",
    ), patch.object(
        desktop_control_service.settings,
        "DESKTOP_COMMAND_ENVELOPE_ED25519_KEY_ID",
        "agentprovision-desktop-command-ed25519-2026-06",
    ), patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value=_presence(),
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        grant = create_desktop_approval_grant(
            db_session,
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            request=DesktopCommandApprovalGrantCreate(
                session_id=SESSION_ID,
                desktop_command_id=command.id,
                risk_tier="native_control",
                capability="pointer_control",
                target_binding={
                    "bundle_id": CANARY_BUNDLE_ID,
                    "action": "pointer_click",
                    "window_title_pattern": "Luna Canary",
                },
                expires_in_seconds=60,
            ),
        )
        claimed, event, _claim_session_event = claim_next_desktop_command(
            db_session,
            user=seeded,
            device_token=DEVICE_TOKEN,
            claim=DesktopCommandClaim(session_id=SESSION_ID, shell_id=SHELL_ID, lease_seconds=30),
        )

    db_session.refresh(command)
    db_session.refresh(grant)
    assert claimed is None
    assert command.status == "denied"
    assert "command_envelope" not in (command.payload or {})
    assert grant.status == "active"
    assert grant.remaining_actions == 1
    assert event is not None
    assert event.event_type == "desktop_command_envelope_denied"
    assert event.reason == "desktop command denied"
    assert event.event_metadata["envelope_config_error"] == "RuntimeError"
    assert event.event_metadata["envelope_signing_algorithm"] == "Ed25519"
    assert (
        db_session.query(DesktopCommandEnvelopeNonce)
        .filter(DesktopCommandEnvelopeNonce.desktop_command_id == command.id)
        .count()
        == 0
    )


def test_native_control_keyboard_nonce_retry_is_idempotent(db_session, seeded):
    # Re-enqueuing the same keyboard command nonce returns the same pending
    # command and writes only one queued event (Phase 4: keyboard is issued, not
    # denied).
    payload = {
        "text": "must not persist",
        "target": {"bundle_id": CANARY_BUNDLE_ID, "action": "keyboard_type"},
    }
    with patch.object(
        desktop_control_service.settings,
        "DESKTOP_CONTROL_CANARY_BUNDLE_ALLOWLIST",
        [CANARY_BUNDLE_ID],
    ), patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value=_presence(),
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        first = enqueue_desktop_command(
            db_session,
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            request=DesktopCommandEnqueue(
                session_id=SESSION_ID,
                action="keyboard_type",
                tool_name="desktop_keyboard_type",
                shell_id=None,
                nonce="native-keyboard-pending",
                payload=dict(payload),
            ),
        )[0]
        second = enqueue_desktop_command(
            db_session,
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            request=DesktopCommandEnqueue(
                session_id=SESSION_ID,
                action="keyboard_type",
                tool_name="desktop_keyboard_type",
                shell_id=None,
                nonce="native-keyboard-pending",
                payload=dict(payload),
            ),
        )[0]

    assert second.id == first.id
    assert first.status == "pending"
    queued = db_session.query(DesktopCommandEvent).filter(
        DesktopCommandEvent.desktop_command_id == first.id,
        DesktopCommandEvent.event_type == "desktop_command_queued",
    ).all()
    assert len(queued) == 1
    assert "must not persist" not in str(first.payload)


def test_duplicate_completion_is_idempotent_and_writes_one_completion_event(db_session, seeded):
    with patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value=_presence(),
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        command = _enqueue(db_session, nonce="nonce-2")
        claim_next_desktop_command(
            db_session,
            user=seeded,
            device_token=DEVICE_TOKEN,
            claim=DesktopCommandClaim(session_id=SESSION_ID, shell_id=SHELL_ID, lease_seconds=30),
        )
        completed, event, _session_event, idempotent = complete_desktop_command(
            db_session,
            user=seeded,
            device_token=DEVICE_TOKEN,
            completion=DesktopCommandCompletion(
                command_id=command.id,
                shell_id=SHELL_ID,
                status="succeeded",
                reason="done",
                metadata=_completion_metadata(db_session, command, summary="ok"),
            ),
        )
        again, again_event, _again_session_event, again_idempotent = complete_desktop_command(
            db_session,
            user=seeded,
            device_token=DEVICE_TOKEN,
            completion=DesktopCommandCompletion(
                command_id=command.id,
                shell_id=SHELL_ID,
                status="failed",
                reason="late duplicate",
                metadata={"raw_clipboard_text": "must not persist"},
            ),
        )

    assert completed.status == "succeeded"
    assert event.event_type == "desktop_command_completed"
    assert idempotent is False
    assert again.status == "succeeded"
    assert again_event is None
    assert again_idempotent is True
    completion_events = db_session.query(DesktopCommandEvent).filter(
        DesktopCommandEvent.desktop_command_id == command.id,
        DesktopCommandEvent.event_type == "desktop_command_completed",
    ).all()
    assert len(completion_events) == 1
    assert "must not persist" not in str(completion_events[0].event_metadata)


def test_completion_after_stop_returns_preempted_not_success(db_session, seeded):
    with patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value=_presence(),
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        command = _enqueue(db_session, nonce="nonce-3")
        claim_next_desktop_command(
            db_session,
            user=seeded,
            device_token=DEVICE_TOKEN,
            claim=DesktopCommandClaim(session_id=SESSION_ID, shell_id=SHELL_ID, lease_seconds=30),
        )
        count, events, _session_events = preempt_desktop_commands_for_stop(
            db_session,
            user=seeded,
            device_token=DEVICE_TOKEN,
            stop=DesktopCommandStop(session_id=SESSION_ID, shell_id=SHELL_ID, reason="operator Stop"),
        )
        completed, event, _session_event, idempotent = complete_desktop_command(
            db_session,
            user=seeded,
            device_token=DEVICE_TOKEN,
            completion=DesktopCommandCompletion(
                command_id=command.id,
                shell_id=SHELL_ID,
                status="succeeded",
            ),
        )

    assert count == 1
    assert events[0].event_type == "desktop_command_preempted"
    assert completed.status == "preempted"
    assert event is None
    assert idempotent is True


def test_stop_revokes_active_session_approval_grants(db_session, seeded):
    with patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value=_presence(),
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        grant = create_desktop_approval_grant(
            db_session,
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            request=DesktopCommandApprovalGrantCreate(
                session_id=SESSION_ID,
                shell_id=SHELL_ID,
                risk_tier="observe",
                capability="screenshot",
                max_actions=2,
                expires_in_seconds=120,
            ),
        )
        count, events, _session_events = preempt_desktop_commands_for_stop(
            db_session,
            user=seeded,
            device_token=DEVICE_TOKEN,
            stop=DesktopCommandStop(session_id=SESSION_ID, shell_id=SHELL_ID, reason="operator Stop"),
        )

    db_session.refresh(grant)
    assert count == 0
    assert events == []
    assert grant.status == "revoked"
    assert grant.revoked_at is not None
    assert grant.remaining_actions == 2


def test_expired_lease_rejects_success_completion(db_session, seeded):
    with patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value=_presence(),
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        command = _enqueue(db_session, nonce="nonce-4")
        claim_next_desktop_command(
            db_session,
            user=seeded,
            device_token=DEVICE_TOKEN,
            claim=DesktopCommandClaim(session_id=SESSION_ID, shell_id=SHELL_ID, lease_seconds=5),
        )
        command.lease_expires_at = _utcnow() - timedelta(seconds=1)
        db_session.commit()
        completed, event, _session_event, idempotent = complete_desktop_command(
            db_session,
            user=seeded,
            device_token=DEVICE_TOKEN,
            completion=DesktopCommandCompletion(
                command_id=command.id,
                shell_id=SHELL_ID,
                status="succeeded",
            ),
        )

    assert completed.status == "expired"
    assert event.event_type == "desktop_command_expired"
    assert event.outcome == "expired"
    assert idempotent is False


def test_completion_accepts_naive_future_lease_from_database(db_session, seeded):
    with patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value=_presence(),
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        command = _enqueue(db_session, nonce="nonce-naive-future-lease")
        claim_next_desktop_command(
            db_session,
            user=seeded,
            device_token=DEVICE_TOKEN,
            claim=DesktopCommandClaim(session_id=SESSION_ID, shell_id=SHELL_ID, lease_seconds=30),
        )
        command.lease_expires_at = (_utcnow() + timedelta(seconds=30)).replace(tzinfo=None)
        db_session.commit()
        db_session.expire_all()

        completed, event, _session_event, idempotent = complete_desktop_command(
            db_session,
            user=seeded,
            device_token=DEVICE_TOKEN,
            completion=DesktopCommandCompletion(
                command_id=command.id,
                shell_id=SHELL_ID,
                status="denied",
                reason="desktop observe locked; get_active_app denied",
                metadata=_completion_metadata(db_session, command, result_kind="error"),
            ),
        )

    assert completed.status == "denied"
    assert event.event_type == "desktop_command_completed"
    assert event.outcome == "denied"
    assert idempotent is False


def test_stale_pending_command_expires_before_claim(db_session, seeded):
    with patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value=_presence(),
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        command = _enqueue(db_session, nonce="nonce-pending-ttl")
        old = _utcnow() - timedelta(seconds=DEFAULT_COMMAND_PENDING_TTL_SECONDS + 1)
        command.created_at = old
        command.updated_at = old
        db_session.commit()

        claimed, event, _session_event = claim_next_desktop_command(
            db_session,
            user=seeded,
            device_token=DEVICE_TOKEN,
            claim=DesktopCommandClaim(session_id=SESSION_ID, shell_id=SHELL_ID, lease_seconds=30),
        )

    assert claimed is None
    assert event is None
    reloaded = db_session.query(DesktopCommand).filter(DesktopCommand.id == command.id).one()
    assert reloaded.status == "expired"
    expired_event = db_session.query(DesktopCommandEvent).filter(
        DesktopCommandEvent.desktop_command_id == command.id,
        DesktopCommandEvent.event_type == "desktop_command_expired",
    ).one()
    assert expired_event.reason == "desktop command pending ttl expired"


def test_stop_preempts_pending_claimed_and_running_commands(db_session, seeded):
    with patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value=_presence(),
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        pending = _enqueue(db_session, nonce="nonce-5a")
        claimed = _enqueue(db_session, nonce="nonce-5b")
        running = _enqueue(db_session, nonce="nonce-5c")
        claimed.status = "claimed"
        claimed.lease_owner_shell_id = SHELL_ID
        claimed.lease_expires_at = _utcnow() + timedelta(seconds=30)
        running.status = "running"
        running.lease_owner_shell_id = SHELL_ID
        running.lease_expires_at = _utcnow() + timedelta(seconds=30)
        db_session.commit()

        count, events, _session_events = preempt_desktop_commands_for_stop(
            db_session,
            user=seeded,
            device_token=DEVICE_TOKEN,
            stop=DesktopCommandStop(session_id=SESSION_ID, shell_id=SHELL_ID),
        )

    assert count == 3
    assert {event.desktop_command_id for event in events} == {pending.id, claimed.id, running.id}
    statuses = {
        row.id: row.status
        for row in db_session.query(DesktopCommand).filter(
            DesktopCommand.id.in_([pending.id, claimed.id, running.id]),
        )
    }
    assert statuses == {
        pending.id: "preempted",
        claimed.id: "preempted",
        running.id: "preempted",
    }


def test_agent_stop_can_preempt_without_device_token_on_connected_shell(db_session, seeded):
    with patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value=_presence(),
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        command = _enqueue(db_session, nonce="nonce-agent-stop")
        count, events, _session_events = preempt_desktop_commands_for_stop(
            db_session,
            user=seeded,
            device_token=None,
            stop=DesktopCommandStop(session_id=SESSION_ID, shell_id=SHELL_ID, reason="agent Stop"),
        )

    assert count == 1
    assert events[0].desktop_command_id == command.id
    assert events[0].source == "agent"
    reloaded = db_session.query(DesktopCommand).filter(DesktopCommand.id == command.id).one()
    assert reloaded.status == "preempted"


def test_claim_requires_matching_device_token(db_session, seeded):
    with patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value=_presence(),
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        _enqueue(db_session, nonce="nonce-6")
        with pytest.raises(HTTPException) as exc:
            claim_next_desktop_command(
                db_session,
                user=seeded,
                device_token="wrong-token",
                claim=DesktopCommandClaim(session_id=SESSION_ID, shell_id=SHELL_ID, lease_seconds=30),
            )

    assert exc.value.status_code == 401


def test_revoked_desktop_device_cannot_claim_even_with_fresh_presence(db_session, seeded):
    with patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value=_presence(),
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        command = _enqueue(db_session, nonce="nonce-revoked-device")
        device = db_session.query(DeviceRegistry).filter(DeviceRegistry.id == DEVICE_ID).one()
        device.status = "revoked"
        db_session.commit()

        with pytest.raises(HTTPException) as exc:
            claim_next_desktop_command(
                db_session,
                user=seeded,
                device_token=DEVICE_TOKEN,
                claim=DesktopCommandClaim(session_id=SESSION_ID, shell_id=SHELL_ID, lease_seconds=30),
            )

    assert exc.value.status_code == 403
    assert exc.value.detail == "Desktop device is revoked"
    reloaded = db_session.query(DesktopCommand).filter(DesktopCommand.id == command.id).one()
    assert reloaded.status == "pending"
    assert reloaded.lease_owner_shell_id is None


def test_revoked_desktop_device_cannot_complete_claimed_command(db_session, seeded):
    with patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value=_presence(),
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        command = _enqueue(db_session, nonce="nonce-revoked-complete")
        claim_next_desktop_command(
            db_session,
            user=seeded,
            device_token=DEVICE_TOKEN,
            claim=DesktopCommandClaim(session_id=SESSION_ID, shell_id=SHELL_ID, lease_seconds=30),
        )
        device = db_session.query(DeviceRegistry).filter(DeviceRegistry.id == DEVICE_ID).one()
        device.status = "disabled"
        db_session.commit()

        with pytest.raises(HTTPException) as exc:
            complete_desktop_command(
                db_session,
                user=seeded,
                device_token=DEVICE_TOKEN,
                completion=DesktopCommandCompletion(
                    command_id=command.id,
                    shell_id=SHELL_ID,
                    status="succeeded",
                ),
            )

    assert exc.value.status_code == 403
    assert exc.value.detail == "Desktop device is revoked"
    reloaded = db_session.query(DesktopCommand).filter(DesktopCommand.id == command.id).one()
    assert reloaded.status == "claimed"
    assert reloaded.completed_at is None


def test_completion_sanitizes_reason_and_metadata_values(db_session, seeded):
    with patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value=_presence(),
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        command = _enqueue(db_session, nonce="nonce-7")
        claim_next_desktop_command(
            db_session,
            user=seeded,
            device_token=DEVICE_TOKEN,
            claim=DesktopCommandClaim(session_id=SESSION_ID, shell_id=SHELL_ID, lease_seconds=30),
        )
        _completed, event, _session_event, _idempotent = complete_desktop_command(
            db_session,
            user=seeded,
            device_token=DEVICE_TOKEN,
            completion=DesktopCommandCompletion(
                command_id=command.id,
                shell_id=SHELL_ID,
                status="failed",
                reason="raw clipboard text: password token must not persist",
                metadata=_completion_metadata(
                    db_session,
                    command,
                    lease_expires_at="sk-raw-token-must-not-persist",
                    summary="OCR token must not persist",
                    result_kind="string",
                    result_size_chars=41,
                    result_fields=["app", "title", "title_present", "raw_text"],
                ),
            ),
        )

    assert event.reason == "desktop command failed"
    assert event.event_metadata["result_kind"] == "string"
    assert event.event_metadata["result_size_chars"] == 41
    assert event.event_metadata["result_fields"] == ["app", "title_present"]
    assert "must not persist" not in str(event.event_metadata)
    assert "lease_expires_at" not in event.event_metadata
    assert "raw clipboard" not in str(event.reason)


def test_stop_sanitizes_operator_reason(db_session, seeded):
    with patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value=_presence(),
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        _enqueue(db_session, nonce="nonce-8")
        count, events, _session_events = preempt_desktop_commands_for_stop(
            db_session,
            user=seeded,
            device_token=DEVICE_TOKEN,
            stop=DesktopCommandStop(
                session_id=SESSION_ID,
                shell_id=SHELL_ID,
                reason="raw clipboard text: password token must not persist",
            ),
        )

    assert count == 1
    assert events[0].reason == "desktop command preempted"
    assert "must not persist" not in str(events[0].event_metadata)


def test_duplicate_terminal_completion_is_idempotent_after_shell_disconnect(db_session, seeded):
    with patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value=_presence(),
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        command = _enqueue(db_session, nonce="nonce-9")
        claim_next_desktop_command(
            db_session,
            user=seeded,
            device_token=DEVICE_TOKEN,
            claim=DesktopCommandClaim(session_id=SESSION_ID, shell_id=SHELL_ID, lease_seconds=30),
        )
        complete_desktop_command(
            db_session,
            user=seeded,
            device_token=DEVICE_TOKEN,
            completion=DesktopCommandCompletion(
                command_id=command.id,
                shell_id=SHELL_ID,
                status="succeeded",
                metadata=_completion_metadata(db_session, command),
            ),
        )

    disconnected = {
        "active_shell": None,
        "connected_shells": [],
        "shell_capabilities": {},
        "shell_devices": {},
    }
    with patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value=disconnected,
    ):
        completed, event, _session_event, idempotent = complete_desktop_command(
            db_session,
            user=seeded,
            device_token=DEVICE_TOKEN,
            completion=DesktopCommandCompletion(
                command_id=command.id,
                shell_id=SHELL_ID,
                status="failed",
            ),
        )

    assert completed.status == "succeeded"
    assert event is None
    assert idempotent is True


def test_later_claim_expires_stale_lease_with_audit_event(db_session, seeded):
    with patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value=_presence(),
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        stale = _enqueue(db_session, nonce="nonce-10a")
        pending = _enqueue(db_session, nonce="nonce-10b")
        stale.status = "claimed"
        stale.lease_owner_shell_id = SHELL_ID
        stale.lease_expires_at = _utcnow() - timedelta(seconds=1)
        db_session.commit()

        claimed, _event, _session_event = claim_next_desktop_command(
            db_session,
            user=seeded,
            device_token=DEVICE_TOKEN,
            claim=DesktopCommandClaim(session_id=SESSION_ID, shell_id=SHELL_ID, lease_seconds=30),
        )

    assert claimed.id == pending.id
    expired = db_session.query(DesktopCommand).filter(DesktopCommand.id == stale.id).one()
    assert expired.status == "expired"
    expired_events = db_session.query(DesktopCommandEvent).filter(
        DesktopCommandEvent.desktop_command_id == stale.id,
        DesktopCommandEvent.event_type == "desktop_command_expired",
    ).all()
    assert len(expired_events) == 1
    assert expired_events[0].reason == "desktop command lease expired"


def test_enqueue_nonce_retry_is_idempotent_for_same_tenant_request(db_session, seeded):
    with patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value=_presence(),
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        first = _enqueue(db_session, nonce="shared-same-tenant")
        second = _enqueue(db_session, nonce="shared-same-tenant")

    assert second.id == first.id
    commands = db_session.query(DesktopCommand).filter(
        DesktopCommand.nonce == "shared-same-tenant",
    ).all()
    queued_events = db_session.query(DesktopCommandEvent).filter(
        DesktopCommandEvent.desktop_command_id == first.id,
        DesktopCommandEvent.event_type == "desktop_command_queued",
    ).all()
    assert len(commands) == 1
    assert len(queued_events) == 1


def test_enqueue_nonce_retry_rejects_explicit_shell_mismatch(db_session, seeded):
    with patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value=_presence(),
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        _enqueue(db_session, nonce="shared-shell-mismatch")
        with pytest.raises(HTTPException) as exc:
            enqueue_desktop_command(
                db_session,
                tenant_id=TENANT_ID,
                user_id=USER_ID,
                request=DesktopCommandEnqueue(
                    session_id=SESSION_ID,
                    action="capture_screenshot",
                    tool_name="desktop_observe_screen",
                    shell_id=OTHER_SHELL_ID,
                    nonce="shared-shell-mismatch",
                    payload={},
                ),
            )

    assert exc.value.status_code == 409


def test_enqueue_nonce_is_tenant_scoped(db_session, seeded):
    _seed_second_tenant(db_session)

    def presence_for_tenant(tenant_id):
        if tenant_id == TENANT_ID_2:
            return _presence(device_id=DEVICE_ID_2)
        return _presence()

    with patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        side_effect=presence_for_tenant,
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        first = _enqueue(db_session, nonce="shared-cross-tenant")
        second = enqueue_desktop_command(
            db_session,
            tenant_id=TENANT_ID_2,
            user_id=USER_ID_2,
            request=DesktopCommandEnqueue(
                session_id=SESSION_ID_2,
                action="capture_screenshot",
                tool_name="desktop_observe_screen",
                shell_id=None,
                nonce="shared-cross-tenant",
                payload={"reason": "same nonce, different tenant"},
            ),
        )[0]

    assert first.id != second.id
    commands = db_session.query(DesktopCommand).filter(
        DesktopCommand.nonce == "shared-cross-tenant",
    ).all()
    assert {command.tenant_id for command in commands} == {TENANT_ID, TENANT_ID_2}


# ── PR4b: per-tenant capability enforcement (audit G10 / Codex B1) ────────────
# Native actuation is fail-closed: master desktop_control_enabled AND the
# per-action-class flag must be ON, re-checked at enqueue AND at claim (the real
# boundary). The seeded tenant is fully enabled; these tests flip flags OFF.


def _set_capability_flags(db, *, desktop=True, pointer=True, keyboard=True, background=True):
    f = db.query(TenantFeatures).filter(TenantFeatures.tenant_id == TENANT_ID).one()
    f.desktop_control_enabled = desktop
    f.pointer_control_enabled = pointer
    f.keyboard_control_enabled = keyboard
    f.background_control_enabled = background
    db.add(f)
    db.commit()


def _seed_tenant_allowlist(db, bundles):
    f = db.query(TenantFeatures).filter(TenantFeatures.tenant_id == TENANT_ID).one()
    f.native_control_target_allowlist = list(bundles)
    db.add(f)
    db.commit()


def _enqueue_pointer(db, *, nonce="p", action="pointer_move", tool="desktop_pointer_move"):
    return enqueue_desktop_command(
        db,
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        request=DesktopCommandEnqueue(
            session_id=SESSION_ID,
            action=action,
            tool_name=tool,
            shell_id=None,
            nonce=nonce,
            payload={"x": 100, "y": 200, "target": {"bundle_id": CANARY_BUNDLE_ID, "action": action}},
        ),
    )


def _enqueue_background_dry_run(db, *, nonce="background-dry-run"):
    return enqueue_desktop_command(
        db,
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        request=DesktopCommandEnqueue(
            session_id=SESSION_ID,
            action="background_app_control_dry_run",
            tool_name="desktop_background_app_control_dry_run",
            shell_id=None,
            nonce=nonce,
            payload={
                "target": {
                    "bundle_id": CANARY_BUNDLE_ID,
                    "action": "background_app_control_dry_run",
                },
                "dry_run": True,
            },
        ),
    )


def test_observe_enqueue_denied_when_master_disabled(db_session, seeded):
    _set_capability_flags(db_session, desktop=False, pointer=True, keyboard=True)
    with patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value=_presence(),
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        with pytest.raises(HTTPException) as exc:
            _enqueue(db_session, nonce="observe-master-off", grant=False)
    assert exc.value.status_code == 403
    assert db_session.query(DesktopCommand).filter(
        DesktopCommand.nonce == "observe-master-off",
    ).count() == 0


def test_observe_approval_grant_denied_when_master_disabled(db_session, seeded):
    with patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value=_presence(),
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        command = _enqueue(db_session, nonce="observe-grant-master-off", grant=False)

    _set_capability_flags(db_session, desktop=False, pointer=True, keyboard=True)
    with pytest.raises(HTTPException) as exc:
        create_desktop_approval_grant(
            db_session,
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            request=DesktopCommandApprovalGrantCreate(
                session_id=SESSION_ID,
                desktop_command_id=command.id,
                risk_tier="observe",
                capability=command.capability,
                expires_in_seconds=60,
            ),
        )

    assert exc.value.status_code == 403
    assert db_session.query(DesktopCommandApprovalGrant).filter(
        DesktopCommandApprovalGrant.desktop_command_id == command.id,
    ).count() == 0


def test_observe_claim_denies_when_master_revoked_midflight(db_session, seeded):
    with patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value=_presence(),
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        command = _enqueue(db_session, nonce="observe-claim-master-off", grant=True)
        grant = db_session.query(DesktopCommandApprovalGrant).filter(
            DesktopCommandApprovalGrant.desktop_command_id == command.id,
        ).one()

        _set_capability_flags(db_session, desktop=False, pointer=True, keyboard=True)
        claimed, event, _session_event = claim_next_desktop_command(
            db_session,
            user=seeded,
            device_token=DEVICE_TOKEN,
            claim=DesktopCommandClaim(session_id=SESSION_ID, shell_id=SHELL_ID, lease_seconds=30),
        )

    assert claimed is None
    refreshed = db_session.query(DesktopCommand).filter(DesktopCommand.id == command.id).one()
    assert refreshed.status == "denied"
    assert event is not None
    assert event.event_type == "desktop_command_envelope_denied"
    assert event.outcome == "denied"
    assert event.reason == "desktop observation denied; capture_screenshot denied"
    assert (event.event_metadata or {}).get("denial_code") == "observation_denied"
    db_session.refresh(grant)
    assert grant.status == "active"
    assert grant.remaining_actions == 1


def test_native_control_enqueue_denied_when_master_disabled(db_session, seeded):
    _set_capability_flags(db_session, desktop=False, pointer=True, keyboard=True)
    with patch.object(
        desktop_control_service.settings, "DESKTOP_CONTROL_CANARY_BUNDLE_ALLOWLIST", [CANARY_BUNDLE_ID],
    ), patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence", return_value=_presence(),
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        with pytest.raises(HTTPException) as exc:
            _enqueue_pointer(db_session, nonce="master-off")
    assert exc.value.status_code == 403
    # nothing queued — fail-closed BEFORE the command row is committed
    assert db_session.query(DesktopCommand).filter(
        DesktopCommand.capability == "pointer_control"
    ).count() == 0


def test_native_control_enqueue_denied_when_pointer_capability_disabled(db_session, seeded):
    # master ON, perception works, but pointer actuation is OFF → pointer denied
    _set_capability_flags(db_session, desktop=True, pointer=False, keyboard=True)
    with patch.object(
        desktop_control_service.settings, "DESKTOP_CONTROL_CANARY_BUNDLE_ALLOWLIST", [CANARY_BUNDLE_ID],
    ), patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence", return_value=_presence(),
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        with pytest.raises(HTTPException) as exc:
            _enqueue_pointer(db_session, nonce="pointer-off")
    assert exc.value.status_code == 403


def test_native_control_enqueue_denied_when_keyboard_capability_disabled(db_session, seeded):
    # keyboard OFF denies keyboard even while pointer is ON (per-action-class gate)
    _set_capability_flags(db_session, desktop=True, pointer=True, keyboard=False)
    with patch.object(
        desktop_control_service.settings, "DESKTOP_CONTROL_CANARY_BUNDLE_ALLOWLIST", [CANARY_BUNDLE_ID],
    ), patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence", return_value=_presence(),
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        with pytest.raises(HTTPException) as exc:
            enqueue_desktop_command(
                db_session,
                tenant_id=TENANT_ID,
                user_id=USER_ID,
                request=DesktopCommandEnqueue(
                    session_id=SESSION_ID,
                    action="keyboard_type",
                    tool_name="desktop_keyboard_type",
                    shell_id=None,
                    nonce="keyboard-off",
                    payload={"text": "hi", "target": {"bundle_id": CANARY_BUNDLE_ID, "action": "keyboard_type"}},
                ),
            )
    assert exc.value.status_code == 403
    # pointer is still permitted in the same tenant (independent capability)
    with patch.object(
        desktop_control_service.settings, "DESKTOP_CONTROL_CANARY_BUNDLE_ALLOWLIST", [CANARY_BUNDLE_ID],
    ), patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence", return_value=_presence(),
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        command, _e, _s = _enqueue_pointer(db_session, nonce="pointer-still-ok")
    assert command.status == "pending"
    assert command.capability == "pointer_control"


def test_background_control_dry_run_claim_completes_no_op_without_envelope(db_session, seeded):
    with patch.object(
        desktop_control_service.settings, "DESKTOP_CONTROL_CANARY_BUNDLE_ALLOWLIST", [CANARY_BUNDLE_ID],
    ), patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence", return_value=_presence(),
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        command, queued_event, _queued_session = _enqueue_background_dry_run(
            db_session,
            nonce="background-dry-run-claim",
        )
        claimed, event, _session_event = claim_next_desktop_command(
            db_session,
            user=seeded,
            device_token=DEVICE_TOKEN,
            claim=DesktopCommandClaim(session_id=SESSION_ID, shell_id=SHELL_ID, lease_seconds=30),
        )

    assert command.capability == "background_control"
    assert command.approval_id is None
    assert command.payload["mode"] == "background_control_dry_run"
    assert queued_event.event_metadata["dry_run"] is True
    assert queued_event.event_metadata["native_envelope"] is False

    assert claimed is not None
    assert claimed.id == command.id
    assert claimed.status == "no_op"
    assert claimed.claimed_at is not None
    assert claimed.completed_at is not None
    assert claimed.payload["dry_run"]["native_envelope"] is False
    assert claimed.payload["dry_run"]["completed_without_native_actuation"] is True
    assert "command_envelope" not in claimed.payload
    assert "approval" not in claimed.payload
    assert event.event_type == "desktop_command_completed"
    assert event.outcome == "no_op"
    assert event.event_metadata["dry_run"] is True
    assert event.event_metadata["native_envelope"] is False

    claim_event = db_session.query(DesktopCommandEvent).filter(
        DesktopCommandEvent.desktop_command_id == command.id,
        DesktopCommandEvent.event_type == "desktop_command_claimed",
    ).one()
    assert claim_event.outcome == "started"
    assert claim_event.event_metadata["dry_run"] is True
    assert db_session.query(DesktopCommandEnvelopeNonce).filter(
        DesktopCommandEnvelopeNonce.desktop_command_id == command.id,
    ).count() == 0
    assert db_session.query(DesktopCommandApprovalGrant).filter(
        DesktopCommandApprovalGrant.desktop_command_id == command.id,
    ).count() == 0


def test_background_control_dry_run_stop_preempts_pending_before_claim(db_session, seeded):
    with patch.object(
        desktop_control_service.settings, "DESKTOP_CONTROL_CANARY_BUNDLE_ALLOWLIST", [CANARY_BUNDLE_ID],
    ), patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence", return_value=_presence(),
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        command, _event, _session = _enqueue_background_dry_run(
            db_session,
            nonce="background-dry-run-stop",
        )
        count, events, _session_events = preempt_desktop_commands_for_stop(
            db_session,
            user=seeded,
            device_token=DEVICE_TOKEN,
            stop=DesktopCommandStop(session_id=SESSION_ID, shell_id=SHELL_ID),
        )
        claimed, event, _claim_session = claim_next_desktop_command(
            db_session,
            user=seeded,
            device_token=DEVICE_TOKEN,
            claim=DesktopCommandClaim(session_id=SESSION_ID, shell_id=SHELL_ID, lease_seconds=30),
        )

    assert count == 1
    assert events[0].desktop_command_id == command.id
    refreshed = db_session.query(DesktopCommand).filter(DesktopCommand.id == command.id).one()
    assert refreshed.status == "preempted"
    assert claimed is None
    assert event is None


def test_background_control_dry_run_denied_when_background_capability_disabled(db_session, seeded):
    _set_capability_flags(db_session, desktop=True, pointer=True, keyboard=True, background=False)
    with patch.object(
        desktop_control_service.settings, "DESKTOP_CONTROL_CANARY_BUNDLE_ALLOWLIST", [CANARY_BUNDLE_ID],
    ), patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence", return_value=_presence(),
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        with pytest.raises(HTTPException) as exc:
            _enqueue_background_dry_run(db_session, nonce="background-off")

    assert exc.value.status_code == 403
    assert db_session.query(DesktopCommand).filter(
        DesktopCommand.capability == "background_control",
    ).count() == 0


def test_background_control_dry_run_enqueue_does_not_require_permission_readiness(db_session, seeded):
    presence = _presence()
    presence.pop("shell_permission_readiness")
    with patch.object(
        desktop_control_service.settings, "DESKTOP_CONTROL_CANARY_BUNDLE_ALLOWLIST", [CANARY_BUNDLE_ID],
    ), patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence", return_value=presence,
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        command, queued_event, _session_event = _enqueue_background_dry_run(
            db_session,
            nonce="background-no-readiness",
        )

    assert command.capability == "background_control"
    assert command.status == "pending"
    assert command.payload["dry_run"]["native_envelope"] is False
    assert queued_event.event_metadata["dry_run"] is True
    assert queued_event.event_metadata["native_envelope"] is False


def test_command_status_snapshot_is_display_safe(db_session, seeded):
    now = _utcnow()
    command = DesktopCommand(
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        session_id=SESSION_ID,
        shell_id=SHELL_ID,
        device_id=DEVICE_ID,
        capability="keyboard_control",
        status="succeeded",
        source="mcp",
        nonce="status-safe",
        payload={
            "action": "keyboard_type",
            "tool_name": "desktop_keyboard_type",
            "mode": "control_locked",
            "args": {"text": "must not leak typed text"},
            "command_envelope": {"signature": "must-not-leak"},
            "approval": {"approval_id": "must-not-leak"},
        },
        claimed_at=now,
        completed_at=now,
        created_at=now,
        updated_at=now,
    )
    db_session.add(command)
    db_session.flush()
    event = DesktopCommandEvent(
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        session_id=SESSION_ID,
        desktop_command_id=command.id,
        correlation_id=command.correlation_id,
        event_type="desktop_command_completed",
        source="tauri",
        action="keyboard_type",
        capability="keyboard_control",
        outcome="succeeded",
        mode="control_locked",
        shell_id=SHELL_ID,
        device_id=DEVICE_ID,
        event_metadata={
            "result_kind": "json",
            "result_size_chars": 42,
            "raw_clipboard_text": "must not leak metadata",
            "args_text": "must not leak metadata",
        },
        created_at=now,
    )
    wrong_user_event = DesktopCommandEvent(
        tenant_id=TENANT_ID,
        user_id=USER_ID_2,
        session_id=SESSION_ID,
        desktop_command_id=command.id,
        correlation_id=command.correlation_id,
        event_type="desktop_command_completed",
        source="tauri",
        action="keyboard_type",
        capability="keyboard_control",
        outcome="succeeded",
        mode="control_locked",
        shell_id=SHELL_ID,
        device_id=DEVICE_ID,
        event_metadata={"result_kind": "text", "result_size_chars": 99},
        created_at=now,
    )
    db_session.add_all([event, wrong_user_event])
    db_session.commit()

    snapshot = get_desktop_command_status_snapshot(
        db_session,
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        command_id=command.id,
        session_id=SESSION_ID,
    )
    payload = display_safe_command_status(snapshot)
    rendered = str(payload)

    assert payload["command"]["action"] == "keyboard_type"
    assert payload["command"]["tool_name"] == "desktop_keyboard_type"
    assert payload["events"][0]["metadata"] == {
        "result_kind": "json",
        "result_size_chars": 42,
    }
    assert len(payload["events"]) == 1
    assert "payload" not in payload["command"]
    assert "must not leak" not in rendered
    assert "must-not-leak" not in rendered
    assert "command_envelope" not in rendered


def test_command_status_snapshot_denies_cross_user(db_session, seeded):
    now = _utcnow()
    command = DesktopCommand(
        tenant_id=TENANT_ID,
        user_id=USER_ID_2,
        session_id=SESSION_ID,
        shell_id=SHELL_ID,
        device_id=DEVICE_ID,
        capability="background_control",
        status="no_op",
        source="mcp",
        payload={
            "action": "background_app_control_dry_run",
            "tool_name": "desktop_background_app_control_dry_run",
            "mode": "background_control_dry_run",
        },
        completed_at=now,
        created_at=now,
        updated_at=now,
    )
    db_session.add(command)
    db_session.commit()

    with pytest.raises(HTTPException) as exc:
        get_desktop_command_status_snapshot(
            db_session,
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            command_id=command.id,
        )

    assert exc.value.status_code == 404


def test_native_control_claim_denies_when_capability_revoked_midflight(db_session, seeded):
    # The REAL boundary: enqueue with flags ON, then the tenant flag flips OFF
    # before the shell claims. Claim must DENY fail-closed (no signed envelope),
    # without breaking the claim channel.
    with patch.object(
        desktop_control_service.settings, "DESKTOP_CONTROL_CANARY_BUNDLE_ALLOWLIST", [CANARY_BUNDLE_ID],
    ), patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence", return_value=_presence(),
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        grant = create_desktop_approval_grant(
            db_session,
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            request=DesktopCommandApprovalGrantCreate(
                session_id=SESSION_ID,
                risk_tier="native_control",
                capability="pointer_control",
                target_binding={"bundle_id": CANARY_BUNDLE_ID, "action": "pointer_click"},
                expires_in_seconds=60,
            ),
        )
        command, _e, _s = enqueue_desktop_command(
            db_session,
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            request=DesktopCommandEnqueue(
                session_id=SESSION_ID,
                action="pointer_click",
                tool_name="desktop_pointer_click",
                shell_id=None,
                nonce="revoke-midflight",
                approval_id=grant.id,
                payload={"target": {"bundle_id": CANARY_BUNDLE_ID, "action": "pointer_click"}},
            ),
        )
        # policy flips OFF after enqueue, before claim
        _set_capability_flags(db_session, desktop=True, pointer=False, keyboard=True)
        claimed, event, _cs = claim_next_desktop_command(
            db_session,
            user=seeded,
            device_token=DEVICE_TOKEN,
            claim=DesktopCommandClaim(session_id=SESSION_ID, shell_id=SHELL_ID, lease_seconds=30),
        )

    assert claimed is None  # no signed envelope issued
    refreshed = db_session.query(DesktopCommand).filter(DesktopCommand.id == command.id).one()
    assert refreshed.status == "denied"
    assert event is not None and event.outcome == "denied"
    # canonical denial code for "the capability is off" (server + client parity)
    assert (event.event_metadata or {}).get("denial_code") == "native_control_disabled"
    # the denied command was the pointer command (capability carried on the row)
    assert refreshed.capability == "pointer_control"


def test_ensure_native_control_capability_enabled_gate_unit(db_session, seeded):
    from app.services.desktop_control_service import _ensure_native_control_capability_enabled as gate

    # fully enabled → both capabilities pass
    gate(db_session, TENANT_ID, "pointer_control")
    gate(db_session, TENANT_ID, "keyboard_control")

    # master off → everything denied even if the per-capability flag is on
    _set_capability_flags(db_session, desktop=False, pointer=True, keyboard=True)
    for cap in ("pointer_control", "keyboard_control"):
        with pytest.raises(HTTPException) as exc:
            gate(db_session, TENANT_ID, cap)
        assert exc.value.status_code == 403

    # master on, only pointer enabled → pointer ok, keyboard denied
    _set_capability_flags(db_session, desktop=True, pointer=True, keyboard=False)
    gate(db_session, TENANT_ID, "pointer_control")
    with pytest.raises(HTTPException):
        gate(db_session, TENANT_ID, "keyboard_control")

    # unknown native capability → fail-closed deny (a new action can't slip the gate)
    _set_capability_flags(db_session, desktop=True, pointer=True, keyboard=True)
    with pytest.raises(HTTPException) as exc:
        gate(db_session, TENANT_ID, "some_future_capability")
    assert exc.value.status_code == 403

    # no TenantFeatures row at all → deny
    db_session.query(TenantFeatures).filter(TenantFeatures.tenant_id == TENANT_ID).delete()
    db_session.commit()
    with pytest.raises(HTTPException):
        gate(db_session, TENANT_ID, "pointer_control")


def test_native_control_claim_denies_on_action_capability_mismatch(db_session, seeded):
    # Defense-in-depth (Codex review): the claim boundary derives the capability
    # from the ACTION and rejects a persisted command whose capability column
    # mismatches its action — even when BOTH capability flags are enabled — so a
    # corrupted/forged row can't check the wrong flag and reach envelope build.
    with patch.object(
        desktop_control_service.settings, "DESKTOP_CONTROL_CANARY_BUNDLE_ALLOWLIST", [CANARY_BUNDLE_ID],
    ), patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence", return_value=_presence(),
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        grant = create_desktop_approval_grant(
            db_session,
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            request=DesktopCommandApprovalGrantCreate(
                session_id=SESSION_ID,
                risk_tier="native_control",
                capability="pointer_control",
                target_binding={"bundle_id": CANARY_BUNDLE_ID, "action": "pointer_click"},
                expires_in_seconds=60,
            ),
        )
        command, _e, _s = enqueue_desktop_command(
            db_session,
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            request=DesktopCommandEnqueue(
                session_id=SESSION_ID,
                action="pointer_click",
                tool_name="desktop_pointer_click",
                shell_id=None,
                nonce="mismatch-row",
                approval_id=grant.id,
                payload={"target": {"bundle_id": CANARY_BUNDLE_ID, "action": "pointer_click"}},
            ),
        )
        # Corrupt the persisted capability to a DIFFERENT class than the action.
        # Both flags are enabled (seeded), so only the action-derivation guard can
        # catch this.
        command.capability = "keyboard_control"
        db_session.add(command)
        db_session.commit()
        claimed, event, _cs = claim_next_desktop_command(
            db_session,
            user=seeded,
            device_token=DEVICE_TOKEN,
            claim=DesktopCommandClaim(session_id=SESSION_ID, shell_id=SHELL_ID, lease_seconds=30),
        )

    assert claimed is None  # mismatch denied before envelope build
    refreshed = db_session.query(DesktopCommand).filter(DesktopCommand.id == command.id).one()
    assert refreshed.status == "denied"
    assert event is not None and event.outcome == "denied"


# ── PR4c: per-tenant target allowlist (effective = per-tenant ∩ floor) ─────────
# A native-control target is allowlisted only when the bundle is in BOTH the
# per-tenant native_control_target_allowlist AND the global env floor. An empty
# per-tenant list denies everything (fail-closed) even when the floor is non-empty.


def test_allowlist_empty_per_tenant_denies_even_with_nonempty_floor(db_session, seeded):
    _seed_tenant_allowlist(db_session, [])  # explicit opt-out
    with patch.object(
        desktop_control_service.settings, "DESKTOP_CONTROL_CANARY_BUNDLE_ALLOWLIST", [CANARY_BUNDLE_ID],
    ), patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence", return_value=_presence(),
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        with pytest.raises(HTTPException) as exc:
            _enqueue_pointer(db_session, nonce="empty-pt-denies")
    assert exc.value.status_code == 422  # target not allowlisted


def test_allowlist_per_tenant_bundle_not_in_floor_denies(db_session, seeded):
    # tenant opts a bundle in, but it is NOT in the platform floor → effective
    # excludes it (the floor is a hard ceiling) → deny.
    _seed_tenant_allowlist(db_session, [CANARY_BUNDLE_ID])
    with patch.object(
        desktop_control_service.settings, "DESKTOP_CONTROL_CANARY_BUNDLE_ALLOWLIST", [OTHER_CANARY_BUNDLE_ID],
    ), patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence", return_value=_presence(),
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        with pytest.raises(HTTPException) as exc:
            _enqueue_pointer(db_session, nonce="not-in-floor-denies")
    assert exc.value.status_code == 422


def test_allowlist_intersection_allows(db_session, seeded):
    # bundle in BOTH per-tenant list and floor → effective contains it → allowed
    _seed_tenant_allowlist(db_session, [CANARY_BUNDLE_ID, OTHER_CANARY_BUNDLE_ID])
    with patch.object(
        desktop_control_service.settings, "DESKTOP_CONTROL_CANARY_BUNDLE_ALLOWLIST", [CANARY_BUNDLE_ID],
    ), patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence", return_value=_presence(),
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        command, _e, _s = _enqueue_pointer(db_session, nonce="intersection-allows")
    assert command.status == "pending"
    assert command.capability == "pointer_control"
    assert command.payload["target"]["bundle_id"] == CANARY_BUNDLE_ID


def test_allowlist_no_tenant_features_row_denies(db_session, seeded):
    # belt-and-suspenders: with no TenantFeatures row the effective set is empty
    db_session.query(TenantFeatures).filter(TenantFeatures.tenant_id == TENANT_ID).delete()
    db_session.commit()
    from app.services.desktop_control_service import _effective_native_control_allowlist as eff
    with patch.object(
        desktop_control_service.settings, "DESKTOP_CONTROL_CANARY_BUNDLE_ALLOWLIST", [CANARY_BUNDLE_ID],
    ):
        assert eff(db_session, TENANT_ID) == set()


def test_effective_allowlist_is_intersection_unit(db_session, seeded):
    from app.services.desktop_control_service import _effective_native_control_allowlist as eff
    _seed_tenant_allowlist(db_session, [CANARY_BUNDLE_ID, "com.example.NotInFloor"])
    with patch.object(
        desktop_control_service.settings,
        "DESKTOP_CONTROL_CANARY_BUNDLE_ALLOWLIST",
        [CANARY_BUNDLE_ID, OTHER_CANARY_BUNDLE_ID],
    ):
        # only the bundle in BOTH survives
        assert eff(db_session, TENANT_ID) == {CANARY_BUNDLE_ID}


def test_allowlist_revoked_after_enqueue_denies_at_claim(db_session, seeded):
    # PR4c claim-time enforcement: a command enqueued while allowlisted cannot be
    # claimed (no signed envelope) once the per-tenant allowlist is revoked — the
    # grant-match allowlist check denies. Capability flags stay ON, so the ONLY
    # thing denying here is the allowlist.
    encoded_private_key = _b64url(ED25519_PRIVATE_KEY_BYTES)
    _seed_tenant_allowlist(db_session, [CANARY_BUNDLE_ID])
    with patch.object(
        desktop_control_service.settings, "DESKTOP_CONTROL_CANARY_BUNDLE_ALLOWLIST", [CANARY_BUNDLE_ID],
    ), patch.object(
        desktop_control_service.settings, "DESKTOP_COMMAND_ENVELOPE_SIGNING_ALGORITHM", "Ed25519",
    ), patch.object(
        desktop_control_service.settings, "DESKTOP_COMMAND_ENVELOPE_ED25519_PRIVATE_KEY", encoded_private_key,
    ), patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence", return_value=_presence(),
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        grant = create_desktop_approval_grant(
            db_session, tenant_id=TENANT_ID, user_id=USER_ID,
            request=DesktopCommandApprovalGrantCreate(
                session_id=SESSION_ID, risk_tier="native_control", capability="pointer_control",
                target_binding={"bundle_id": CANARY_BUNDLE_ID, "action": "pointer_click"},
                expires_in_seconds=60,
            ),
        )
        command, _e, _s = enqueue_desktop_command(
            db_session, tenant_id=TENANT_ID, user_id=USER_ID,
            request=DesktopCommandEnqueue(
                session_id=SESSION_ID, action="pointer_click", tool_name="desktop_pointer_click",
                shell_id=None, nonce="revoke-allowlist-after-enqueue", approval_id=grant.id,
                payload={"target": {"bundle_id": CANARY_BUNDLE_ID, "action": "pointer_click"}},
            ),
        )
        # revoke the per-tenant allowlist AFTER enqueue, BEFORE claim
        _seed_tenant_allowlist(db_session, [])
        claimed, event, _cs = claim_next_desktop_command(
            db_session, user=seeded, device_token=DEVICE_TOKEN,
            claim=DesktopCommandClaim(session_id=SESSION_ID, shell_id=SHELL_ID, lease_seconds=30),
        )
    assert claimed is None  # no signed envelope issued — allowlist revoked
    refreshed = db_session.query(DesktopCommand).filter(DesktopCommand.id == command.id).one()
    assert refreshed.status == "denied"
    assert event is not None
    assert event.event_type == "desktop_command_approval_denied"
    assert event.outcome == "denied"
    assert event.reason == "desktop command approval grant binding mismatch"
    assert (event.event_metadata or {}).get("denial_code") == "approval_binding_mismatch"
    assert "command_envelope" not in (refreshed.payload or {})  # never reached envelope issuance


def test_allowlist_revoked_after_claim_does_not_corrupt_completion(db_session, seeded):
    # Codex IMPORTANT: completion verifies the IMMUTABLE signed envelope binding,
    # NOT the mutable current allowlist. Revoking the allowlist AFTER the envelope
    # was issued must NOT mis-record an already-authorized actuation as denied.
    encoded_private_key = _b64url(ED25519_PRIVATE_KEY_BYTES)
    _seed_tenant_allowlist(db_session, [CANARY_BUNDLE_ID])
    with patch.object(
        desktop_control_service.settings, "DESKTOP_CONTROL_CANARY_BUNDLE_ALLOWLIST", [CANARY_BUNDLE_ID],
    ), patch.object(
        desktop_control_service.settings, "DESKTOP_COMMAND_ENVELOPE_SIGNING_ALGORITHM", "Ed25519",
    ), patch.object(
        desktop_control_service.settings, "DESKTOP_COMMAND_ENVELOPE_ED25519_PRIVATE_KEY", encoded_private_key,
    ), patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence", return_value=_presence(),
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        grant = create_desktop_approval_grant(
            db_session, tenant_id=TENANT_ID, user_id=USER_ID,
            request=DesktopCommandApprovalGrantCreate(
                session_id=SESSION_ID, risk_tier="native_control", capability="pointer_control",
                target_binding={"bundle_id": CANARY_BUNDLE_ID, "action": "pointer_click"},
                expires_in_seconds=60,
            ),
        )
        command, _e, _s = enqueue_desktop_command(
            db_session, tenant_id=TENANT_ID, user_id=USER_ID,
            request=DesktopCommandEnqueue(
                session_id=SESSION_ID, action="pointer_click", tool_name="desktop_pointer_click",
                shell_id=None, nonce="revoke-allowlist-after-claim", approval_id=grant.id,
                payload={"target": {"bundle_id": CANARY_BUNDLE_ID, "action": "pointer_click"}},
            ),
        )
        claimed, _event, _cs = claim_next_desktop_command(
            db_session, user=seeded, device_token=DEVICE_TOKEN,
            claim=DesktopCommandClaim(session_id=SESSION_ID, shell_id=SHELL_ID, lease_seconds=30),
        )
        assert claimed is not None  # envelope issued while allowlisted
        envelope = claimed.payload["command_envelope"]
        # revoke the per-tenant allowlist AFTER the envelope was issued
        _seed_tenant_allowlist(db_session, [])
        completed, complete_event, _ccs, idempotent = complete_desktop_command(
            db_session, user=seeded, device_token=DEVICE_TOKEN,
            completion=DesktopCommandCompletion(
                command_id=command.id, shell_id=SHELL_ID, status="succeeded",
                metadata={"envelope_nonce": envelope["nonce"]},
            ),
        )
    # completion trusts the signed envelope binding — NOT denied by the revoke
    assert completed.status == "succeeded"
    assert complete_event.event_type == "desktop_command_completed"
    assert idempotent is False
