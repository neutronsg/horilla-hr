# Employee and HR access

Employee information, including Singapore employment details and contribution
settings, must use the existing company-scoped HR Manager/Admin roles and employee
permissions. Do not introduce separate permissions for employee subsections unless
the user explicitly requests a new access policy.

Resolve access against the target employee's company, including when the session
selects "All my companies". Keep ordinary employee and manager access restricted,
and preserve identifier masking, encrypted storage and audit records.

Contribution setup is persistent employee configuration. Ordinary saves must not
require a salary month or a boilerplate reference. Keep dated history internally,
and offer a start month only for intentional backdated or scheduled changes.

HR reminder settings use existing company-scoped HR Manager/Admin roles and
reimbursement approval access. Resolve scheduled recipients from those roles
in the target company rather than maintaining a hardcoded list of people.
Do not introduce separate permissions for HR settings or delivery logs.

# Leave approvals

Normal leave decisions belong to the target employee's active reporting manager.
HR Manager roles receive company-scoped FYI notifications and retain viewing and
employee setup access; HR/global change permissions do not grant normal approval
or self-approval. If HR is also the actual reporting manager, authorize that
manager relationship. Keep web, bulk, API and all templates consistent.

Use the separate administrator intervention entry for exceptions, with a required
reason and an audit record. Reuse existing company Admin roles and permissions;
do not introduce another permission. Missing/inactive/self reporting managers
leave requests pending; assigning an active manager reroutes pending requests.
Preserve existing explicitly configured sequential approval chains and balance
locking. Do not silently enable a second HR approval stage.
