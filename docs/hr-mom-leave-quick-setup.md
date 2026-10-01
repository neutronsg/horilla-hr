# HR quick guide: annual and sick leave

For full-time employees whose leave is measured in days. There are **two leave categories**, but sick leave needs **two separate Horilla leave types** because outpatient and hospitalisation have different limits.

## 1. Enter employment dates

In each employee's **Work Info**, enter the actual **Joining Date**. For a fixed-term employee, also enter **Contract End Date**. Update the end date if the contract is extended. The automatic balances use these dates; they are not granted in full when a type is assigned.

## 2. Configure the leave types

Open **Leave → Configuration → Leave Types**. Create or edit the following types, then use **Assign Leave** on each type to assign the relevant employees.

| Leave type | Automatic Leave Policy | Total Days | Reset | Carryforward |
| --- | --- | ---: | --- | --- |
| Annual Leave | Annual leave | Contractual yearly allowance, e.g. 14 | Off | Follow company policy and MOM's statutory rules |
| Medical Leave (MC) | Outpatient sick leave | Company yearly allowance, at least 14 for the MOM minimum | Off | No Carryforward |
| Hospitalisation Leave | Hospitalisation leave | Company yearly allowance, at least 60 for the MOM minimum | Off | No Carryforward |

For **all three**, turn on **Limit Leave Days**, **Exclude Holidays**, and **Exclude Weekly Off Days** (called **Exclude Company Holidays** on some edit screens). Configure the actual rest/off days under **Leave → Configuration → Weekly Off Days**; the exclusion checkbox alone cannot identify them. Set **Require Attachment** on the sick leave types if HR wants an MC uploaded with the application. HR must still check the MC and notice requirements.

**Annual leave:** Enter the allowance from the contract, such as 14 days from year one. Horilla uses completed months of service to prorate that allowance and rounds a half-day up. The joining year runs from joining date to 31 December; subsequent years run from **1 January to 31 December**. Paid annual leave can be requested after three months. Probation does not restart in January. Approved unpaid leave can reduce completed service. Review **Carryforward Max**: employees covered by Part 4 of the Employment Act must be able to carry unused statutory annual leave into the next 12 months.

**Sick leave:** Both outpatient and hospitalisation leave start after three months. Their MOM minimum entitlements at 3, 4, 5, and 6 completed months are **5/8/11/14** outpatient days and **15/30/45/60** hospitalisation days. The 60-day hospitalisation limit **includes** outpatient sick days; for example, using 2 outpatient days leaves 12 outpatient days and 58 days of the shared hospitalisation limit. After six months, sick leave resets by calendar year and does not carry forward. During a new hire's first six months, usage since joining still counts across 1 January.

## 3. Check one employee before assigning everyone

For an employee who joined **1 January** with **14 annual days** and MOM-minimum sick leave:

| Check date | Annual earned | Outpatient sick | Hospitalisation, including outpatient |
| --- | ---: | ---: | ---: |
| 1 April, three completed months | 4 | 5 | 15 |
| 1 July, six completed months | 7 | 14 | 60 |

The displayed **available** balance may be lower if approved leave was already taken. During the first three months, use **Unpaid Leave** for an approved absence. Horilla rejects paid leave requests exceeding the available balance; it does not show a negative advance balance. Split sick leave spanning **31 December** into separate requests for each calendar year.

For calculation details and special cases, see [the full HR guide](hr-mom-annual-leave-setup.md). MOM references: [annual leave](https://www.mom.gov.sg/employment-practices/leave/annual-leave/eligibility-and-entitlement), [sick leave](https://www.mom.gov.sg/employment-practices/leave/sick-leave/eligibility-and-entitlement), [sick leave by calendar year](https://www.mom.gov.sg/faq/sick-leave/how-is-sick-leave-and-hospitalisation-leave-calculated), and [unused annual leave](https://www.mom.gov.sg/employment-practices/leave/annual-leave/special-situations).
