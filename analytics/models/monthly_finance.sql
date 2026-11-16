{{ config(
    materialized='incremental',
    unique_key=['run_id', 'client_id', 'service_month'],
    pre_hook="{% if is_incremental() %}delete from {{ this }} as existing where not exists (
        select 1 from {{ ref('member_month_close') }} as source
        where source.run_id = existing.run_id and source.client_id = existing.client_id
            and source.service_month = existing.service_month
    ){% endif %}"
) }}

with recalculated as (
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
group by run_id, client_id, service_month
)
select recalculated.*
from recalculated
{% if is_incremental() %}
left join {{ this }} as existing using (run_id, client_id, service_month)
where existing.member_months is distinct from recalculated.member_months
   or existing.paid_cents is distinct from recalculated.paid_cents
   or existing.benchmark_cents is distinct from recalculated.benchmark_cents
   or existing.missing_benchmark_rows is distinct from recalculated.missing_benchmark_rows
{% endif %}
