# Validation — 2026-10-28

- `python -m pytest tests -q`: **2 tests passed**, using temporary synthetic
  Parquet fixtures and FastAPI's HTTP test client.
- Verified default/state-filtered distinct-order counts agree with repeated
  line items, seller lookup and missing sellers, sort-key rejection and positive
  pagination limits.
- Python compilation and workflow YAML parsing passed.

These checks cover the portability/API repair. They do not revalidate the
README's historical Olist metrics or DuckDB benchmark, rebuild all source CSVs,
or prove a Redshift deployment. The suite emitted a dependency deprecation
warning from Starlette's HTTP test client; no test failed.
