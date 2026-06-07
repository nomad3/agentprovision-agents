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
    enqueue_desktop_command,
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


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


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
    db_session.add_all([tenant, user, session, device])
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
    db_session.add_all([tenant, user, session, device])
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
        assert envelope["key_id"] == "agentprovision-desktop-command-ed25519-v1"
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


def test_native_control_command_enqueue_is_denied_before_claim(db_session, seeded):
    with patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value=_presence(),
    ), patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        command, event, _session_event = enqueue_desktop_command(
            db_session,
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            request=DesktopCommandEnqueue(
                session_id=SESSION_ID,
                action="pointer_click",
                tool_name="desktop_pointer_click",
                shell_id=None,
                nonce="native-pointer-denied",
                payload={
                    "x": 100,
                    "y": 200,
                    "raw_target_text": "must not persist",
                },
            ),
        )
        claimed, claim_event, _claim_session_event = claim_next_desktop_command(
            db_session,
            user=seeded,
            device_token=DEVICE_TOKEN,
            claim=DesktopCommandClaim(session_id=SESSION_ID, shell_id=SHELL_ID, lease_seconds=30),
        )

    assert command.status == "denied"
    assert command.capability == "pointer_control"
    assert command.completed_at is not None
    assert command.lease_expires_at is None
    assert command.payload["mode"] == "control_locked"
    assert event.event_type == "desktop_command_completed"
    assert event.outcome == "denied"
    assert event.reason == "desktop native control disabled; pointer_click denied"
    assert event.event_metadata["result_kind"] == "unsupported"
    assert "must not persist" not in str(command.payload)
    assert "must not persist" not in str(event.event_metadata)
    assert claimed is None
    assert claim_event is None


def test_native_control_denial_nonce_retry_is_idempotent(db_session, seeded):
    with patch(
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
                nonce="native-keyboard-denied",
                payload={"text": "must not persist"},
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
                nonce="native-keyboard-denied",
                payload={"text": "must not persist"},
            ),
        )[0]

    assert second.id == first.id
    events = db_session.query(DesktopCommandEvent).filter(
        DesktopCommandEvent.desktop_command_id == first.id,
        DesktopCommandEvent.event_type == "desktop_command_completed",
    ).all()
    assert len(events) == 1
    assert events[0].reason == "desktop native control disabled; keyboard_type denied"


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
