with monthly as (
    select * from {{ ref('monthly_finance') }}
)
select
    original.client_id,
    original.service_month,
    original.paid_cents as original_paid_cents,
    revised.paid_cents as revised_paid_cents,
    revised.paid_cents - original.paid_cents as difference_cents
from monthly as original
join monthly as revised
  on original.client_id = revised.client_id
 and original.service_month = revised.service_month
where original.run_id = 'original' and revised.run_id = 'revised'
