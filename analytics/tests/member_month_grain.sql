select run_id, client_id, member_id, service_month
from {{ ref('member_month_close') }}
group by 1, 2, 3, 4
having count(*) <> 1
    or run_id is null or client_id is null or member_id is null or service_month is null
