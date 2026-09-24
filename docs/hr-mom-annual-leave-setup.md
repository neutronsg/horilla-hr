# HR guide: Singapore annual leave in Horilla

Use this guide for full-time employees whose annual leave is measured in days. Ask your system administrator to enable the updated annual leave feature and set the application time zone to **Asia/Singapore** before using it.

## Set up the leave type

1. Open **Leave → Leave Types** and create or edit the annual leave type.
2. Set **Limit Leave Days** on. In **Total Days**, enter the yearly allowance from the employment contract, such as **14**. This is the allowance from year one; it is not a balance credited upfront.
3. Turn on **Auto Calculate Annual Leave**. Set the payment field to **Paid** and leave **Reset** off. The form saves automatic annual leave as paid leave without a fixed reset.
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

The calculation uses **completed months ÷ 12 × the leave type's yearly days**, rounded to the nearest whole day with half a day rounded up. It uses the employee's service anniversary, not 1 January, for later service years. If the leave type's allowance is below MOM's statutory minimum for a service year, the statutory minimum applies.

**Scope:** This setup is for full-time, day-based annual leave. Part-time employees need MOM's hours-based calculation.

Sources: [MOM annual leave eligibility and entitlement](https://www.mom.gov.sg/employment-practices/leave/annual-leave/eligibility-and-entitlement), [MOM treatment of unused leave](https://www.mom.gov.sg/employment-practices/leave/annual-leave/special-situations), [MOM part-time leave](https://www.mom.gov.sg/employment-practices/part-time-employment/leave).
