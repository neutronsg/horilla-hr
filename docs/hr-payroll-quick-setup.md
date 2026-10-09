# HR quick guide: Singapore monthly payroll

## 1. Employment dates and working days

Enter actual employment dates and the full monthly Basic Salary in Payroll → Contract. Select the Payroll Workweek or configure the employee's shift, including half-day schedules. Keep the full contractual salary for a new joiner; Horilla calculates earned pay.

Monthly earned salary = full monthly salary ÷ full month's scheduled working days × payable working days. Scheduled public holidays remain included; non-working/rest days are excluded. Approved unpaid time reduces pay once. Example: S$8,400 monthly salary, Monday–Friday, joining 7 September 2026 → 18/22 × S$8,400 = S$6,872.73.

Historical payroll uses the contract covering the requested period, including expired/terminated contracts. A period covering multiple contracts requires a consolidated calculation and is rejected rather than silently using the current contract. Automatic CPF currently requires one consolidated payslip per employee per calendar month; separate partial-period slips must not each receive the full monthly ceiling.

## 2. Cash allowances and reimbursements

Allowance is a cash allowance, such as a fixed monthly fuel allowance. Under the company's confirmed policy, fixed recurring allowances default to proration for joining, leaving and unpaid time. The Prorate Fixed Monthly Allowance option controls this. Percentage/attendance allowances and dated one-off items are not prorated again.

Select the CPF Wage Classification explicitly: Ordinary Wages (OW), Additional Wages (AW), or genuine expense reimbursement / excluded wages. Taxability is a separate choice. Fixed transport/meal allowances generally attract CPF; repayment of evidenced business expenses does not. Reimbursements do not use the monthly allowance proration or CPF wage base. SDL uses the earned wage snapshot excluding these reimbursements. Review the classification of existing components before using the new payroll calculation; migration defaults cannot identify a reimbursement or bonus from its title.

## 3. Statutory CPF and custom deductions

For Singapore companies, complete Singapore employment details before generating payroll: residency (SC/PR/foreigner), date of birth for SC/PR, and PR effective date for PRs. Singapore employment details or a configured CPF component also activate this validation. Missing residency does not silently exempt a Singapore employee. The calculation reads residency and PR date only, without decrypting identity numbers.

CPF is calculated automatically using the payroll month, age band, PR year, OW/AW classification, wage ceilings, low-wage rules and statutory rounding. Birthday and PR anniversary changes start in the following month. The verified private-sector tables cover 2025, 2026 and 2027. Unsupported years require an updated rate table. CPF starts on the PR effective date; the conversion month's eligible earned wages are recomputed from that date.

Legacy deduction components tagged CPF no longer supply a fixed amount/rate or create a second CPF deduction. A salary structure still controls ordinary recurring deductions, while separately recorded advances, installments and one-off deductions retain their existing treatment. An empty structure does not grant CPF exemption. Self-help-group contributions retain their configured rules; this change does not automate ethnicity/religion eligibility or government submissions.

CPF Exempt and SDL Exempt remain explicit contract options with a required reason/document reference. CPF exemption excludes CPF and linked CDAC/ECF/SINDA components; MBMF has separate rules. For an approved higher PR contribution scheme, select Full Employer / Graduated Employee or Full Employer / Employee, record the CPF Board approval reference, and enter the approved effective month using its first day. Historical months before that date retain graduated rates. Existing payroll/contract permissions control these fields; no new permission is introduced.

## 4. Additional Wages and annual reconciliation

Before paying AW, record the current year's Estimated Annual OW Subject to CPF and CPF Estimate Year. This estimate includes all contracts with the same employer and must be reviewed when wages change. The AW ceiling is S$102,000 less annual OW subject to CPF. All earlier employment months must have reconciled OW/AW snapshots; missing or legacy records produce an actionable validation error.

Each AW calculation checks earlier contributions against the current annual ceiling. December and the final contract month use recorded actual OW. A shortfall is added to the current employee/employer CPF amounts and stored separately in the snapshot; prior paid payslips are not rewritten. Repeating the same calculation does not duplicate the adjustment. Excess contributions require CPF Board refund/reconciliation and are blocked rather than silently creating a negative deduction. A historical wage change affecting later AW payroll also requires reconciliation. External/pre-upgrade ledgers, refunds and company transfers require reviewed correction work; do not invent snapshots to bypass validation.

## 5. Review and payment

Check contractual salary, earned salary, allowance proration, employee CPF, employer CPF and SDL. Employer contributions/SDL do not reduce employee net pay. Confirm gross pay − employee deductions = net pay. Statutory bases and contribution amounts are saved with the payslip; changing configuration does not rewrite old snapshots.

New payroll defaults to the scheduled 6th of the following month, including when the 6th falls on a weekend. Generate payroll before that date as needed. After transferring salary, record the actual payment date and then mark Paid. An existing HR-entered date is preserved. Generation is not a bank transfer or confirmation that salary has been paid. Automatic regeneration refuses paid payslips.

Payroll Configuration controls the automatic generation day independently of the payment date. Automatic generation calculates the previous complete calendar month (for example, 7 October calculates 1–30 September), including staff who joined or left during that month. Repeated runs preserve existing payslips. A staff member with invalid payroll/CPF data is skipped and logged so other staff can still be processed; HR must resolve the error and regenerate that employee's payroll. A day such as 31 falls back to the last day of shorter months.

## 6. Local QA and upgrade scope

The fixes add attendance migration 0008 and payroll migrations 0010–0011, including historical-contract fields. Apply migrations before starting the new application version. Complete missing residency/DOB/PR details and review allowance classifications before running production payroll. Do not automatically recalculate historical confirmed/paid payroll during deployment.

For approved leave affected by the old half-day record failure, preview missing attendance records with `python manage.py repair_leave_work_records --company-id COMPANY_ID` (or repeat `--request-id ID`). Add `--apply` only after reviewing the preview. The command creates missing records and preserves existing attendance, request values and balances. It requires explicit scope and can be repeated safely. It does not recalculate old payslips.

Local QA uses the deployed d53cb9a image's dependencies plus the working-tree source mounted into a separate PostgreSQL environment; these patched results are not tests of the unchanged production image. The local SMTP sink prevents real email delivery. The wider 185-scenario plan still contains unexecuted family-leave, Part IV/overtime, self-help-group, filing and full end-to-end cases. This patch is not a statement that the entire system has passed Singapore compliance acceptance.

See [the leave guide](hr-mom-leave-quick-setup.md) for HR override scope and join-date leave recalculation.

Sources: [MOM incomplete-month salary](https://www.mom.gov.sg/employment-practices/salary/monthly-and-daily-salary), [CPF wages](https://www.cpf.gov.sg/employer/employer-obligations/what-constitutes-wages-for-cpf-contributions), [2025 CPF tables](https://www.cpf.gov.sg/content/dam/web/employer/employer-obligations/documents/CPF_contribution_rates_from_1_Jan_2025.pdf), [2026 CPF tables](https://www.cpf.gov.sg/content/dam/web/employer/employer-obligations/documents/CPFcontributionratesfrom1Jan2026.pdf), [2027 CPF tables](https://www.cpf.gov.sg/content/dam/web/employer/employer-obligations/documents/jan2027cpfcontributionrates.pdf), [AW reconciliation](https://www.cpf.gov.sg/service/article/how-do-i-calculate-cpf-contributions-on-additional-wages-aw-paid-before-the-end-of-the-year-last-month-of-employment), [SDL guidance](https://file.go.gov.sg/sdl-generic-faq.pdf).
