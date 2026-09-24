# Singapore staff details

The employee profile's About section shows masked Singapore employment details
and personal email for users with `employee.view_singaporeemployeedetails`.
Opening the About section records a masked-view audit event and prevents caching.
Editing or revealing complete identifiers also requires
`employee.change_singaporeemployeedetails`. Both are
explicit permissions: ordinary employee/profile/payroll permissions do not grant
access. Non-superusers must also have access to the employee's company through
their own work information or a company group assignment. No existing groups
receive these permissions automatically.

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
