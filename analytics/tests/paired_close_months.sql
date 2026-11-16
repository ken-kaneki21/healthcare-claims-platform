select client_id, service_month
from {{ ref('monthly_finance') }}
group by client_id, service_month
having count(*) <> 2
    or count(*) filter (where run_id = 'original') <> 1
    or count(*) filter (where run_id = 'revised') <> 1
    or min(member_months) <> max(member_months)
