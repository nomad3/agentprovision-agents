"""Remedia PharmApp tools for authenticated e-commerce operations.

Provides OTP authentication and order management for the Remedia
medication marketplace. Auth is synchronous (interactive chat),
order creation triggers a Temporal workflow for durable tracking.
"""
import json
import logging
from typing import Optional

import httpx

from config.settings import settings

logger = logging.getLogger(__name__)

_remedia_client: Optional[httpx.AsyncClient] = None
_api_client: Optional[httpx.AsyncClient] = None


def _get_remedia_client() -> httpx.AsyncClient:
    global _remedia_client
    if _remedia_client is None:
        _remedia_client = httpx.AsyncClient(
            base_url=settings.remedia_api_url,
            timeout=30.0,
        )
    return _remedia_client


def _get_api_client() -> httpx.AsyncClient:
    global _api_client
    if _api_client is None:
        _api_client = httpx.AsyncClient(
            base_url=settings.api_base_url,
            timeout=30.0,
        )
    return _api_client


async def _get_stored_token(phone_number: str) -> Optional[str]:
    """Retrieve stored Remedia auth token for a phone number."""
    client = _get_api_client()
    try:
        resp = await client.get(
            f"/api/v1/remedia/token/{phone_number}",
            headers={"X-Internal-Key": settings.mcp_api_key},
        )
        if resp.status_code == 200:
            data = resp.json()
            return data.get("token")
    except Exception:
        logger.exception("Failed to retrieve stored token")
    return None


async def _store_token(phone_number: str, token: str, tenant_id: str) -> bool:
    """Store Remedia auth token for a phone number."""
    client = _get_api_client()
    try:
        resp = await client.post(
            "/api/v1/remedia/token",
            headers={"X-Internal-Key": settings.mcp_api_key},
            json={"phone": phone_number, "token": token, "tenant_id": tenant_id},
        )
        return resp.status_code == 200
    except Exception:
        logger.exception("Failed to store token")
    return False


async def remedia_auth(
    tenant_id: str,
    action: str,
    phone_number: str,
    code: Optional[str] = None,
) -> dict:
    """Authenticate a WhatsApp user with Remedia via OTP.

    This tool handles the OTP authentication flow for the Remedia pharmacy
    marketplace. Users receive a one-time code via WhatsApp and verify it
    to get an access token for placing orders.

    Args:
        tenant_id: Tenant context. Use "auto" if unknown.
        action: One of:
            - "request_otp": Send OTP code to user's WhatsApp
            - "verify_otp": Verify OTP code and store auth token
            - "check_auth": Check if user is already authenticated
        phone_number: User's phone number (Chilean format, e.g. "56954791985")
        code: OTP code from user (required for verify_otp action)

    Returns:
        Dict with success status and relevant data.
    """
    remedia = _get_remedia_client()

    try:
        if action == "request_otp":
            resp = await remedia.post(
                "/auth/otp/request",
                json={"phone_number": phone_number},
            )
            if resp.status_code == 200:
                return {"success": True, "message": "OTP enviado a tu WhatsApp. Responde con el código."}
            return {"success": False, "error": f"Failed to send OTP: {resp.text[:200]}"}

        elif action == "verify_otp":
            if not code:
                return {"success": False, "error": "code is required for verify_otp"}
            resp = await remedia.post(
                "/auth/otp/verify",
                json={"phone_number": phone_number, "code": code},
            )
            if resp.status_code == 200:
                data = resp.json()
                token = data.get("access_token")
                if token:
                    await _store_token(phone_number, token, tenant_id)
                    return {"success": True, "message": "Autenticación exitosa. Ya puedes realizar pedidos.", "authenticated": True}
                return {"success": False, "error": "No access_token in response"}
            return {"success": False, "error": "Código inválido o expirado. Solicita uno nuevo."}

        elif action == "check_auth":
            token = await _get_stored_token(phone_number)
            if not token:
                return {"success": True, "authenticated": False, "message": "Usuario no autenticado. Usa request_otp primero."}
            resp = await remedia.get(
                "/auth/profile",
                headers={"Authorization": f"Bearer {token}"},
            )
            if resp.status_code == 200:
                profile = resp.json()
                return {"success": True, "authenticated": True, "profile": profile}
            return {"success": True, "authenticated": False, "message": "Token expirado. Solicita nuevo OTP."}

        else:
            return {"error": f"Unknown action: {action}. Use request_otp, verify_otp, or check_auth."}

    except Exception as e:
        logger.exception("remedia_auth error")
        return {"error": f"Auth failed: {str(e)}"}


async def remedia_order(
    tenant_id: str,
    action: str,
    phone_number: str,
    pharmacy_id: Optional[str] = None,
    items: Optional[str] = None,
    payment_provider: Optional[str] = None,
    order_id: Optional[str] = None,
    medication_id: Optional[str] = None,
) -> dict:
    """Manage orders on Remedia — create orders via Temporal workflow, query status directly.

    IMPORTANT: The user must be authenticated first (use remedia_auth).
    Order creation triggers a durable Temporal workflow for payment tracking.

    Args:
        tenant_id: Tenant context. Use "auto" if unknown.
        action: One of:
            - "create": Place a new order (triggers Temporal workflow)
            - "list": List user's orders
            - "status": Get specific order status
            - "add_favorite": Add medication to favorites
            - "list_favorites": List favorite medications
        phone_number: User's phone number for token lookup.
        pharmacy_id: UUID of pharmacy (required for create).
        items: JSON string of order items, e.g.
            '[{"medication_id": "uuid", "price_id": "uuid", "quantity": 1}]'
            Required for create action.
        payment_provider: One of: mercadopago, transbank, cash_on_delivery, bank_transfer.
            Required for create action.
        order_id: UUID of existing order (for status action).
        medication_id: UUID of medication (for add_favorite action).

    Returns:
        Dict with order data or error message.
    """
    token = await _get_stored_token(phone_number)
    if not token:
        return {
            "error": "Usuario no autenticado. Usa remedia_auth con action='request_otp' primero.",
            "needs_auth": True,
        }

    remedia = _get_remedia_client()
    auth_headers = {"Authorization": f"Bearer {token}"}

    try:
        if action == "create":
            if not all([pharmacy_id, items, payment_provider]):
                return {"error": "pharmacy_id, items, and payment_provider are required for create."}

            parsed_items = json.loads(items) if isinstance(items, str) else items

            # Trigger Temporal workflow via ServiceTsunami API
            api = _get_api_client()
            resp = await api.post(
                "/api/v1/remedia/orders",
                headers={"X-Internal-Key": settings.mcp_api_key},
                json={
                    "phone_number": phone_number,
                    "tenant_id": tenant_id,
                    "token": token,
                    "pharmacy_id": pharmacy_id,
                    "items": parsed_items,
                    "payment_provider": payment_provider,
                },
            )
            if resp.status_code == 200:
                return resp.json()
            return {"error": f"Order creation failed: {resp.text[:300]}"}

        elif action == "list":
            resp = await remedia.get("/orders/", headers=auth_headers)
            if resp.status_code == 200:
                orders = resp.json()
                if isinstance(orders, list):
                    return {"success": True, "orders": orders[:20], "count": len(orders)}
                return {"success": True, "orders": orders}
            return {"error": f"Failed to list orders: {resp.text[:200]}"}

        elif action == "status":
            if not order_id:
                return {"error": "order_id is required for status action."}
            resp = await remedia.get(f"/orders/{order_id}/status", headers=auth_headers)
            if resp.status_code == 200:
                return {"success": True, "order": resp.json()}
            return {"error": f"Failed to get order status: {resp.text[:200]}"}

        elif action == "add_favorite":
            if not medication_id:
                return {"error": "medication_id is required for add_favorite."}
            resp = await remedia.post(
                "/favorites/",
                headers=auth_headers,
                json={"medication_id": medication_id},
            )
            if resp.status_code in (200, 201):
                return {"success": True, "favorite": resp.json()}
            return {"error": f"Failed to add favorite: {resp.text[:200]}"}

        elif action == "list_favorites":
            resp = await remedia.get("/favorites/", headers=auth_headers)
            if resp.status_code == 200:
                return {"success": True, "favorites": resp.json()}
            return {"error": f"Failed to list favorites: {resp.text[:200]}"}

        else:
            return {"error": f"Unknown action: {action}. Use create, list, status, add_favorite, or list_favorites."}

    except json.JSONDecodeError:
        return {"error": "Invalid items JSON format. Expected: [{\"medication_id\": \"uuid\", \"price_id\": \"uuid\", \"quantity\": 1}]"}
    except Exception as e:
        logger.exception("remedia_order error")
        return {"error": f"Order operation failed: {str(e)}"}
