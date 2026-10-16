# Employee insurance documents implementation plan

Status: Draft for review. Research checked on 16 October 2026. Feature implementation has not started.

Add employee-specific, employer-provided insurance records to the employee editor, with read-only access for the insured employee. The first release should make certificates, insurance cards and coverage information easy to find. Shared company policy administration, insurance claims and privately purchased personal insurance remain outside this release.

The feature branch is `codex/employee-insurance-documents`, created from `codex/neutron-brand-polish` at `e2ee280ec`. Its isolated worktree is `/private/tmp/horilla-employee-insurance`; the original checkout remains available for work on `codex/neutron-brand-polish`.

## Recommended first release

- HR uploads one or more files under **Edit employee → Insurance**.
- Employees get an **Insurance** summary card on their personal dashboard for quick review and access to their e-card or certificate.
- Employees open **My profile → Insurance** to view and download their own files. The Insurance tab should be directly visible beside Documents, using the existing profile extension mechanism.
- A record can contain a certificate, e-card and benefits or claims guide for that employee. HR may attach an employee-safe policy booklet as supporting material.
- Each record shows the insurer, insurance type, policy or membership reference, recorded coverage dates and files. Policy references can be shared across employees; they are not unique employee identifiers.
- Renewals create a new coverage record. Previous coverage remains available as history rather than being overwritten.
- HR can correct metadata, replace an attachment or withdraw a mistaken upload. Employees have read-only access.

A certificate for one employee is suitable for employee access. An insurer's master schedule containing a staff roster, other employees' identifiers or company premiums should remain in the existing HR-controlled policy/document process. HR must supply an employee-specific extract when necessary.

## MOM requirements and product implications

| Area | Current requirement | Implication for this feature |
| --- | --- | --- |
| Work Permit and S Pass medical insurance | Employers generally must maintain inpatient/day-surgery cover of at least S$60,000 annually per holder and bear the premium, subject to MOM's stated exceptions. Policies starting, renewing or extending from 1 July 2025 also have enhanced exclusion, age-band and hospital-payment requirements. | Capture insurance type, insurer, policy reference and coverage dates. A file or recorded coverage limit alone cannot prove that the policy satisfies the applicable terms. Sources: [Work Permit medical insurance](https://www.mom.gov.sg/passes-and-permits/work-permit-for-foreign-worker/sector-specific-rules/medical-insurance), [S Pass medical insurance](https://www.mom.gov.sg/passes-and-permits/s-pass/medical-insurance). |
| Work Permit insurance details | Insurer, policy number, commencement and expiry details must be maintained in MOM's process when issuing/renewing the pass and when details change. | The HR record can help staff prepare those details. Saving in Neutron does not submit them to MOM. Source: [MOM insurance detail submission](https://www.mom.gov.sg/passes-and-permits/work-permit-for-foreign-worker/sector-specific-rules/medical-insurance#submit-insurance-details). |
| Employment Pass medical insurance | Employer-provided medical insurance is optional for EP holders. | Do not label every employee without an uploaded medical policy as non-compliant. Source: [MOM EP medical insurance FAQ](https://www.mom.gov.sg/faq/employment-pass/are-employers-required-to-buy-medical-insurance-for-employment-pass-holders). |
| Work injury compensation insurance | Within WICA's scope, compulsory insurance covers manual employees at every salary and non-manual employees earning S$2,600 or less monthly, excluding the listed variable payments and allowances. This applies to local and foreign employees; approved policies come from designated insurers. | Support WIC as a separate insurance type. Do not derive its applicability solely from nationality or work-pass type. Source: [MOM WIC insurance requirements](https://www.mom.gov.sg/workplace-safety-and-health/work-injury-compensation/work-injury-compensation-insurance). |
| Employment terms | Applicable medical benefits, including insurance, form part of key employment terms. | Employee access should explain their coverage and where to get help; document storage supplements the employment terms. Source: [MOM key employment terms](https://www.mom.gov.sg/employment-practices/contract-of-service/key-employment-terms). |

**Compliance boundary:** the first release is a document and coverage-information feature. It will not certify MOM compliance, interpret policy exclusions, decide claims, calculate payroll deductions or automate MOM submissions. Employer medical-cost obligations and WICA claim eligibility extend beyond whether an insurance file has been uploaded.

MOM's general employment-record retention requirements concern the specified employee and salary records. They should not be treated as a blanket insurance-policy deletion schedule. HR should set insurance retention around applicable claims, legal and business needs, with the organisation's data-protection owner. Personal data must not be retained indefinitely without a purpose. Sources: [MOM employment records](https://www.mom.gov.sg/employment-practices/employment-records), [PDPC retention guidance, section 18](https://www.pdpc.gov.sg/-/media/Files/PDPC/PDF-Files/Advisory-Guidelines/AG-on-Key-Concepts/Advisory-Guidelines-on-Key-Concepts-in-the-PDPA-1-Oct-2021.pdf).

## Patterns in other HR systems

These are documented product patterns; they are not claims about the vendors' Singapore insurance compliance.

| System | Documented approach | Pattern to use in Neutron |
| --- | --- | --- |
| Zoho People | Separates organisation files, sensitive employee files and private personal uploads. Access depends on the file's audience. | Treat employer-issued insurance certificates as employee files, distinct from shared company booklets and employees' private storage. [Zoho Files overview](https://help.zoho.com/portal/en/kb/people/administrator-guide/files-document-management/articles/files-overview). |
| Employment Hero | Employers upload documents from an employee's profile and specify document access, including employee and reporting-line audiences. | Put the upload beside employee details and make the employee audience explicit. Use Neutron's existing HR roles rather than copying the vendor's permission editor. [Employment Hero employee documents](https://help.employmenthero.com/hc/en-au/articles/17426650783375-Upload-documents-to-an-employee-s-file). |
| Personio | Document visibility depends on both employee access and document category. The document hub supports category and recipient filtering. | Check document ownership and company access on every request, including downloads. Keep insurance distinguishable from unrelated employee documents. [Personio Documents Hub](https://support.personio.de/hc/en-us/articles/28583190491293-Overview-of-the-Documents-Hub). |

The common pattern is employee-linked documents with a controlled audience. A full benefits-enrolment or claims-management module is unnecessary for the requested upload-and-view workflow.

## Existing code and the integration choice

The repository already has:

- An employee editor with independently saved sections, rendered through `horilla_theme/templates/employee/update_form/form_view_fragment.html` and `employee/views.py::employee_view_update`.
- Profile extensions through `EmployeeProfileView.add_tab` in `employee/cbv/employee_profile.py`, shared with employee self-service through `UserProfileView`.
- A personal dashboard at `/my/`, backed by `base/ess_dashboard.py` and `base/templates/base/ess_dashboard.html`, with My HR shortcuts and shared Ledger card styling.
- Generic `Document` and `DocumentRequest` models in `horilla_documents/models.py`, including employee ownership, dates and an employee-upload approval workflow.
- Private media storage through `horilla/horilla_backends.py::PrivateMediaStorage`. Deployment configuration in `neutron-infra` enables private OSS storage and expiring signed URLs.
- A company-specific HR/Admin access pattern in `employee/singapore.py`, encrypted HR text fields, and restricted-model/audit patterns in `employee/singapore_models.py`.

**Recommended integration:** use small insurance-specific models and views, while reusing the existing employee editor, profile tabs, private storage and company-role helpers. The generic document workflow includes employee uploads and approval states; its `can_access_document` helper also admits reporting managers. Direct reuse would require changing those semantics and could unintentionally expose insurance files or affect existing document requests.

An independent Insurance tab also avoids changing the existing Documents tab's permissions. The dashboard card, read tab and editor must use the same records, date calculations and protected file service; there must be no second copy of an employee's insurance data.

## User journeys

### HR manages an employee record

1. Open Edit employee and select Insurance. Only authorised company HR/Admin users see the management controls.
2. Select Add insurance, enter a title and insurance type, and upload the employee's files. Show the employee's name and company beside the form so the recipient is clear.
3. Enter insurer and available policy/member details and dates. Save independently of personal, bank and Singapore employment forms.
4. The saved record becomes visible to that employee immediately. Show this consequence next to Save; there is no signature or approval stage.
5. Use Add renewal for the next coverage period. Use Replace file for a correction, preserving an audit record and previous version for authorised HR review.

Upload failures must preserve entered metadata and existing attachments. Cancelling an upload or saving another editor section must not remove existing insurance files.

### The employee reads their insurance

Start with the Insurance card on the personal dashboard, or open My profile → Insurance for the full record. The profile tab shows current or upcoming recorded coverage first and previous coverage below. Each entry shows the insurer, recorded dates, policy/member reference and named files with View and Download actions. The employee has no upload, edit, replace or delete controls.

Use **Within recorded dates**, **Upcoming**, **Expired** and **Dates not provided** to describe the entered dates. These labels do not promise that the insurer has accepted a claim or verified coverage. The empty state should say that HR has not added insurance documents and direct the employee to HR.

### Dashboard quick review

Place a compact Insurance card below the My HR shortcut area and before the large calendar and charts, so employees can reach their documents without scrolling through reports. Use the existing Ledger card and button styles. On mobile, keep the same reading order.

The card should show:

- Insurance title/type, insurer and the recorded coverage dates. Keep full policy/member references in the profile tab.
- A quiet date-based status, including **Expiring soon** when the recorded end date is within 30 days. This threshold is a proposed product default; it does not schedule notifications or claim that a policy meets MOM requirements.
- **View e-card** or **View certificate** when HR has identified that file type, plus **All insurance** leading to the full profile tab. Use an explicit file-purpose field rather than guessing from filenames.

Show up to two current or upcoming records, prioritising medical coverage, with an additional-record count when needed. Records with missing dates are also eligible for the summary and remain labelled as missing. If every recorded period has ended and there are no undated records, show the most recent expired period with a clear label. When there are no available files, use a neutral message that HR has not added insurance documents; absence of an upload must not be presented as proof that the employee is uninsured.

The personal dashboard always resolves the employee from the logged-in account, including for HR/Admin users viewing their own dashboard. Its summary is independent of report-month filters and uses the same date and permission rules as the full Insurance tab. HR changes appear on the next dashboard load or refresh. Withdrawal must block direct file access immediately, even if an already-open card has not refreshed.

## Data and access design

### Proposed records

| Record | Contents |
| --- | --- |
| `EmployeeInsurance` | Employee, issuing company, title, type (medical, WIC, personal accident or other), insurer, optional encrypted policy/member references, optional start/end dates, optional annual limit and currency, employee-safe instructions and claims contact, creator/updater and revision timestamp. |
| `EmployeeInsuranceFile` | Insurance record, private storage key, display title, purpose (e-card, certificate, benefits/claims guide or other), original filename, verified type, size, checksum, version/replacement relationship, uploader and upload time. A record supports multiple files. |
| `EmployeeInsuranceAudit` | Actor, action, record/file identifiers, timestamp and changed field names. Record upload, metadata edit, replacement, withdrawal, preview and download without copying identifiers or file contents into logs. |

The required upload fields should be title, insurance type and at least one accepted file. Missing insurer or dates should be clearly marked for HR completion; they should not prevent HR from making an e-card available. Both dates are needed before showing a recorded coverage period. Reject an end date earlier than a start date. Allow multiple policies and legitimate overlapping periods.

Bind employee and company on the server from the employee being edited. Preserve the issuing company on the insurance record; do not silently reassign historic policies when an employee transfers. Current-company HR access must not automatically reveal another company's historical records. Cover transfer and historical-record access explicitly in tests before enabling it.

Use the restricted-model pattern to keep insurance data out of generic exports, dynamic field discovery and generic APIs. Reuse existing employee permissions and company HR/Admin roles; do not create a separate Insurance permission family.

### Access matrix

| Actor | Read and download | Upload or change |
| --- | --- | --- |
| Insured employee | Their own available files, while their account has access | No |
| HR Manager or Admin | Records within their authorised target employee/company scope, with existing employee view/change access | With existing employee change access in that company |
| Reporting manager or colleague | No access merely through reporting-line or directory access | No |
| HR in another company | No | No |
| Superuser | Existing administrator access, with audit records | Existing administrator access, with audit records |

Resolve company permissions for the target employee and record, including when the session selects All my companies. Hide controls for convenience, but enforce the same checks on lists, metadata, uploads, previews, downloads, replacements and withdrawals.

### Files and lifecycle

Reuse the configured private storage with opaque object names. Serve files through authenticated, authorised application endpoints, so the UI does not publish storage keys or long-lived bearer URLs. Stream downloads instead of reading an entire file into memory. Use private/no-store responses and safe content disposition; recheck access on every request.

Proposed initial upload defaults are PDF, JPEG and PNG, up to 10 MB per file. These are product defaults, not MOM requirements. Validate actual content and final extension as well as size, and reject mismatches, empty files and active document formats. Confirm the examples HR receives fit these defaults before release.

Renewal and expiry do not delete evidence. Replacing a mistaken file removes the replaced version from employee access while preserving the authorised HR audit trail. Withdrawing a wrong-recipient record blocks subsequent employee previews/downloads immediately. Physical retention and deletion must follow the agreed retention schedule and any legal hold. Reuse encrypted reference fields and verify the storage deployment's encryption-at-rest configuration before production use.

## Implementation sequence

1. **Models and access service:** add the three restricted records, additive migrations, validation and company/owner access helpers. Add permission and transfer-boundary tests before exposing routes.
2. **Upload and protected file delivery:** implement private storage handling, preview/download streaming, replacement and withdrawal, failure cleanup and audit records. Keep storage failures from leaving visible records without files.
3. **HR and employee interfaces:** add the Insurance editor section, personal-dashboard summary and read tab using the current Django/HTMX and Ledger components. Preserve section state and validation feedback. Register Insurance in the primary profile-tab labels so it is easy to find, and verify that More still aligns correctly.
4. **Acceptance and rollout:** exercise synthetic policies across admin, HR and employee roles; review the flow with HR; then deploy code and migrations through the existing release process when authorised. No existing generic documents will be reclassified automatically.

Likely change locations are `employee/insurance_models.py`, `employee/insurance.py`, `employee/urls.py`, `base/ess_dashboard.py`, the personal-dashboard template/card include, employee editor/profile integration files, new insurance templates, restricted-model registration and focused tests. The final file split should follow the repository's existing conventions during implementation.

## Acceptance checks

- HR can upload multiple valid files in Edit employee and the insured employee can immediately preview and download them from their own profile.
- The personal-dashboard card displays the employee's own summary and opens the correct protected e-card/certificate or full Insurance tab. Verify multiple policies, no files, missing dates, expiry and the 30-day boundary. Report filters and HR/Admin roles must not substitute another employee's summary.
- Employees cannot access another employee's metadata or bytes by changing IDs or guessing endpoints. Logged-out and cross-company requests fail, including under All my companies.
- Reporting-manager permissions and general employee-directory access do not grant insurance access. Generic document approvals and existing Documents tab access behave as before.
- Renewals preserve historical coverage. Replacement and withdrawal enforce their access changes on direct endpoints, and retained versions remain restricted.
- Invalid files, oversized files, failed storage writes and concurrent updates preserve existing data and return useful form errors. Verify rollback/orphan cleanup with the storage backend mocked.
- Date labels handle missing dates, future periods, expiry boundaries and overlapping coverage without claiming MOM compliance.
- Restricted data is excluded from generic APIs, exports, logs and shared caches; audit entries identify permitted actions without recording file contents or raw references.
- At 390, 1024 and 1440 px, in light and dark modes, the dashboard card, editor, read tab, preview, long filenames and More menu remain usable by pointer and keyboard. Check both employee profile routes.
- Run the relevant Django permission/storage/view tests, the existing employee-document regressions, UI workflow checks and `npm run build:ui`. Check migration drift and per-file line endings before committing implementation.

## Items for HR to settle during implementation

Use representative, redacted certificate/e-card examples to confirm file formats and labels. Confirm who maintains renewals, whether employees need dependent certificates within their own records, and the retention period for expired or withdrawn files. Company-wide document distribution, insurer integrations, claims processing, acknowledgements and renewal reminders can be considered after this employee upload-and-view flow is working.
