"""
Temporal workflow for Remedia e-commerce order lifecycle.

Handles: create order → send confirmation → monitor payment → notify delivery.
Each step is traced via ExecutionTrace for full audit trail.
"""
from temporalio import workflow
from datetime import timedelta
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class OrderItem:
    medication_id: str
    price_id: str
    quantity: int = 1


@dataclass
class RemediaOrderInput:
    phone_number: str
    tenant_id: str
    token: str
    pharmacy_id: str
    items: List[dict] = field(default_factory=list)
    payment_provider: str = "mercadopago"
    chat_session_id: Optional[str] = None


@workflow.defn(sandboxed=False)
class RemediaOrderWorkflow:
    """Durable order lifecycle for Remedia pharmacy marketplace.

    Steps:
    1. create_order — POST to Remedia API, get order_id + payment_url
    2. send_confirmation — WhatsApp message with order summary + payment link
    3. monitor_payment — Poll order status until paid or timeout (30 min)
    4. send_payment_confirmed — WhatsApp notification on payment success
    5. track_delivery — Poll until delivered, send status updates
    """

    @workflow.run
    async def run(self, input: RemediaOrderInput) -> dict:
        retry_policy = workflow.RetryPolicy(
            maximum_attempts=3,
            initial_interval=timedelta(seconds=10),
            backoff_coefficient=2.0,
        )

        workflow.logger.info(
            f"RemediaOrder: starting for phone={input.phone_number} "
            f"pharmacy={input.pharmacy_id} items={len(input.items)}"
        )

        # Step 1: Create order on Remedia
        order_result = await workflow.execute_activity(
            "create_remedia_order",
            args=[input],
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=retry_policy,
        )

        if order_result.get("error"):
            return {"status": "failed", "error": order_result["error"]}

        order_id = order_result["order_id"]
        payment_url = order_result.get("payment_url")
        total = order_result.get("total", 0)

        workflow.logger.info(f"RemediaOrder: created order {order_id}, total=${total}")

        # Step 2: Send order confirmation via WhatsApp
        await workflow.execute_activity(
            "send_remedia_notification",
            args=[{
                "phone_number": input.phone_number,
                "tenant_id": input.tenant_id,
                "message_type": "order_created",
                "order_id": order_id,
                "total": total,
                "payment_url": payment_url,
                "payment_provider": input.payment_provider,
            }],
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=retry_policy,
        )

        # Step 3: Monitor payment (poll every 30s for up to 30 min)
        if input.payment_provider in ("mercadopago", "transbank"):
            payment_result = await workflow.execute_activity(
                "monitor_remedia_payment",
                args=[{
                    "order_id": order_id,
                    "token": input.token,
                    "phone_number": input.phone_number,
                    "tenant_id": input.tenant_id,
                    "timeout_minutes": 30,
                }],
                start_to_close_timeout=timedelta(minutes=35),
                retry_policy=workflow.RetryPolicy(maximum_attempts=1),
            )

            if payment_result.get("paid"):
                workflow.logger.info(f"RemediaOrder: payment confirmed for {order_id}")

                # Step 4: Send payment confirmation
                await workflow.execute_activity(
                    "send_remedia_notification",
                    args=[{
                        "phone_number": input.phone_number,
                        "tenant_id": input.tenant_id,
                        "message_type": "payment_confirmed",
                        "order_id": order_id,
                        "total": total,
                    }],
                    start_to_close_timeout=timedelta(minutes=1),
                    retry_policy=retry_policy,
                )
            else:
                workflow.logger.info(f"RemediaOrder: payment not received for {order_id}")

        # Step 5: Track delivery (poll every 5 min for up to 24h)
        delivery_result = await workflow.execute_activity(
            "track_remedia_delivery",
            args=[{
                "order_id": order_id,
                "token": input.token,
                "phone_number": input.phone_number,
                "tenant_id": input.tenant_id,
            }],
            start_to_close_timeout=timedelta(hours=25),
            retry_policy=workflow.RetryPolicy(maximum_attempts=1),
        )

        final_status = delivery_result.get("status", "unknown")
        workflow.logger.info(f"RemediaOrder: completed with status={final_status}")

        return {
            "status": "completed",
            "order_id": order_id,
            "total": total,
            "payment_url": payment_url,
            "final_status": final_status,
        }
