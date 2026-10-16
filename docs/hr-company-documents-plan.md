# Company documents implementation plan

Status: Implemented locally on the feature branch. Requirements and sources checked on 16 October 2026. Production rollout and publication of HR manuals remain separate deployment steps.

Create a central **Company documents** library where HR publishes the insurance manual and other documents for all employees of the company. HR uploads each document once. Current employees and new hires can find the same published edition, with quick access from their personal dashboard.

Extend the existing Policies feature and its attachments, company scope and permissions. The first release covers shared reference material: insurance and benefits guides, handbooks, policies, forms and instructions. Individual insurance records, employee-editor uploads, coverage calculations, claims processing, signatures and read acknowledgements are outside this release.

Work remains isolated on `codex/employee-insurance-documents`, based on `codex/neutron-brand-polish` at `e2ee280ec`, in `/private/tmp/horilla-employee-insurance`. The original checkout remains available for the other session.

## Employee experience

### Company documents library

Add a top-level **Company documents** navigation entry beside Dashboard for employees and HR. Shared company resources do not belong inside the Employees module. It opens a dedicated library rather than the combined Policies and discipline screen. Existing policy links continue to resolve to the same records; disciplinary workflows remain separate.

Use four initial categories: **Insurance and benefits**, **Handbooks and policies**, **Forms and guides**, and **Other**. Employees can search titles and descriptions and filter by category. Show the title, short description, last published update and named attachments with file type and size. Order pinned documents first, then most recently published updates.

An entry can contain several related files, such as the insurance manual, claims instructions and a blank claim form. PDF and image files have explicit **View** and **Download** actions. Office documents have **Download**. Employees always receive the current published files. Use deliberate clicks and keyboard controls for previews.

### Dashboard quick access

Place a compact **Company documents** card near the My HR shortcuts on `/my/`, before the large calendar. Show up to three published entries, pinned entries first, with title, updated date and a **View** action. The View action opens the document entry, with protected previews and downloads for its files. **View all documents** opens the full library.

HR pins the insurance manual so it stays easy to find. The card can also surface a handbook or important form. Use the same Ledger cards, buttons and typography as the existing dashboard, including mobile and dark mode. With no published documents, show “Company documents will appear here when HR publishes them.”

The dashboard and library use the same visibility query and file service. HR changes appear on the next load or refresh. There is no separate dashboard upload or employee-specific copy.

## HR publishing workflow

1. Open **Company documents** and choose **Add document**.
2. Enter a title, category and optional short description. Upload one or more files.
3. Confirm the company audience. The form states **Visible to all current employees of [company], including future hires**. New entries belong to one explicit company in the first release.
4. Choose **Save draft** to keep the entry within authorised HR access, or **Publish** to make it available to employees. Pinning is optional.
5. Use **Edit** or **Replace file** for updates. For a published entry, **Publish changes** applies metadata and file changes together. The current edition stays available until that operation succeeds; a separate saved draft of a published revision is deferred.
6. Use **Unpublish** to return an entry to draft or **Archive** to remove it from the active library. Previous file editions remain available to authorised HR through history.

Require a title, category, explicit company and at least one valid file before publishing a new shared-document entry. Preserve existing attachments and entered form values after validation or upload failures. Saving a draft must never publish it as a side effect.

No employee selection is required. Access follows current company membership and account status, so new hires see the library automatically and employees who lose company access cannot continue requesting its files. The feature communicates the manual; it does not decide insurance eligibility.

## MOM guidance relevant to shared manuals

MOM includes applicable medical benefits, including insurance, among key employment terms. It also allows common terms such as medical benefits to be provided in an employee handbook or company intranet. Sources: [MOM key employment terms](https://www.mom.gov.sg/employment-practices/contract-of-service/key-employment-terms), [MOM contract of service guidance](https://www.mom.gov.sg/employment-practices/contract-of-service/what-is-a-contract-of-service/).

The tripartite guidelines say common terms may be provided through a handbook, website or another platform when employees can easily access and keep a copy; electronic information should be printable. This supports a readily accessible library with downloadable manuals. Source: [Tripartite guidelines, paragraph 7 and footnote 4](https://www.mom.gov.sg/-/media/mom/documents/employment-practices/tripartite-guidelines-on-issuance-of-written-key-employment-terms.pdf).

The product implication is easy access to the current guide and the ability to retain a copy. A shared manual does not itself establish that an employee's employment terms or the employer's underlying insurance arrangements meet every applicable requirement. HR should publish the correct employee-facing guide and keep it current. Insurance procurement and MOM submissions stay in their existing processes.

## Patterns in other HR systems

| System | Documented approach | Application in Neutron |
| --- | --- | --- |
| Zoho People | Organization Files stores common documents, supports sharing with the entire organisation, and can surface marked policy documents from the home area. Employees can view and, when permitted, download them. | One company library, automatic company audience, and dashboard access to important guides. [Zoho Organization Files](https://help.zoho.com/portal/en/kb/people/administrator-guide/files-document-management/articles/organizational-files). |
| Employment Hero | Company Policies supports uploaded files, all-employee sharing, drafts, publishing, replacement versions and archiving. | Explicit publishing and controlled replacement of a shared edition. Acknowledgements and notifications can remain future work. [Employment Hero Singapore company policies](https://help.employmenthero.com/hc/en-sg/articles/17426649963279-Create-and-share-your-organisational-policies). |

These patterns support a shared document library using the existing policy infrastructure. Neither vendor's workflow determines Neutron's insurance obligations.

## Existing implementation and proposed changes

The repository already provides `Policy` and `PolicyMultipleFile` in `employee/models.py`, `PolicyForm` in `employee/forms.py`, policy views in `employee/policies.py` and `employee/cbv/policy_cbv.py`, plus employee-facing policy templates. `Policy` already has a title, body, attachments, visibility flag and company association. Its base model supplies creation time, creator, modifier, an active flag and audit integration points.

Reuse these records rather than introducing insurance models or copying files into employee documents. The proposed additions are:

| Area | First release design |
| --- | --- |
| Document metadata | Add category, dashboard pin and publication/update timestamps. Permit an optional description for new file-based entries; preserve existing policy body content. |
| Publication | Reuse `is_visible_to_all` and `is_active`: draft is active and not employee-visible; published is active and employee-visible; archived is inactive. Enforce transitions centrally and display these states clearly. |
| File metadata | Extend existing attachments with a display name, original filename, verified type, byte size and replacement link. Reuse creator/time fields. Keep replaced files inactive and accessible only to authorised HR. |
| History | Use existing audit facilities for upload, edit, publication, replacement, audience change and archive. Verify registration and attachment-change coverage; add explicit events where existing tracking is insufficient. Do not add read receipts. |
| Views | Add the dedicated library and HR controls, protected view/download endpoints, and the dashboard summary in `base/ess_dashboard.py` and `base/templates/base/ess_dashboard.html`. |

Replacing a file writes a new storage object and atomically changes the published attachment set. It must not overwrite the old bytes. Keep a stable document link when a manual is updated, and show the new published date. Physical deletion and history retention use the organisation's existing retention process; archiving is not deletion.

### Existing policies and migration

Inventory existing policies before rollout, including body-only entries, hidden entries, records with several companies, and records with no company. Carry company-scoped visible policies into the published state without duplicating their files. Hidden entries remain HR-only. Preserve body-only policies as readable articles; the attachment requirement applies to new shared-document uploads.

The company manager currently includes records with no company association. The new library must require an explicit company and must not interpret a blank association as permission to publish everywhere. Resolve legacy unscoped records with HR before rollout rather than automatically assigning an audience. Keep existing URLs compatible while applying the same access checks to them.

Existing records shared across several companies retain those explicit audiences. Changing such a record requires authority in every affected company; otherwise it is read-only for that HR user. New cross-company publishing controls are deferred.

## Access and file handling

| Actor | Published documents | Management and history |
| --- | --- | --- |
| Current employee | Read and download documents for their company | None |
| Reporting manager | Same employee access; reporting lines grant no additional document authority | Only if separately authorised through existing company roles |
| Company HR Manager or Admin | Read within their authorised company scope | Existing Policy view/add/change/delete permissions, resolved for the target company |
| Other-company user or anonymous visitor | No access | No access |
| Superuser | Existing administrator access | Existing administrator access with audit records |

Use the existing Policy permission family, with create and update checked separately. Employee reading does not require an HR management permission. Selecting **All my companies** must not combine one company's management permission with another company's documents. The personal dashboard resolves its employee/company from the logged-in account.

Centralise visibility and authorization for lists, searches, detail pages, attachment lists, file access and every mutation, including older policy routes. Source review identified several areas to address: policy detail does not repeat the list's visibility filter; attachment removal is not constrained to the requested policy's attachment set; some delete operations use GET; templates render raw storage URLs; and create permission also guards updates. Cover these paths as part of the feature, rather than securing only the new screen.

Require POST and CSRF protection for mutations, verify each attachment belongs to its authorised parent, and validate every file in a multiple upload. Reuse configured private storage. Serve files through authenticated application endpoints that recheck publication and company access on every request, including stale links after unpublishing. Stream responses with private cache controls, safe filenames and content disposition.

The browser sees an authenticated application file URL, not an object-storage URL or a temporary bearer link. The deployment configuration defaults to signed storage URLs with a 900-second expiry, but the Company documents endpoint opens the private object server-side. Production uses HTTPS. The local preview uses ordinary filesystem storage and HTTP with synthetic files only. This feature adds no application-level encryption. Repository configuration does not establish whether the OSS bucket has server-side encryption enabled; a read-only metadata check on 16 October 2026 was rejected with `InvalidAccessKeyId`. Encryption at rest therefore remains unverified, and no bucket settings were changed.

Proposed upload defaults are **20 MB per file**, accepting PDF, JPEG, PNG, DOCX, XLSX and PPTX. These are product defaults. Check content, final extension and size; reject empty files, mismatches, HTML, executables and macro-enabled documents. Preview only supported PDFs/images with safe response headers; Office files download as attachments. Validate representative insurer manuals before release.

## Delivery sequence

1. **Policy access and migration:** inventory legacy records, define the shared access helper, correct policy/attachment endpoint checks and plan explicit company mappings.
2. **Metadata and publishing:** add the minimal model/form changes, file validation, atomic replacement and audited state transitions. Preserve existing policy content and URLs.
3. **Company documents screens:** build the employee library and HR draft/publish/archive controls with search, categories, named files and protected previews/downloads.
4. **Dashboard:** add the compact shared-documents card and pin the insurance manual through the same records and permissions.
5. **Verification and rollout:** test the access/lifecycle cases below, review representative manuals with HR, then publish the initial company documents.

## Acceptance checks

- HR uploads one insurance manual once; multiple employees and a newly added employee see the same published file without employee-specific records or copies.
- Employees can find the pinned manual from the dashboard and search/download it from Company documents. Other categories work through the same workflow.
- Drafts, archived entries and replaced editions are absent from employee lists and denied through direct detail/file URLs. Unpublishing blocks subsequent requests from a stale card.
- Another company's employee or HR user cannot read or modify a document by changing IDs. All my companies, mixed role scopes, lost membership and disabled accounts are covered.
- Create, update, publish, replace and archive honour existing company permissions. An attachment ID from another policy cannot be removed or substituted. GET requests never mutate data.
- Invalid files anywhere in a multi-file upload fail validation. A failed replacement leaves the current edition available, and cancelled edits preserve attachments.
- Migration preserves scoped policy audiences, body-only articles and existing links. Unscoped legacy records receive an explicit audience before release. Old policy endpoints cannot bypass the new rules.
- The library, upload form and dashboard card work by keyboard at 390, 1024 and 1440 px in light and dark mode. Category/action popovers remain clickable and do not clip; no horizontal overflow or console errors.

Run focused model, permission, migration and view tests plus the relevant existing policy/dashboard regressions. Run migration-drift and UI build checks when implementation changes their inputs.

## Local use and validation

Apply the included employee migration before running the feature branch. Employees open the top-level **Company documents** link beside Dashboard or the **Company documents** card on **My dashboard**. HR uses **Add document**, selects **Insurance and benefits**, uploads the employee-facing manual, pins it if needed, and chooses **Publish**. Drafts and archived documents are available through the HR status filter. Only administrators can map legacy records that have no company audience; these are held as drafts until assigned explicitly.

The employee and base regression suites passed 196 tests after the navigation refinement. The Company documents suite includes JWT downloads and failed-upload retries. Browser checks cover employees, HR and administrators at 390, 1024 and 1440 px in light and dark mode, keyboard access to filters, sidebar HTMX navigation and the publish/replace/unpublish/archive lifecycle. PDF preview was inspected in Chrome. Migration drift, Django system checks, UI compilation and line-ending checks also passed.

### Navigation and select audit, 16 October 2026

The shared select audit visited all 130 sidebar destinations available across administrator (60), HR (51) and employee (19) roles in both themes: 260 page measurements, plus 20 expanded-filter measurements and five create-dialog measurements. No JavaScript errors were recorded. `tools/interface/choice-audit.cjs` reproduces the audit against the synthetic preview; results and screenshots stay outside the repository.

| Component | Before | After |
| --- | --- | --- |
| Company documents navigation | Inside Employees | Direct link beside Dashboard; personal-dashboard shortcut retained |
| Category and Status | Native operating-system menus | Existing Select2 component, readable labels, keyboard selection and short menus without an unnecessary search field |
| Select2 fields across modules | 13.5/14 px text; modal and multi-select variants | 13.5 px text, 36 px single-select wells, multi-selects grow with their contents |
| Select2 menus | Legacy 4 px corners, opaque light/dark backgrounds and old shadow | 10 px Ledger material, shared elevation, readable selected/hover/search states in both themes |
| Native quick-status/list selects | Operating-system arrow | Shared chevron and input styling; native selection behavior retained |
| Collapsed sidebar to submenu | Width dipped to 93.875 px and labels disappeared crossing the 6 px gap | Rail remains 232 px with labels visible throughout the crossing and a 250 ms pause in the gap |

`tools/interface/navigation-selects.cjs` verifies slow pointer crossings at 768/991/1440 px, keyboard navigation and dismissal, document filters at 390/1440 px in both themes, and option selection inside employee, leave and payroll filter panels. The document browser suite covers 54 layout combinations plus direct HTMX navigation and the complete publish/replace/unpublish/archive flow.

A follow-up check in the live in-app browser reproduced another close path: a focusout event can schedule a new close timer after mouseenter has cancelled the previous one. The timer now checks whether the pointer is still over the flyout or its owning row before hiding it. Recruitment was verified with the pointer over both a middle row and the last row, including focus moving outside the menu; pointer exit still collapses the rail, and keyboard opening/Escape still work. The browser regression harness now covers that focusout sequence for Employees, Recruitment and Reports at all three sidebar widths.

Reproduce the browser checks with the repository's synthetic preview. Set `HR_UI_COMPANY_DOCUMENT_FIXTURES=1`, `HR_UI_DB=/private/tmp/hr-interface/company-documents.sqlite3`, `HR_UI_PORT=8791` and `HR_UI_STATE=/private/tmp/hr-interface/company-documents-state.json` when running `tools/interface/preview.py`. Then run `tools/interface/company-documents.cjs` with Playwright available. The preview uses local synthetic files and an in-memory email backend.
