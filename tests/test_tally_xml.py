from backend.services.connectors.tally.xml import (
    build_export_request,
    parse_companies,
    parse_ledgers,
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
