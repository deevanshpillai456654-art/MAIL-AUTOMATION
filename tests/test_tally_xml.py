from backend.services.connectors.tally.xml import (
    build_export_request,
    parse_companies,
    parse_gst_reports,
    parse_ledgers,
    parse_stock_items,
    parse_vouchers,
)


def test_build_export_request_contains_tally_envelope_and_company():
    xml = build_export_request("List of Companies", company="Acme Books")

    assert "<ENVELOPE>" in xml
    assert "<TALLYREQUEST>Export Data</TALLYREQUEST>" in xml
    assert "<REPORTNAME>List of Companies</REPORTNAME>" in xml
    assert "<SVCURRENTCOMPANY>Acme Books</SVCURRENTCOMPANY>" in xml


def test_parse_companies_from_tally_xml():
    xml = """
    <ENVELOPE><BODY><DATA>
      <COMPANY><NAME>Acme Books</NAME><GUID>abc</GUID></COMPANY>
      <COMPANY><NAME>Demo Pvt Ltd</NAME><GUID>def</GUID></COMPANY>
    </DATA></BODY></ENVELOPE>
    """

    assert parse_companies(xml) == [
        {"name": "Acme Books", "guid": "abc"},
        {"name": "Demo Pvt Ltd", "guid": "def"},
    ]


def test_parse_ledgers_and_vouchers_from_tally_xml():
    xml = """
    <ENVELOPE><BODY><DATA>
      <LEDGER><NAME>Sales</NAME><PARENT>Revenue</PARENT><CLOSINGBALANCE>1200</CLOSINGBALANCE></LEDGER>
      <VOUCHER><GUID>v1</GUID><VOUCHERTYPENAME>Sales</VOUCHERTYPENAME><DATE>20260518</DATE><VOUCHERNUMBER>INV-1</VOUCHERNUMBER><AMOUNT>1200</AMOUNT></VOUCHER>
    </DATA></BODY></ENVELOPE>
    """

    assert parse_ledgers(xml)[0]["name"] == "Sales"
    assert parse_ledgers(xml)[0]["closing_balance"] == "1200"
    assert parse_vouchers(xml)[0]["voucher_number"] == "INV-1"
    assert parse_vouchers(xml)[0]["amount"] == "1200"


def test_parse_stock_items_and_gst_reports_from_tally_xml():
    xml = """
    <ENVELOPE><BODY><DATA>
      <STOCKITEM>
        <NAME>USB Cable</NAME>
        <PARENT>Accessories</PARENT>
        <CLOSINGBALANCE>25 Nos</CLOSINGBALANCE>
        <CLOSINGVALUE>12500</CLOSINGVALUE>
        <REORDERBASE>10 Nos</REORDERBASE>
      </STOCKITEM>
      <GSTREPORT>
        <PERIOD>2026-05</PERIOD>
        <MISMATCHCOUNT>3</MISMATCHCOUNT>
        <TAXPAYABLE>4500</TAXPAYABLE>
        <STATUS>review</STATUS>
      </GSTREPORT>
    </DATA></BODY></ENVELOPE>
    """

    stock = parse_stock_items(xml)
    gst = parse_gst_reports(xml)

    assert stock == [
        {
            "name": "USB Cable",
            "parent": "Accessories",
            "closing_balance": "25 Nos",
            "closing_value": "12500",
            "reorder_level": "10 Nos",
        }
    ]
    assert gst == [
        {
            "period": "2026-05",
            "mismatch_count": "3",
            "tax_payable": "4500",
            "status": "review",
        }
    ]
