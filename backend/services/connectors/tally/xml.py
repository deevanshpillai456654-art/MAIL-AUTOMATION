from __future__ import annotations

import xml.etree.ElementTree as ET
from html import escape
from typing import Any


def _text(node: ET.Element, *names: str) -> str:
    for name in names:
        found = node.find(f".//{name}")
        if found is not None and found.text:
            return found.text.strip()
    return ""


def build_export_request(report_name: str, company: str | None = None) -> str:
    company_xml = f"<SVCURRENTCOMPANY>{escape(company)}</SVCURRENTCOMPANY>" if company else ""
    return (
        "<ENVELOPE>"
        "<HEADER><VERSION>1</VERSION><TALLYREQUEST>Export Data</TALLYREQUEST><TYPE>Data</TYPE>"
        f"<ID>{escape(report_name)}</ID></HEADER>"
        "<BODY><DESC><STATICVARIABLES>"
        f"<REPORTNAME>{escape(report_name)}</REPORTNAME>{company_xml}"
        "</STATICVARIABLES></DESC></BODY>"
        "</ENVELOPE>"
    )


def _root(raw_xml: str) -> ET.Element:
    return ET.fromstring(raw_xml.encode("utf-8"))


def parse_companies(raw_xml: str) -> list[dict[str, Any]]:
    root = _root(raw_xml)
    rows = []
    for company in root.findall(".//COMPANY"):
        name = _text(company, "NAME")
        if name:
            rows.append({"name": name, "guid": _text(company, "GUID")})
    return rows


def parse_ledgers(raw_xml: str) -> list[dict[str, Any]]:
    root = _root(raw_xml)
    rows = []
    for ledger in root.findall(".//LEDGER"):
        name = _text(ledger, "NAME")
        if name:
            rows.append({
                "name": name,
                "parent": _text(ledger, "PARENT"),
                "closing_balance": _text(ledger, "CLOSINGBALANCE"),
            })
    return rows


def parse_vouchers(raw_xml: str) -> list[dict[str, Any]]:
    root = _root(raw_xml)
    rows = []
    for voucher in root.findall(".//VOUCHER"):
        rows.append({
            "guid": _text(voucher, "GUID"),
            "voucher_type": _text(voucher, "VOUCHERTYPENAME"),
            "date": _text(voucher, "DATE"),
            "voucher_number": _text(voucher, "VOUCHERNUMBER"),
            "amount": _text(voucher, "AMOUNT"),
        })
    return [row for row in rows if any(row.values())]


def parse_stock_items(raw_xml: str) -> list[dict[str, Any]]:
    root = _root(raw_xml)
    rows = []
    for item in root.findall(".//STOCKITEM"):
        name = _text(item, "NAME")
        if name:
            rows.append({
                "name": name,
                "parent": _text(item, "PARENT"),
                "closing_balance": _text(item, "CLOSINGBALANCE"),
                "closing_value": _text(item, "CLOSINGVALUE"),
                "reorder_level": _text(item, "REORDERBASE", "REORDERLEVEL"),
            })
    return rows


def parse_gst_reports(raw_xml: str) -> list[dict[str, Any]]:
    root = _root(raw_xml)
    rows = []
    for report in root.findall(".//GSTREPORT") + root.findall(".//GSTSUMMARY"):
        period = _text(report, "PERIOD", "RETURNPERIOD")
        if period:
            rows.append({
                "period": period,
                "mismatch_count": _text(report, "MISMATCHCOUNT", "MISMATCHES"),
                "tax_payable": _text(report, "TAXPAYABLE", "TAXAMOUNT"),
                "status": _text(report, "STATUS"),
            })
    return rows
