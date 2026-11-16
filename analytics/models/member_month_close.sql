{{ config(materialized='view') }}

select
    run_id,
    client_id,
    member_id,
    cast(month as date) as service_month,
    paid_cents,
    benchmark_cents
from read_parquet('{{ env_var("CLAIMS_CLOSE_PARQUET") }}')
