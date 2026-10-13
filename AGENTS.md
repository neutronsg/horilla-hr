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
