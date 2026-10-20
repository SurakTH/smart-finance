# Financial insights

`GET /workspaces/{wid}/insights?start=YYYY-MM-DD&end=YYYY-MM-DD` is read-only and uses the existing authenticated workspace membership dependency. Optional `account_id` and `category_id` must belong to that workspace and have the appropriate kind. Results are not sampled from a transaction page. Monetary amounts are integer satang; display rounds averages to satang.

Both date boundaries are inclusive. Windows are limited to 366 calendar days. The immediately preceding window has the same number of days, including zero-spend days. “เดือนนี้” ends today in Bangkok; “เดือนก่อน” uses the complete prior calendar month. A 31-day month is therefore compared to the preceding 31 days, not necessarily the preceding calendar month; the UI prints both dates. This avoids silently mixing a partial month with a complete month.

- Income and expense use active business journals. Opening balances, transfers, card repayments, reversed originals, and reversal journals do not inflate spending or income. Corrected replacements are counted once.
- `average_daily`: expense / all calendar days, rounded to satang. `average_transaction`: expense / expense entry count. Weekday averages divide by occurrences of that weekday, including days without spending.
- Monthly bars include only selected dates, with empty months represented by zero; edge months may be incomplete. Category comparisons include categories which had spending only in the previous window.
- Top five expenses are selected by amount in SQL, then date and ID for deterministic ordering. Rankings, totals and weekday/monthly aggregates cover the whole selected window.
- Net income in this view is a flow, not net worth. Current net worth remains a separate Dashboard/account figure.
- Filters apply to both comparison windows and drilldown links. An expense-category filter naturally excludes income entries. No predictions, inferred merchants, AI-generated totals, or claim of complete data: these are recorded journals only.

No provider calls, credentials, migration, new server environment variables, or ledger writes are involved. Reports deliberately do not cache across users or workspaces. Mobile navigation promotes analysis; Inbox remains available from the services hub and the desktop menu.

Design references: [YNAB spending and income/expense reports](https://www.ynab.com/blog/ynab-reports-and-data), [Actual Budget reports](https://actualbudget.org/docs/reports/). The interface adopts progressive detail and drilldown, without reproducing their UI or requiring budget terminology.

## วันนี้

ปุ่ม **วันนี้** เลือกวันเริ่มและสิ้นสุดเป็นวันเดียวกันตามเขตเวลา `Asia/Bangkok` เปรียบเทียบกับเมื่อวาน (หนึ่งวันเท่ากัน) และยังใช้ตัวกรองบัญชี/หมวดหรือเปิดรายการต้นทางได้ ตัวเลขมาจากฐานข้อมูลโดยไม่เรียก AI
