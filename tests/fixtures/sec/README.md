# Mocked SEC EDGAR responses

Used by `tests/integration/test_company_search.py` and, through `CREDITLENS_SEC_FIXTURES=tests/fixtures/sec`, by
the browser tests. No automated test calls SEC.

* `company_tickers_exchange.json` — a few rows in SEC's format. Rows marked TEST FIXTURE are invented.
* `companyfacts_0000076605.json.gz` — real SEC XBRL companyfacts of Patrick Industries (CIK 76605), compacted by
  `SECClient.company_facts` (public data; the non-curated issuer of the search tests).
* `companyfacts_0000099901.json.gz` — the same figures under an invented bank CIK with SIC 6022, to test that
  financial-sector filers are never scored by the network.
* `companyfacts_0000099902.json.gz` — an invented IFRS-only filer: no us-gaap statements.
* `submissions_*.json` — identity records written for the tests (name, SIC, tickers); not copies of SEC files.
* CIK 99903 has a submissions record but no companyfacts (SEC answers 404): no XBRL financial data.
