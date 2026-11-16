select run_id, client_id, service_month
from {{ ref('monthly_finance') }}
where (missing_benchmark_rows > 0 and expense_to_benchmark is not null)
   or paid_cents < 0
   or member_months <= 0
