# HR quick guide: Singapore monthly payroll

## 1. Employment dates and working days

Enter actual employment dates and the full monthly Basic Salary in Payroll → Contract. Select the Payroll Workweek or configure the employee's shift, including half-day schedules. Keep the full contractual salary for a new joiner; Horilla calculates earned pay.

Monthly earned salary = full monthly salary ÷ full month's scheduled working days × payable working days. Scheduled public holidays remain included; non-working/rest days are excluded. Approved unpaid time reduces pay once. Example: S$8,400 monthly salary, Monday–Friday, joining 7 September 2026 → 18/22 × S$8,400 = S$6,872.73.

Historical payroll uses the contract covering the requested period, including expired/terminated contracts. A period covering multiple contracts requires a consolidated calculation and is rejected rather than silently using the current contract. Automatic CPF currently requires one consolidated payslip per employee per calendar month; separate partial-period slips must not each receive the full monthly ceiling.

## 2. Cash allowances and reimbursements

Allowance is a cash allowance, such as a fixed monthly fuel allowance. Under the company's confirmed policy, fixed recurring allowances default to proration for joining, leaving and unpaid time. The Prorate Fixed Monthly Allowance option controls this. Percentage/attendance allowances and dated one-off items are not prorated again.

Select the CPF Wage Classification explicitly: Ordinary Wages (OW), Additional Wages (AW), or genuine expense reimbursement / excluded wages. Taxability is a separate choice. Fixed transport/meal allowances generally attract CPF; repayment of evidenced business expenses does not. Reimbursements do not use the monthly allowance proration or CPF wage base. SDL uses the earned wage snapshot excluding these reimbursements. Review the classification of existing components before using the new payroll calculation; migration defaults cannot identify a reimbursement or bonus from its title.

Use Payroll → Reimbursement for evidenced expenses incurred for official business, up to the actual expense. When approved, these claims now create an excluded, non-taxable allowance. Record fixed cash allowances and cash employee benefits as allowances with their appropriate wage and tax classifications; calling a payment a reimbursement does not itself exempt it. Bonus/leave encashments continue to be wages. SDL also includes applicable overtime, bonuses and commissions, not only basic salary and fixed allowances.

Previously approved reimbursements retain their existing classifications. Review their linked allowances before correcting them; do not infer treatment from the title alone. Preview and recalculate affected draft payslips only after reviewing the classifications. Confirmed/paid payslips keep their historical snapshots. Example: S$4,000 earned salary plus S$126.47 actual business expenses gives S$4,126.47 before employee deductions, but SDL wages of S$4,000 and indicative SDL of S$10.00. Company SDL remittance is rounded down only after summing all employees' SDL.

## 3. Statutory CPF and custom deductions

For Singapore companies, complete Singapore employment details before generating payroll: residency (SC/PR/foreigner), date of birth for SC/PR, and PR effective date for PRs. Singapore employment details or a configured CPF component also activate this validation. Missing residency does not silently exempt a Singapore employee. The calculation reads residency and PR date only, without decrypting identity numbers.

CPF is calculated automatically using the payroll month, age band, PR year, OW/AW classification, wage ceilings, low-wage rules and statutory rounding. Birthday and PR anniversary changes start in the following month. The verified private-sector tables cover 2025, 2026 and 2027. Unsupported years require an updated rate table. CPF starts on the PR effective date; the conversion month's eligible earned wages are recomputed from that date.

Legacy deduction components tagged CPF no longer supply a fixed amount/rate or create a second CPF deduction. A salary structure still controls ordinary recurring deductions, while separately recorded advances, installments and one-off deductions retain their existing treatment. An empty structure does not grant CPF exemption.

CPF Exempt and SDL Exempt remain explicit contract options with a required reason/document reference. Student CDAC/ECF/SINDA exemption also requires the dated institution evidence in the contribution declaration; MBMF has separate rules. For an approved higher PR contribution scheme, select Full Employer / Graduated Employee or Full Employer / Employee, record the CPF Board approval reference, and enter the approved effective month using its first day. Historical months before that date retain graduated rates. Existing payroll/contract permissions control these fields; no new permission is introduced.

### Self-help group declarations

Open Employee → Singapore employment details → Self-help group contributions. Use the existing company-scoped Singapore details view/change permissions; no additional permission is created. Record the primary race from NRIC (first race for a double-barrelled race) or the employee declaration, whether the employee is Muslim, residency/work-pass status for the salary period and a verification reference. Never infer race or religion from a name. Unknown declarations block new Singapore payroll with an HR validation message.

Automatic treatment calculates CDAC for Chinese SC/PR, ECF for Eurasian SC/PR, SINDA for Indian-descent SC/PR/EP holders, and MBMF for Muslims of all nationalities. An Indian Muslim can owe both SINDA and MBMF. Probation, permanent and fixed-term roles do not themselves exempt an employee; permanent employment is not PR residency. Verified rates cover 2025–2027 and use earned wages including applicable cash allowances, overtime, commissions and bonuses, excluding genuine business expenses. Fund-specific allowance exclusions can be recorded explicitly without altering CPF or SDL. The monthly CPF ceilings do not cap SHG wages.

Keep fund treatment Automatic unless a documented opt-out or adjusted contribution applies. Record the actual effective salary month (first day), application/certificate reference, and approved amount for fixed/voluntary contributions. Voluntary treatment is available for an otherwise inapplicable fund only on recorded employee authorisation. MBMF partial opt-outs use the remaining monthly amount specified by the MUIS certificate; the system does not invent a component split. A full opt-out uses Documented opt-out. Follow each fund's submission/approval procedure outside Horilla.

Every save adds an immutable declaration version. Future-effective changes do not affect earlier months; the latest saved correction for the same month wins on new calculations. No migration infers declarations from old component assignments. Deductions tagged CDAC/ECF/SINDA/MBMF are replaced by the automatic calculation in all deduction channels, including salary structures and compensation updates, to avoid duplicate deductions. Untagged custom deductions remain unchanged: review any untagged legacy fund components before rollout.

Intern status alone does not grant exemption. Record qualifying institution/MUIS evidence and the exemption date range. Student CPF/CDAC/ECF/SINDA treatment must agree with the contract CPF exemption; MBMF student exemption is separate. A change within the pay period requires reviewed transition handling and blocks automatic payroll, rather than guessing a partial-month exemption. Indian EP-to-PR transitions retain whole-month SINDA eligibility; other PR conversions recompute eligible ethnic-fund wages from the PR date. Record the prior month's pass declaration for an Indian PR transition.

Paid/confirmed payslips retain their saved contribution amounts and profile version ID; sensitive race/religion and document references are not copied into payslip payloads. Review and explicitly recalculate affected **drafts** if needed. Editing an employee declaration does not itself alter or notify existing payslips, submit CPF/SHG payments, or create bank transfers.

## 4. Additional Wages and annual reconciliation

Before paying AW, record the current year's Estimated Annual OW Subject to CPF and CPF Estimate Year. This estimate includes all contracts with the same employer and must be reviewed when wages change. The AW ceiling is S$102,000 less annual OW subject to CPF. All earlier employment months must have reconciled OW/AW snapshots; missing or legacy records produce an actionable validation error.

Each AW calculation checks earlier contributions against the current annual ceiling. December and the final contract month use recorded actual OW. A shortfall is added to the current employee/employer CPF amounts and stored separately in the snapshot; prior paid payslips are not rewritten. Repeating the same calculation does not duplicate the adjustment. Excess contributions require CPF Board refund/reconciliation and are blocked rather than silently creating a negative deduction. A historical wage change affecting later AW payroll also requires reconciliation. External/pre-upgrade ledgers, refunds and company transfers require reviewed correction work; do not invent snapshots to bypass validation.

## 5. Review and payment

Check contractual salary, earned salary, allowance proration, employee CPF, employer CPF and SDL. Employer contributions/SDL do not reduce employee net pay. Confirm gross pay − employee deductions = net pay. Statutory bases and contribution amounts are saved with the payslip; changing configuration does not rewrite old snapshots.

New payroll defaults to the scheduled 6th of the following month, including when the 6th falls on a weekend. Generate payroll before that date as needed. After transferring salary, record the actual payment date and then mark Paid. An existing HR-entered date is preserved. Generation is not a bank transfer or confirmation that salary has been paid. Automatic regeneration refuses paid payslips.

Payroll Configuration controls the automatic generation day independently of the payment date. Automatic generation calculates the previous complete calendar month (for example, 7 October calculates 1–30 September), including staff who joined or left during that month. Repeated runs preserve existing payslips. A staff member with invalid payroll/CPF data is skipped and logged so other staff can still be processed; HR must resolve the error and regenerate that employee's payroll. A day such as 31 falls back to the last day of shorter months.

## 6. Local QA and upgrade scope

The fixes add attendance migration 0008 and payroll migrations 0010–0012, plus employee migration 0007 for dated contribution declarations. Apply migrations before starting the new application version. Complete missing residency/DOB/PR details and SHG declarations, review allowance classifications and untagged legacy fund deductions before running production payroll. New Singapore payroll will stop for employees whose declaration is unconfirmed. Do not automatically recalculate historical confirmed/paid payroll during deployment.

For approved leave affected by the old half-day record failure, preview missing attendance records with `python manage.py repair_leave_work_records --company-id COMPANY_ID` (or repeat `--request-id ID`). Add `--apply` only after reviewing the preview. The command creates missing records and preserves existing attendance, request values and balances. It requires explicit scope and can be repeated safely. It does not recalculate old payslips.

Local QA uses the deployed f201879 image's dependencies plus the working-tree source mounted into a separate PostgreSQL environment; these patched results are not tests of the unchanged production image. The local SMTP sink prevents real email delivery. The wider 185-scenario plan still contains unexecuted family-leave, Part IV/overtime, filing and full end-to-end cases. This patch is not a statement that the entire system has passed Singapore compliance acceptance.

See [the leave guide](hr-mom-leave-quick-setup.md) for HR override scope and join-date leave recalculation.

Sources: [MOM incomplete-month salary](https://www.mom.gov.sg/employment-practices/salary/monthly-and-daily-salary), [CPF wages](https://www.cpf.gov.sg/employer/employer-obligations/what-constitutes-wages-for-cpf-contributions), [2025 CPF tables](https://www.cpf.gov.sg/content/dam/web/employer/employer-obligations/documents/CPF_contribution_rates_from_1_Jan_2025.pdf), [2026 CPF tables](https://www.cpf.gov.sg/content/dam/web/employer/employer-obligations/documents/CPFcontributionratesfrom1Jan2026.pdf), [2027 CPF tables](https://www.cpf.gov.sg/content/dam/web/employer/employer-obligations/documents/jan2027cpfcontributionrates.pdf), [AW reconciliation](https://www.cpf.gov.sg/service/article/how-do-i-calculate-cpf-contributions-on-additional-wages-aw-paid-before-the-end-of-the-year-last-month-of-employment), [SDL guidance](https://file.go.gov.sg/sdl-generic-faq.pdf).

SHG sources: [CPF Board eligibility and monthly rate tables](https://www.cpf.gov.sg/employer/employer-obligations/contributions-to-self-help-groups), [declaration / dual-fund rules](https://ask.gov.sg/cpf/questions/cmudavffv00c35o01j17dldcp), [student SHG rules](https://ask.gov.sg/cpf/questions/cm0f52l3g039fpz7ammd5jgc9), [CDAC employer guidance](https://www.cdac.org.sg/cdac-funding-info-information-for-employers), [ECF](https://www.eurasians.sg/ecf-contribution), [SINDA](https://www.sinda.org.sg/donate/sindafundcontribution/), [MUIS employer guidance and certificates](https://www.muis.gov.sg/give-back/mbmf/employer-information/).
