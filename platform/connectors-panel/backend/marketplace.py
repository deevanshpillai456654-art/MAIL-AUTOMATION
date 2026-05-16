"""
Marketplace router — browse and install connectors from the catalog.
Prefix: /marketplace
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, status

from .db import get_panel_db
from .models import (
    APIResponse,
    ConnectorCategory,
    ConnectorInstallRequest,
    ConnectorStatus,
    InstalledConnector,
    MarketplaceConnector,
)
from ..shared.constants import CONNECTOR_CATEGORIES, FEATURED_CONNECTOR_IDS
from ..shared.utils import generate_connector_id, utc_now_str

router = APIRouter(prefix="/marketplace", tags=["marketplace"])


# ---------------------------------------------------------------------------
# Hardcoded catalog
# ---------------------------------------------------------------------------

_CATALOG: list[dict[str, Any]] = [
    # ── Communication ────────────────────────────────────────────────────────
    {
        "id": "whatsapp",
        "name": "WhatsApp Business",
        "version": "1.2.0",
        "category": "communication",
        "description": "Send and receive WhatsApp messages via the WhatsApp Business API. Supports media, templates, and read receipts.",
        "author": "MailPilot",
        "icon_url": "https://cdn.jsdelivr.net/npm/simple-icons@v9/icons/whatsapp.svg",
        "status": "inactive",
        "permissions": ["messages.read", "messages.send", "contacts.read", "media.upload"],
        "events": ["whatsapp.message.received", "whatsapp.message.sent", "whatsapp.status.updated", "whatsapp.media.received"],
        "supports_oauth": False,
        "supports_webhook": True,
        "supports_api_key": True,
        "multiTenant": True,
        "queue_enabled": True,
        "health_endpoint": "/health",
        "install_count": 8420,
        "rating": 4.7,
        "is_beta": False,
        "price_tier": "free",
    },
    {
        "id": "gmail",
        "name": "Gmail",
        "version": "2.0.1",
        "category": "communication",
        "description": "Integrate Gmail to send, receive, and process emails automatically. Full OAuth 2.0 support with Gmail API.",
        "author": "MailPilot",
        "icon_url": "https://cdn.jsdelivr.net/npm/simple-icons@v9/icons/gmail.svg",
        "status": "inactive",
        "permissions": ["gmail.read", "gmail.send", "gmail.modify", "contacts.read"],
        "events": ["email.received", "email.sent", "email.bounced", "email.opened"],
        "supports_oauth": True,
        "supports_webhook": False,
        "supports_api_key": False,
        "multiTenant": True,
        "queue_enabled": True,
        "health_endpoint": "/health",
        "install_count": 15320,
        "rating": 4.9,
        "is_beta": False,
        "price_tier": "free",
    },
    {
        "id": "openai",
        "name": "OpenAI",
        "version": "1.3.0",
        "category": "ai",
        "description": "Connect to OpenAI's GPT models for email classification, extraction, summarisation, and intelligent routing.",
        "author": "MailPilot",
        "icon_url": "https://cdn.jsdelivr.net/npm/simple-icons@v9/icons/openai.svg",
        "status": "inactive",
        "permissions": ["ai.classify", "ai.extract", "ai.chat", "ai.embed"],
        "events": ["ai.classification.completed", "ai.extraction.completed", "ai.summary.completed"],
        "supports_oauth": False,
        "supports_webhook": False,
        "supports_api_key": True,
        "multiTenant": True,
        "queue_enabled": True,
        "health_endpoint": "/health",
        "install_count": 12100,
        "rating": 4.8,
        "is_beta": False,
        "price_tier": "pro",
    },
    {
        "id": "ocr_engine",
        "name": "OCR Engine",
        "version": "1.1.0",
        "category": "ocr",
        "description": "Optical character recognition for invoices, receipts, and documents. Bridges to the platform OCR pipeline.",
        "author": "MailPilot",
        "icon_url": "https://cdn.jsdelivr.net/npm/simple-icons@v9/icons/readthedocs.svg",
        "status": "inactive",
        "permissions": ["documents.read", "documents.process", "ocr.results.write"],
        "events": ["ocr.document.processed", "ocr.document.failed"],
        "supports_oauth": False,
        "supports_webhook": False,
        "supports_api_key": True,
        "multiTenant": True,
        "queue_enabled": True,
        "health_endpoint": "/health",
        "install_count": 4300,
        "rating": 4.5,
        "is_beta": False,
        "price_tier": "pro",
    },
    {
        "id": "shopify",
        "name": "Shopify",
        "version": "1.4.2",
        "category": "ecommerce",
        "description": "Sync orders, products, and customers from Shopify. Receive real-time order webhooks and automate fulfilment workflows.",
        "author": "MailPilot",
        "icon_url": "https://cdn.jsdelivr.net/npm/simple-icons@v9/icons/shopify.svg",
        "status": "inactive",
        "permissions": ["orders.read", "orders.write", "products.read", "customers.read"],
        "events": ["order.created", "order.updated", "order.fulfilled", "order.cancelled", "product.created", "product.updated"],
        "supports_oauth": True,
        "supports_webhook": True,
        "supports_api_key": False,
        "multiTenant": True,
        "queue_enabled": True,
        "health_endpoint": "/health",
        "install_count": 9870,
        "rating": 4.6,
        "is_beta": False,
        "price_tier": "free",
    },
    {
        "id": "slack",
        "name": "Slack",
        "version": "1.2.0",
        "category": "communication",
        "description": "Send notifications and messages to Slack channels. Supports slash commands and interactive workflows.",
        "author": "MailPilot",
        "icon_url": "https://cdn.jsdelivr.net/npm/simple-icons@v9/icons/slack.svg",
        "status": "inactive",
        "permissions": ["slack.message.send", "slack.channels.read", "slack.users.read"],
        "events": ["slack.message.received", "slack.notification.sent"],
        "supports_oauth": True,
        "supports_webhook": True,
        "supports_api_key": False,
        "multiTenant": True,
        "queue_enabled": False,
        "health_endpoint": None,
        "install_count": 11200,
        "rating": 4.8,
        "is_beta": False,
        "price_tier": "free",
    },
    {
        "id": "webhook_listener",
        "name": "Generic Webhook Listener",
        "version": "1.0.0",
        "category": "webhook",
        "description": "Receive and route arbitrary inbound webhooks from any system to the MailPilot event bus.",
        "author": "MailPilot",
        "icon_url": "https://cdn.jsdelivr.net/npm/simple-icons@v9/icons/zapier.svg",
        "status": "inactive",
        "permissions": ["webhooks.receive", "events.publish"],
        "events": ["webhook.received", "webhook.failed"],
        "supports_oauth": False,
        "supports_webhook": True,
        "supports_api_key": False,
        "multiTenant": True,
        "queue_enabled": True,
        "health_endpoint": None,
        "install_count": 3200,
        "rating": 4.2,
        "is_beta": False,
        "price_tier": "free",
    },
    {
        "id": "erp_sync",
        "name": "ERP Sync",
        "version": "1.0.3",
        "category": "erp",
        "description": "Bidirectional sync with major ERP systems (SAP, Oracle, Microsoft Dynamics). Syncs invoices, POs, and financial records.",
        "author": "MailPilot",
        "icon_url": "https://cdn.jsdelivr.net/npm/simple-icons@v9/icons/sap.svg",
        "status": "inactive",
        "permissions": ["erp.read", "erp.write", "invoice.read", "invoice.write"],
        "events": ["erp.sync.completed", "erp.sync.failed", "erp.record.created", "erp.record.updated", "invoice.created", "invoice.paid"],
        "supports_oauth": False,
        "supports_webhook": False,
        "supports_api_key": True,
        "multiTenant": True,
        "queue_enabled": True,
        "health_endpoint": "/health",
        "install_count": 1850,
        "rating": 4.3,
        "is_beta": False,
        "price_tier": "enterprise",
    },
    {
        "id": "zoho_crm",
        "name": "Zoho CRM",
        "version": "1.1.0",
        "category": "crm",
        "description": "Sync contacts, deals, and leads from Zoho CRM. Trigger automated follow-ups based on CRM pipeline stages.",
        "author": "MailPilot",
        "icon_url": "https://cdn.jsdelivr.net/npm/simple-icons@v9/icons/zoho.svg",
        "status": "inactive",
        "permissions": ["contacts.read", "contacts.write", "deals.read", "deals.write"],
        "events": ["contact.created", "contact.updated", "deal.created", "deal.updated", "deal.closed"],
        "supports_oauth": True,
        "supports_webhook": True,
        "supports_api_key": False,
        "multiTenant": True,
        "queue_enabled": True,
        "health_endpoint": "/health",
        "install_count": 5100,
        "rating": 4.4,
        "is_beta": False,
        "price_tier": "pro",
    },
    {
        "id": "shipping_tracker",
        "name": "Shipping Tracker",
        "version": "1.0.1",
        "category": "tracking",
        "description": "Track shipments across major carriers (FedEx, UPS, DHL, USPS). Sends status updates and delivery notifications.",
        "author": "MailPilot",
        "icon_url": "https://cdn.jsdelivr.net/npm/simple-icons@v9/icons/fedex.svg",
        "status": "inactive",
        "permissions": ["shipments.read", "tracking.read", "notifications.send"],
        "events": ["shipment.created", "shipment.updated", "shipment.delivered", "shipment.failed"],
        "supports_oauth": False,
        "supports_webhook": True,
        "supports_api_key": True,
        "multiTenant": True,
        "queue_enabled": True,
        "health_endpoint": "/health",
        "install_count": 4700,
        "rating": 4.5,
        "is_beta": False,
        "price_tier": "free",
    },

    # ── ERP Connectors ───────────────────────────────────────────────────────
    {
        "id": "sap",
        "name": "SAP ERP",
        "version": "2.1.0",
        "category": "erp",
        "description": "Bidirectional integration with SAP S/4HANA and SAP ECC. Sync purchase orders, invoices, financial records, and master data in real time.",
        "author": "MailPilot",
        "icon_url": "https://cdn.jsdelivr.net/npm/simple-icons@v9/icons/sap.svg",
        "status": "inactive",
        "permissions": ["erp.read", "erp.write", "invoice.read", "invoice.write", "po.read", "po.write"],
        "events": ["erp.po.created", "erp.invoice.posted", "erp.payment.cleared", "erp.goods.received"],
        "supports_oauth": False, "supports_webhook": True, "supports_api_key": True,
        "multiTenant": True, "queue_enabled": True, "health_endpoint": "/health",
        "install_count": 2100, "rating": 4.5, "is_beta": False, "price_tier": "free",
    },
    {
        "id": "oracle_erp",
        "name": "Oracle ERP Cloud",
        "version": "1.4.0",
        "category": "erp",
        "description": "Connect Oracle ERP Cloud for financials, procurement, project management, and supply chain automation.",
        "author": "MailPilot",
        "icon_url": "https://cdn.jsdelivr.net/npm/simple-icons@v9/icons/oracle.svg",
        "status": "inactive",
        "permissions": ["erp.read", "erp.write", "finance.read", "procurement.write"],
        "events": ["oracle.invoice.created", "oracle.po.approved", "oracle.payment.made"],
        "supports_oauth": True, "supports_webhook": True, "supports_api_key": False,
        "multiTenant": True, "queue_enabled": True, "health_endpoint": "/health",
        "install_count": 1650, "rating": 4.4, "is_beta": False, "price_tier": "free",
    },
    {
        "id": "netsuite",
        "name": "NetSuite",
        "version": "1.3.0",
        "category": "erp",
        "description": "Oracle NetSuite ERP integration for order management, financials, inventory, and multi-subsidiary reporting.",
        "author": "MailPilot",
        "icon_url": "https://cdn.jsdelivr.net/npm/simple-icons@v9/icons/oracle.svg",
        "status": "inactive",
        "permissions": ["erp.read", "erp.write", "inventory.read", "orders.read"],
        "events": ["netsuite.order.created", "netsuite.invoice.generated", "netsuite.item.updated"],
        "supports_oauth": True, "supports_webhook": False, "supports_api_key": True,
        "multiTenant": True, "queue_enabled": True, "health_endpoint": None,
        "install_count": 1380, "rating": 4.3, "is_beta": False, "price_tier": "free",
    },
    {
        "id": "odoo",
        "name": "Odoo",
        "version": "1.5.0",
        "category": "erp",
        "description": "Open-source ERP integration with Odoo for sales, CRM, inventory, accounting, manufacturing, and HR modules.",
        "author": "MailPilot",
        "icon_url": "https://cdn.jsdelivr.net/npm/simple-icons@v9/icons/odoo.svg",
        "status": "inactive",
        "permissions": ["erp.read", "erp.write", "crm.read", "inventory.read"],
        "events": ["odoo.sale.confirmed", "odoo.invoice.created", "odoo.stock.moved"],
        "supports_oauth": False, "supports_webhook": True, "supports_api_key": True,
        "multiTenant": True, "queue_enabled": True, "health_endpoint": "/health",
        "install_count": 1920, "rating": 4.6, "is_beta": False, "price_tier": "free",
    },
    {
        "id": "erpnext",
        "name": "ERPNext",
        "version": "1.2.0",
        "category": "erp",
        "description": "Open-source ERPNext integration for manufacturing, distribution, retail, services, and education businesses.",
        "author": "MailPilot",
        "icon_url": "https://cdn.jsdelivr.net/npm/simple-icons@v9/icons/frappe.svg",
        "status": "inactive",
        "permissions": ["erp.read", "erp.write", "purchase.read", "accounts.read"],
        "events": ["erpnext.po.submitted", "erpnext.payment.entry", "erpnext.stock.entry"],
        "supports_oauth": False, "supports_webhook": True, "supports_api_key": True,
        "multiTenant": True, "queue_enabled": True, "health_endpoint": None,
        "install_count": 980, "rating": 4.2, "is_beta": False, "price_tier": "free",
    },
    {
        "id": "ms_dynamics",
        "name": "Microsoft Dynamics 365",
        "version": "1.6.0",
        "category": "erp",
        "description": "Microsoft Dynamics 365 Finance & Operations integration for enterprise-grade ERP, supply chain, and business intelligence.",
        "author": "MailPilot",
        "icon_url": "https://cdn.jsdelivr.net/npm/simple-icons@v9/icons/microsoft.svg",
        "status": "inactive",
        "permissions": ["dynamics.read", "dynamics.write", "finance.read", "supply_chain.read"],
        "events": ["dynamics.po.created", "dynamics.invoice.posted", "dynamics.shipment.confirmed"],
        "supports_oauth": True, "supports_webhook": True, "supports_api_key": False,
        "multiTenant": True, "queue_enabled": True, "health_endpoint": "/health",
        "install_count": 2450, "rating": 4.5, "is_beta": False, "price_tier": "free",
    },

    # ── CRM Connectors ───────────────────────────────────────────────────────
    {
        "id": "salesforce",
        "name": "Salesforce",
        "version": "2.2.0",
        "category": "crm",
        "description": "Full Salesforce CRM integration. Sync leads, contacts, opportunities, accounts, and automate sales workflows with Apex triggers.",
        "author": "MailPilot",
        "icon_url": "https://cdn.jsdelivr.net/npm/simple-icons@v9/icons/salesforce.svg",
        "status": "inactive",
        "permissions": ["contacts.read", "contacts.write", "leads.read", "leads.write", "opportunities.read", "opportunities.write"],
        "events": ["sf.lead.created", "sf.opportunity.won", "sf.contact.updated", "sf.account.created"],
        "supports_oauth": True, "supports_webhook": True, "supports_api_key": False,
        "multiTenant": True, "queue_enabled": True, "health_endpoint": "/health",
        "install_count": 8900, "rating": 4.8, "is_beta": False, "price_tier": "free",
    },
    {
        "id": "hubspot",
        "name": "HubSpot",
        "version": "1.8.0",
        "category": "crm",
        "description": "HubSpot CRM, Marketing Hub, and Sales Hub integration. Sync contacts, deals, pipelines, and trigger email sequences.",
        "author": "MailPilot",
        "icon_url": "https://cdn.jsdelivr.net/npm/simple-icons@v9/icons/hubspot.svg",
        "status": "inactive",
        "permissions": ["contacts.read", "contacts.write", "deals.read", "deals.write", "email.send"],
        "events": ["hubspot.contact.created", "hubspot.deal.stage_changed", "hubspot.email.opened"],
        "supports_oauth": True, "supports_webhook": True, "supports_api_key": True,
        "multiTenant": True, "queue_enabled": True, "health_endpoint": "/health",
        "install_count": 7200, "rating": 4.7, "is_beta": False, "price_tier": "free",
    },
    {
        "id": "freshsales",
        "name": "Freshsales",
        "version": "1.2.0",
        "category": "crm",
        "description": "Freshsales CRM integration for lead management, deal pipeline, AI-powered scoring, and automated follow-up sequences.",
        "author": "MailPilot",
        "icon_url": "https://cdn.jsdelivr.net/npm/simple-icons@v9/icons/freshworks.svg",
        "status": "inactive",
        "permissions": ["contacts.read", "leads.read", "deals.read", "email.send"],
        "events": ["freshsales.lead.created", "freshsales.deal.won", "freshsales.contact.updated"],
        "supports_oauth": True, "supports_webhook": True, "supports_api_key": True,
        "multiTenant": True, "queue_enabled": False, "health_endpoint": None,
        "install_count": 2100, "rating": 4.3, "is_beta": False, "price_tier": "free",
    },
    {
        "id": "pipedrive",
        "name": "Pipedrive",
        "version": "1.4.0",
        "category": "crm",
        "description": "Pipedrive CRM integration for visual pipeline management, deal tracking, activity automation, and sales reporting.",
        "author": "MailPilot",
        "icon_url": "https://cdn.jsdelivr.net/npm/simple-icons@v9/icons/pipedrive.svg",
        "status": "inactive",
        "permissions": ["deals.read", "contacts.read", "activities.write"],
        "events": ["pipedrive.deal.created", "pipedrive.deal.stage_changed", "pipedrive.activity.completed"],
        "supports_oauth": True, "supports_webhook": True, "supports_api_key": True,
        "multiTenant": True, "queue_enabled": False, "health_endpoint": None,
        "install_count": 3400, "rating": 4.5, "is_beta": False, "price_tier": "free",
    },

    # ── Shipping & Logistics ─────────────────────────────────────────────────
    {
        "id": "fedex",
        "name": "FedEx",
        "version": "1.3.0",
        "category": "tracking",
        "description": "FedEx shipping and tracking integration. Book shipments, generate labels, track packages, and receive delivery webhooks.",
        "author": "MailPilot",
        "icon_url": "https://cdn.jsdelivr.net/npm/simple-icons@v9/icons/fedex.svg",
        "status": "inactive",
        "permissions": ["shipments.read", "shipments.create", "tracking.read", "labels.generate"],
        "events": ["fedex.shipment.created", "fedex.package.in_transit", "fedex.package.delivered", "fedex.exception.raised"],
        "supports_oauth": False, "supports_webhook": True, "supports_api_key": True,
        "multiTenant": True, "queue_enabled": True, "health_endpoint": "/health",
        "install_count": 4100, "rating": 4.4, "is_beta": False, "price_tier": "free",
    },
    {
        "id": "ups",
        "name": "UPS",
        "version": "1.2.0",
        "category": "tracking",
        "description": "UPS logistics integration for shipment booking, real-time tracking, rate shopping, and automated delivery notifications.",
        "author": "MailPilot",
        "icon_url": "https://cdn.jsdelivr.net/npm/simple-icons@v9/icons/ups.svg",
        "status": "inactive",
        "permissions": ["shipments.read", "tracking.read", "rates.read"],
        "events": ["ups.shipment.booked", "ups.package.delivered", "ups.delivery.exception"],
        "supports_oauth": True, "supports_webhook": True, "supports_api_key": True,
        "multiTenant": True, "queue_enabled": True, "health_endpoint": None,
        "install_count": 3600, "rating": 4.3, "is_beta": False, "price_tier": "free",
    },
    {
        "id": "dhl",
        "name": "DHL Express",
        "version": "1.5.0",
        "category": "tracking",
        "description": "DHL Express integration for international shipment booking, AWB generation, real-time tracking, and customs documentation.",
        "author": "MailPilot",
        "icon_url": "https://cdn.jsdelivr.net/npm/simple-icons@v9/icons/dhl.svg",
        "status": "inactive",
        "permissions": ["shipments.create", "tracking.read", "awb.generate", "customs.submit"],
        "events": ["dhl.shipment.picked_up", "dhl.shipment.in_transit", "dhl.shipment.delivered", "dhl.customs.cleared"],
        "supports_oauth": False, "supports_webhook": True, "supports_api_key": True,
        "multiTenant": True, "queue_enabled": True, "health_endpoint": "/health",
        "install_count": 5200, "rating": 4.6, "is_beta": False, "price_tier": "free",
    },
    {
        "id": "delhivery",
        "name": "Delhivery",
        "version": "1.1.0",
        "category": "tracking",
        "description": "Delhivery logistics platform integration for domestic India shipments, COD management, and last-mile delivery tracking.",
        "author": "MailPilot",
        "icon_url": "https://cdn.jsdelivr.net/npm/simple-icons@v9/icons/deliveroo.svg",
        "status": "inactive",
        "permissions": ["shipments.create", "tracking.read", "cod.manage"],
        "events": ["delhivery.shipment.created", "delhivery.out_for_delivery", "delhivery.delivered", "delhivery.rto.initiated"],
        "supports_oauth": False, "supports_webhook": True, "supports_api_key": True,
        "multiTenant": True, "queue_enabled": True, "health_endpoint": None,
        "install_count": 2800, "rating": 4.2, "is_beta": False, "price_tier": "free",
    },
    {
        "id": "shiprocket",
        "name": "Shiprocket",
        "version": "1.3.0",
        "category": "tracking",
        "description": "Shiprocket multi-carrier aggregator for ecommerce shipping. Automatically select the best carrier, generate AWBs, and track shipments.",
        "author": "MailPilot",
        "icon_url": "https://cdn.jsdelivr.net/npm/simple-icons@v9/icons/shopify.svg",
        "status": "inactive",
        "permissions": ["shipments.create", "orders.sync", "tracking.read", "returns.manage"],
        "events": ["shiprocket.order.shipped", "shiprocket.shipment.delivered", "shiprocket.return.initiated"],
        "supports_oauth": True, "supports_webhook": True, "supports_api_key": True,
        "multiTenant": True, "queue_enabled": True, "health_endpoint": "/health",
        "install_count": 3100, "rating": 4.4, "is_beta": False, "price_tier": "free",
    },
    {
        "id": "aftership",
        "name": "AfterShip",
        "version": "1.4.0",
        "category": "tracking",
        "description": "AfterShip multi-carrier tracking aggregator. Unify tracking across 700+ carriers with automated customer notifications and branded tracking pages.",
        "author": "MailPilot",
        "icon_url": "https://cdn.jsdelivr.net/npm/simple-icons@v9/icons/aftership.svg",
        "status": "inactive",
        "permissions": ["tracking.read", "notifications.send", "analytics.read"],
        "events": ["aftership.tracking.created", "aftership.status.changed", "aftership.delivery.failed"],
        "supports_oauth": False, "supports_webhook": True, "supports_api_key": True,
        "multiTenant": True, "queue_enabled": True, "health_endpoint": "/health",
        "install_count": 4700, "rating": 4.7, "is_beta": False, "price_tier": "free",
    },
    {
        "id": "maersk",
        "name": "Maersk Tracking",
        "version": "1.0.0",
        "category": "tracking",
        "description": "Maersk container and BL tracking integration. Track container status, vessel position, port ETAs, and ocean freight milestones.",
        "author": "MailPilot",
        "icon_url": "https://cdn.jsdelivr.net/npm/simple-icons@v9/icons/maersk.svg",
        "status": "inactive",
        "permissions": ["containers.track", "bl.read", "vessel.read"],
        "events": ["maersk.container.gate_in", "maersk.vessel.departed", "maersk.container.delivered"],
        "supports_oauth": False, "supports_webhook": False, "supports_api_key": True,
        "multiTenant": True, "queue_enabled": True, "health_endpoint": None,
        "install_count": 820, "rating": 4.1, "is_beta": False, "price_tier": "free",
    },
    {
        "id": "msc_tracking",
        "name": "MSC Tracking",
        "version": "1.0.0",
        "category": "tracking",
        "description": "Mediterranean Shipping Company container tracking. Monitor container movements, vessel schedules, and port arrival/departure events.",
        "author": "MailPilot",
        "icon_url": "https://cdn.jsdelivr.net/npm/simple-icons@v9/icons/anchor.svg",
        "status": "inactive",
        "permissions": ["containers.track", "bl.read"],
        "events": ["msc.container.loaded", "msc.vessel.arrived", "msc.container.discharged"],
        "supports_oauth": False, "supports_webhook": False, "supports_api_key": True,
        "multiTenant": True, "queue_enabled": True, "health_endpoint": None,
        "install_count": 560, "rating": 4.0, "is_beta": True, "price_tier": "free",
    },

    # ── Ecommerce ─────────────────────────────────────────────────────────────
    {
        "id": "woocommerce",
        "name": "WooCommerce",
        "version": "1.6.0",
        "category": "ecommerce",
        "description": "WooCommerce WordPress integration. Sync orders, products, customers, and inventory with automated fulfillment and notification workflows.",
        "author": "MailPilot",
        "icon_url": "https://cdn.jsdelivr.net/npm/simple-icons@v9/icons/woocommerce.svg",
        "status": "inactive",
        "permissions": ["orders.read", "orders.write", "products.read", "customers.read"],
        "events": ["woo.order.created", "woo.order.completed", "woo.order.refunded", "woo.product.updated"],
        "supports_oauth": False, "supports_webhook": True, "supports_api_key": True,
        "multiTenant": True, "queue_enabled": True, "health_endpoint": None,
        "install_count": 6800, "rating": 4.5, "is_beta": False, "price_tier": "free",
    },
    {
        "id": "magento",
        "name": "Magento / Adobe Commerce",
        "version": "1.3.0",
        "category": "ecommerce",
        "description": "Adobe Commerce (Magento) integration for enterprise ecommerce. Sync catalog, orders, customers, and inventory across storefronts.",
        "author": "MailPilot",
        "icon_url": "https://cdn.jsdelivr.net/npm/simple-icons@v9/icons/magento.svg",
        "status": "inactive",
        "permissions": ["catalog.read", "orders.read", "orders.write", "customers.read"],
        "events": ["magento.order.placed", "magento.order.shipped", "magento.inventory.updated"],
        "supports_oauth": True, "supports_webhook": True, "supports_api_key": True,
        "multiTenant": True, "queue_enabled": True, "health_endpoint": "/health",
        "install_count": 2900, "rating": 4.3, "is_beta": False, "price_tier": "free",
    },
    {
        "id": "amazon_seller",
        "name": "Amazon Seller Central",
        "version": "1.4.0",
        "category": "ecommerce",
        "description": "Amazon Seller Central integration via SP-API. Sync FBA orders, inventory, returns, and automate fulfillment and customer messaging.",
        "author": "MailPilot",
        "icon_url": "https://cdn.jsdelivr.net/npm/simple-icons@v9/icons/amazon.svg",
        "status": "inactive",
        "permissions": ["orders.read", "inventory.read", "reports.read", "messaging.send"],
        "events": ["amazon.order.created", "amazon.order.shipped", "amazon.return.requested"],
        "supports_oauth": True, "supports_webhook": False, "supports_api_key": False,
        "multiTenant": True, "queue_enabled": True, "health_endpoint": "/health",
        "install_count": 5400, "rating": 4.4, "is_beta": False, "price_tier": "free",
    },

    # ── Communication ────────────────────────────────────────────────────────
    {
        "id": "outlook",
        "name": "Microsoft Outlook",
        "version": "1.5.0",
        "category": "communication",
        "description": "Microsoft 365 / Outlook integration for email processing, calendar events, and Teams notifications via Microsoft Graph API.",
        "author": "MailPilot",
        "icon_url": "https://cdn.jsdelivr.net/npm/simple-icons@v9/icons/microsoftoutlook.svg",
        "status": "inactive",
        "permissions": ["email.read", "email.send", "calendar.read", "contacts.read"],
        "events": ["outlook.email.received", "outlook.email.sent", "outlook.calendar.created"],
        "supports_oauth": True, "supports_webhook": True, "supports_api_key": False,
        "multiTenant": True, "queue_enabled": True, "health_endpoint": "/health",
        "install_count": 9100, "rating": 4.7, "is_beta": False, "price_tier": "free",
    },
    {
        "id": "teams",
        "name": "Microsoft Teams",
        "version": "1.3.0",
        "category": "communication",
        "description": "Microsoft Teams integration for channel notifications, bot interactions, meeting alerts, and automated team updates.",
        "author": "MailPilot",
        "icon_url": "https://cdn.jsdelivr.net/npm/simple-icons@v9/icons/microsoftteams.svg",
        "status": "inactive",
        "permissions": ["teams.message.send", "teams.channels.read"],
        "events": ["teams.message.sent", "teams.notification.received"],
        "supports_oauth": True, "supports_webhook": True, "supports_api_key": False,
        "multiTenant": True, "queue_enabled": False, "health_endpoint": None,
        "install_count": 6700, "rating": 4.6, "is_beta": False, "price_tier": "free",
    },
    {
        "id": "telegram",
        "name": "Telegram",
        "version": "1.1.0",
        "category": "communication",
        "description": "Telegram Bot API integration for automated notifications, alerts, and interactive customer support through Telegram channels and groups.",
        "author": "MailPilot",
        "icon_url": "https://cdn.jsdelivr.net/npm/simple-icons@v9/icons/telegram.svg",
        "status": "inactive",
        "permissions": ["messages.send", "channels.write", "bot.manage"],
        "events": ["telegram.message.received", "telegram.notification.sent"],
        "supports_oauth": False, "supports_webhook": True, "supports_api_key": True,
        "multiTenant": True, "queue_enabled": False, "health_endpoint": None,
        "install_count": 3200, "rating": 4.4, "is_beta": False, "price_tier": "free",
    },
    {
        "id": "discord",
        "name": "Discord",
        "version": "1.0.0",
        "category": "communication",
        "description": "Discord webhook and bot integration for server notifications, alert routing, and automated team communication workflows.",
        "author": "MailPilot",
        "icon_url": "https://cdn.jsdelivr.net/npm/simple-icons@v9/icons/discord.svg",
        "status": "inactive",
        "permissions": ["messages.send", "channels.read"],
        "events": ["discord.message.sent", "discord.notification.delivered"],
        "supports_oauth": True, "supports_webhook": True, "supports_api_key": True,
        "multiTenant": True, "queue_enabled": False, "health_endpoint": None,
        "install_count": 1800, "rating": 4.2, "is_beta": False, "price_tier": "free",
    },

    # ── Accounting ────────────────────────────────────────────────────────────
    {
        "id": "quickbooks",
        "name": "QuickBooks",
        "version": "1.4.0",
        "category": "accounting",
        "description": "QuickBooks Online integration for invoice sync, payment tracking, expense management, financial reporting, and bank reconciliation.",
        "author": "MailPilot",
        "icon_url": "https://cdn.jsdelivr.net/npm/simple-icons@v9/icons/quickbooks.svg",
        "status": "inactive",
        "permissions": ["invoices.read", "invoices.write", "payments.read", "accounts.read", "expenses.read"],
        "events": ["qbo.invoice.created", "qbo.payment.received", "qbo.expense.submitted"],
        "supports_oauth": True, "supports_webhook": True, "supports_api_key": False,
        "multiTenant": True, "queue_enabled": True, "health_endpoint": "/health",
        "install_count": 5600, "rating": 4.6, "is_beta": False, "price_tier": "free",
    },
    {
        "id": "xero",
        "name": "Xero",
        "version": "1.3.0",
        "category": "accounting",
        "description": "Xero accounting integration for invoicing, bank feeds, payroll, expense claims, and financial reporting automation.",
        "author": "MailPilot",
        "icon_url": "https://cdn.jsdelivr.net/npm/simple-icons@v9/icons/xero.svg",
        "status": "inactive",
        "permissions": ["invoices.read", "invoices.write", "contacts.read", "bank.read"],
        "events": ["xero.invoice.created", "xero.payment.applied", "xero.contact.updated"],
        "supports_oauth": True, "supports_webhook": True, "supports_api_key": False,
        "multiTenant": True, "queue_enabled": True, "health_endpoint": None,
        "install_count": 4100, "rating": 4.5, "is_beta": False, "price_tier": "free",
    },
    {
        "id": "zoho_books",
        "name": "Zoho Books",
        "version": "1.2.0",
        "category": "accounting",
        "description": "Zoho Books accounting integration for invoicing, purchase orders, bank reconciliation, and GST/tax compliance reporting.",
        "author": "MailPilot",
        "icon_url": "https://cdn.jsdelivr.net/npm/simple-icons@v9/icons/zoho.svg",
        "status": "inactive",
        "permissions": ["invoices.read", "invoices.write", "po.read", "contacts.read"],
        "events": ["zohobooks.invoice.sent", "zohobooks.payment.received", "zohobooks.bill.created"],
        "supports_oauth": True, "supports_webhook": True, "supports_api_key": True,
        "multiTenant": True, "queue_enabled": False, "health_endpoint": None,
        "install_count": 2400, "rating": 4.3, "is_beta": False, "price_tier": "free",
    },

    # ── Customer Support ──────────────────────────────────────────────────────
    {
        "id": "zendesk",
        "name": "Zendesk",
        "version": "1.5.0",
        "category": "support",
        "description": "Zendesk customer support integration for ticket sync, SLA monitoring, agent routing, and customer satisfaction workflows.",
        "author": "MailPilot",
        "icon_url": "https://cdn.jsdelivr.net/npm/simple-icons@v9/icons/zendesk.svg",
        "status": "inactive",
        "permissions": ["tickets.read", "tickets.write", "agents.read", "customers.read"],
        "events": ["zendesk.ticket.created", "zendesk.ticket.solved", "zendesk.satisfaction.rated"],
        "supports_oauth": True, "supports_webhook": True, "supports_api_key": True,
        "multiTenant": True, "queue_enabled": True, "health_endpoint": "/health",
        "install_count": 4800, "rating": 4.6, "is_beta": False, "price_tier": "free",
    },
    {
        "id": "freshdesk",
        "name": "Freshdesk",
        "version": "1.4.0",
        "category": "support",
        "description": "Freshdesk helpdesk integration for multi-channel ticket management, SLA enforcement, and AI-powered agent assist.",
        "author": "MailPilot",
        "icon_url": "https://cdn.jsdelivr.net/npm/simple-icons@v9/icons/freshworks.svg",
        "status": "inactive",
        "permissions": ["tickets.read", "tickets.write", "contacts.read", "agents.read"],
        "events": ["freshdesk.ticket.created", "freshdesk.ticket.resolved", "freshdesk.agent.assigned"],
        "supports_oauth": True, "supports_webhook": True, "supports_api_key": True,
        "multiTenant": True, "queue_enabled": False, "health_endpoint": None,
        "install_count": 3200, "rating": 4.4, "is_beta": False, "price_tier": "free",
    },
    {
        "id": "intercom",
        "name": "Intercom",
        "version": "1.2.0",
        "category": "support",
        "description": "Intercom customer messaging integration for live chat, proactive campaigns, product tours, and AI support bot automation.",
        "author": "MailPilot",
        "icon_url": "https://cdn.jsdelivr.net/npm/simple-icons@v9/icons/intercom.svg",
        "status": "inactive",
        "permissions": ["conversations.read", "contacts.read", "messages.send"],
        "events": ["intercom.conversation.created", "intercom.message.replied", "intercom.user.created"],
        "supports_oauth": True, "supports_webhook": True, "supports_api_key": True,
        "multiTenant": True, "queue_enabled": False, "health_endpoint": None,
        "install_count": 2700, "rating": 4.5, "is_beta": False, "price_tier": "free",
    },

    # ── AI & Intelligence ─────────────────────────────────────────────────────
    {
        "id": "anthropic",
        "name": "Anthropic Claude",
        "version": "1.1.0",
        "category": "ai",
        "description": "Anthropic Claude API integration for enterprise AI: document analysis, email drafting, data extraction, decision support, and workflow intelligence.",
        "author": "MailPilot",
        "icon_url": "https://cdn.jsdelivr.net/npm/simple-icons@v9/icons/anthropic.svg",
        "status": "inactive",
        "permissions": ["ai.chat", "ai.analyze", "ai.extract", "ai.classify"],
        "events": ["claude.analysis.completed", "claude.extraction.done"],
        "supports_oauth": False, "supports_webhook": False, "supports_api_key": True,
        "multiTenant": True, "queue_enabled": True, "health_endpoint": None,
        "install_count": 3800, "rating": 4.9, "is_beta": False, "price_tier": "free",
    },
    {
        "id": "google_gemini",
        "name": "Google Gemini",
        "version": "1.0.0",
        "category": "ai",
        "description": "Google Gemini multimodal AI for document understanding, image analysis, structured data extraction, and intelligent automation.",
        "author": "MailPilot",
        "icon_url": "https://cdn.jsdelivr.net/npm/simple-icons@v9/icons/google.svg",
        "status": "inactive",
        "permissions": ["ai.chat", "ai.vision", "ai.extract"],
        "events": ["gemini.task.completed"],
        "supports_oauth": False, "supports_webhook": False, "supports_api_key": True,
        "multiTenant": True, "queue_enabled": True, "health_endpoint": None,
        "install_count": 2100, "rating": 4.7, "is_beta": True, "price_tier": "free",
    },
]

_CATALOG_BY_ID: dict[str, dict[str, Any]] = {c["id"]: c for c in _CATALOG}


def _to_marketplace_model(raw: dict[str, Any], installed_ids: set[str]) -> MarketplaceConnector:
    return MarketplaceConnector(
        **{k: v for k, v in raw.items()},
        is_installed=raw["id"] in installed_ids,
    )


def _get_installed_ids(tenant_id: Optional[str] = None) -> set[str]:
    db = get_panel_db()
    if tenant_id:
        rows = db.fetch_all(
            "SELECT manifest_id FROM connectors WHERE tenant_id = ? AND is_active = 1",
            (tenant_id,),
        )
    else:
        rows = db.fetch_all("SELECT manifest_id FROM connectors WHERE is_active = 1", ())
    return {r["manifest_id"] for r in rows}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/connectors", response_model=list[MarketplaceConnector], summary="List marketplace connectors")
async def list_marketplace_connectors(
    category: Optional[str] = Query(None, description="Filter by category"),
    search: Optional[str] = Query(None, description="Search by name or description"),
    price_tier: Optional[str] = Query(None, description="Filter by price tier: free, pro, enterprise"),
    tenant_id: Optional[str] = Query(None, description="Mark connectors as installed for this tenant"),
):
    installed_ids = _get_installed_ids(tenant_id)
    results = list(_CATALOG)

    if category:
        results = [c for c in results if c["category"] == category]
    if price_tier:
        results = [c for c in results if c["price_tier"] == price_tier]
    if search:
        q = search.lower()
        results = [
            c for c in results
            if q in c["name"].lower() or q in c["description"].lower()
        ]

    return [_to_marketplace_model(c, installed_ids) for c in results]


@router.get("/connectors/{connector_id}", response_model=MarketplaceConnector, summary="Get connector details")
async def get_marketplace_connector(
    connector_id: str,
    tenant_id: Optional[str] = Query(None),
):
    raw = _CATALOG_BY_ID.get(connector_id)
    if not raw:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Connector '{connector_id}' not found in marketplace")
    installed_ids = _get_installed_ids(tenant_id)
    return _to_marketplace_model(raw, installed_ids)


@router.post(
    "/connectors/{connector_id}/install",
    response_model=InstalledConnector,
    status_code=status.HTTP_201_CREATED,
    summary="Install a connector",
)
async def install_connector(connector_id: str, body: ConnectorInstallRequest):
    raw = _CATALOG_BY_ID.get(connector_id)
    if not raw:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Connector '{connector_id}' not found")

    if body.connector_id != connector_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="connector_id in body does not match URL")

    db = get_panel_db()

    # Check for duplicate
    existing = db.fetch_one(
        "SELECT id FROM connectors WHERE tenant_id = ? AND manifest_id = ? AND is_active = 1",
        (body.tenant_id, connector_id),
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Connector '{connector_id}' is already installed for tenant '{body.tenant_id}'",
        )

    record_id = generate_connector_id()
    now = utc_now_str()

    db.execute(
        """
        INSERT INTO connectors
            (id, tenant_id, manifest_id, name, category, status, version,
             config_json, installed_at, last_sync, last_heartbeat,
             failure_count, retry_count, health_score, is_active)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, 0, 0, 1.0, 1)
        """,
        (
            record_id,
            body.tenant_id,
            connector_id,
            raw["name"],
            raw["category"],
            ConnectorStatus.INSTALLING.value,
            raw["version"],
            json.dumps(body.config),
            now,
        ),
    )

    return InstalledConnector(
        connector_id=record_id,
        tenant_id=body.tenant_id,
        name=raw["name"],
        category=ConnectorCategory(raw["category"]),
        status=ConnectorStatus.INSTALLING,
        version=raw["version"],
        installed_at=datetime.fromisoformat(now),
        config=body.config,
        health_score=1.0,
    )


@router.get("/categories", summary="List connector categories")
async def list_categories():
    return CONNECTOR_CATEGORIES


@router.get("/featured", response_model=list[MarketplaceConnector], summary="Get featured connectors")
async def get_featured_connectors(tenant_id: Optional[str] = Query(None)):
    installed_ids = _get_installed_ids(tenant_id)
    featured = [_CATALOG_BY_ID[cid] for cid in FEATURED_CONNECTOR_IDS if cid in _CATALOG_BY_ID]
    return [_to_marketplace_model(c, installed_ids) for c in featured]
