# HR guide: Singapore annual and sick leave in Horilla

Use this guide for full-time employees whose leave is measured in days. Set the application time zone to **Asia/Singapore**.

## Set up the leave type

1. Open **Leave → Leave Types** and create or edit the annual leave type.
2. Set **Limit Leave Days** on. In **Total Days**, enter the yearly allowance from the employment contract, such as **14**. This is the allowance from year one; it is not a balance credited upfront.
3. Set **Automatic Leave Policy** to **Annual leave**. The form saves automatic annual leave as paid leave without a fixed reset.
4. Set **Carryforward Type** according to your policy. For employees covered by Part 4 of the Employment Act, select **Carryforward** and set **Carryforward Max** high enough to preserve all unused statutory days. A max of **14** preserves the full balance for a 14-day type. MOM requires unused statutory leave to remain available for the next 12 months; check the contract for treatment of days above the statutory minimum.
5. Save the leave type, then choose **Assign Leave** on that leave type and select the employees. The displayed balance is calculated from their service dates, so do not enter 14 days manually into each balance.

## Check each employee

- In the employee's **Work Info**, enter the actual **Joining Date**.
- For a fixed-term contract, enter the **Contract End Date** as the final day of employment. Leave it empty for an ongoing contract. Update it if a contract is extended.
- Assign a separate **Unpaid Leave** type if the employee may request unpaid leave. Ensure unpaid leave requests are recorded and approved; approved unpaid days reduce completed service used for annual leave.
- Do not manually adjust an automatic annual leave balance without checking its approved leave history. If converting an existing leave type, review the resulting balances with HR.

## Quick check: 14-day annual leave type

For an employee who joins on **1 January 2025**:

| Date | Expected earned annual leave |
| --- | ---: |
| 30 March 2025 | 0 days |
| 31 March 2025, after three completed months | 4 days |
| 30 April 2025, after four completed months | 5 days |
| 30 June 2025, after six completed months | 7 days |
| 31 December 2025, after twelve completed months | 14 days |

Paid annual leave can be requested from **1 April 2025**. During the first three months, an annual leave absence should be recorded as approved unpaid leave if granted. If the contract ends on **31 March 2025**, the employee has earned **4 days** even though paid annual leave could not be taken during probation. The system calculates the balance; HR must handle [payment for unused leave](https://www.mom.gov.sg/employment-practices/termination-of-employment/termination-with-notice) in the final settlement.

The calculation uses **completed months ÷ 12 × the leave type's yearly days**, rounded to the nearest whole day with half a day rounded up. The joining year starts on the actual joining date; subsequent years start on **1 January**. January rollover carries eligible unused days according to the configured carryforward policy. A service-entitlement safeguard prevents split periods and rounding from reducing contractual/MOM entitlement, including probation spanning January. If the leave type's allowance is below MOM's statutory minimum for a service year, the statutory minimum applies.

**Scope:** This setup is for full-time, day-based annual leave. Part-time employees need MOM's hours-based calculation.

## Set up paid sick leave

1. Create or edit an **Outpatient Sick Leave** type. Set **Automatic Leave Policy** to **Outpatient sick leave** and yearly **Total Days** to the company allowance. MOM's minimum is **14 days** after six months, so a lower figure such as 12 is automatically raised to 14.
2. Create a separate **Hospitalisation Leave** type. Set **Automatic Leave Policy** to **Hospitalisation leave** and yearly **Total Days** to the company allowance, at least **60 days** for the MOM minimum. Assign **both** sick leave types to eligible employees. The 60-day hospitalisation cap includes outpatient sick leave days; outpatient days reduce both remaining balances.
3. Leave **Reset** off and **Carryforward Type** at **No Carryforward** for both. Automatic sick leave uses the calendar year and does not carry unused days forward.
4. Set **Require Attachment** to **Yes** if HR requires an MC upload with the application. HR must check medical certification and the employee's 48-hour notice; the balance calculation does not verify these documents or notice timing.
5. Set **Exclude Holidays** and **Exclude Company Holidays** to **Yes**, and configure the company's non-working days, so sick leave is charged for working days only. For leave crossing 31 December, submit separate requests for each calendar year so each part uses that year's balance.

## Quick check: MOM sick leave minimum

For an employee who joins on **13 February 2023**:

| Date | Outpatient entitlement | Hospitalisation entitlement (including outpatient) |
| --- | ---: | ---: |
| 12 May 2023 | 0 | 0 |
| 13 May 2023 | 5 | 15 |
| 13 June 2023 | 8 | 30 |
| 13 July 2023 | 11 | 45 |
| 13 August 2023 | 14 | 60 |

The balances shown are before approved sick leave is deducted. After six months, the full entitlement resets each **1 January**. During a new hire's first six months, sick leave taken since joining still counts across New Year; the full calendar-year reset begins at six completed months. An employee who has used two outpatient days after six months has **12 outpatient days** and **58 hospitalisation days** remaining.

**Scope:** Automatic sick leave uses day-based allowances for full-time employees. For part-time staff, use MOM's hours-based calculation separately. HR remains responsible for checking each employee's Employment Act coverage and medical eligibility.

Sources: [MOM annual leave](https://www.mom.gov.sg/employment-practices/leave/annual-leave/eligibility-and-entitlement), [MOM sick leave](https://www.mom.gov.sg/employment-practices/leave/sick-leave/eligibility-and-entitlement), [MOM calendar-year rule](https://www.mom.gov.sg/faq/sick-leave/how-is-sick-leave-and-hospitalisation-leave-calculated), [MOM first-six-month cross-year example](https://www.mom.gov.sg/faq/sick-leave/how-do-i-compute-my-sl-entitlement-if-my-1st-6-months-of-employment-spans-across-2-calendar-years), [MOM treatment of unused annual leave](https://www.mom.gov.sg/employment-practices/leave/annual-leave/special-situations), [MOM part-time leave](https://www.mom.gov.sg/employment-practices/part-time-employment/leave).
