# Singapore staff details

Singapore employment details and contribution settings use the existing HR Manager
and Admin roles in the target employee's company, with ordinary employee view/edit
permissions. Viewing requires `employee.view_employee` or `employee.change_employee`;
editing and revealing full identifiers require `employee.change_employee`. No separate
Singapore permissions are required or exposed. Ordinary employees and managers do
not gain access through general employee permissions alone. Roles and permissions
are resolved for the target company, even in the All my companies session.

The employee profile's About section shows masked details and personal email to
these HR users. Opening it records a masked-view audit event and prevents caching.
Migration 0009 removes the obsolete Singapore view/change permission records;
HR/Admin employee role assignments remain unchanged.

NRIC/FIN and work-pass numbers are encrypted using Fernet at rest. The key is
derived with domain separation from Django's stable `SECRET_KEY`. Backups of the
database require that secret to recover identifiers. For key rotation, retain
the previous secret in `SECRET_KEY_FALLBACKS`, resave every details row under the
new key, verify decryption, and retain old keys as long as old backups need them.
Do not rotate/remove keys without this procedure. Database rows must not be
updated with raw SQL plaintext identifiers.

The normal details page masks identifiers; opening the edit/full view is audited.
Change audits record actor, employee, time and field names, never values. Generic
exports and generic model mutation endpoints reject these restricted models.
Private models have no reverse relationship on Employee, so existing employee
serializers, profile forms and relation-based exports do not include them. Do not
register these models for generic audit snapshots or add them to general APIs.

All fields can be empty during onboarding. Identifier validation checks format,
not government verification or work authorisation. Residency and pass type are
separate; LTVP/Dependant's Pass alone does not establish permission to work. Work
pass expiry is separate from employment-contract expiry. PR dates are recorded
but do not alter CPF/payroll calculations automatically.

Preferred names are optional ordinary profile data. The directory displays them
alongside legal names; `get_full_name()` and payroll/contract names remain legal.
Emergency-contact names allow 200 characters. No employee data is bundled in
migrations or source code; imports must be separately authorised and audited.
