{{ config(materialized='incremental', unique_key=['run_id', 'client_id', 'service_month']) }}

select
    run_id,
    client_id,
    service_month,
    count(*) as member_months,
    sum(paid_cents) as paid_cents,
    sum(benchmark_cents) as benchmark_cents,
    count(*) - count(benchmark_cents) as missing_benchmark_rows,
    sum(paid_cents) / nullif(count(*), 0) as pmpm_cents,
    case
        when count(benchmark_cents) = count(*)
        then sum(paid_cents) / nullif(sum(benchmark_cents), 0)
    end as expense_to_benchmark
from {{ ref('member_month_close') }}
{% if is_incremental() %}
where run_id not in (select distinct run_id from {{ this }})
{% endif %}
group by run_id, client_id, service_month
