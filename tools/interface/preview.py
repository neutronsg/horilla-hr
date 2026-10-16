"""Isolated synthetic UI benchmark server; never connects to production services."""

import os, sys, time, json
from pathlib import Path

ROOT = Path(os.environ.get("HR_UI_SOURCE_DIR", Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(ROOT))
qa_db = Path(
    os.environ.get("HR_UI_DB", "/private/tmp/hr-interface/qa.sqlite3")
).resolve()
if not qa_db.is_relative_to(Path("/private/tmp/hr-interface")):
    raise ValueError("UI QA databases must stay under /private/tmp/hr-interface")
qa_db.parent.mkdir(parents=True, exist_ok=True)
os.environ.update(
    DJANGO_SETTINGS_MODULE="horilla.settings",
    DEBUG="True",
    SECRET_KEY="interface-local-only",
    DB_NAME=str(qa_db),
    DATABASE_URL=f"sqlite:///{qa_db}",
    ALLOWED_HOSTS="localhost,127.0.0.1",
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
sys.argv = ["manage.py", "shell"]
import django

django.setup()
from django.conf import settings

settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
if os.environ.get("HR_UI_COMPANY_DOCUMENT_FIXTURES") == "1":
    from django.test import override_settings

    document_preview_settings = override_settings(
        MEDIA_ROOT="/private/tmp/hr-interface/company-documents-media",
        COMPANY_SCOPED_PERMISSIONS=True,
    )
    document_preview_settings.enable()
# Use production's compiled-template cache in both baseline and final runs.
settings.TEMPLATES[0]["OPTIONS"]["loaders"] = [
    (
        "django.template.loaders.cached.Loader",
        settings.TEMPLATES[0]["OPTIONS"]["loaders"],
    )
]
from django.core.management import call_command
from horilla.horilla_middlewares import _thread_locals

_thread_locals.request = None
call_command("migrate", verbosity=0, interactive=False)
from horilla.testkit import (
    make_company,
    make_employee,
    make_user,
    clear_selected_company,
)
from base.models import Company, Department
from employee.models import Employee, EmployeeWorkInformation
from leave.models import LeaveType, LeaveRequest, AvailableLeave
from payroll.models.models import Payslip, Reimbursement
from payroll.models.tax_models import PayrollSettings
from datetime import date

clear_selected_company()
company = Company.objects.filter(company="Neutron UI QA").first() or make_company(
    "Neutron UI QA"
)
if not Employee.objects.filter(email="zeyu+ui-admin@neutron.sg").exists():
    admin = make_employee(
        company=company,
        email="zeyu+ui-admin@neutron.sg",
        first_name="Alex",
        last_name="Morgan",
        user=make_user("ui-admin", email="zeyu+ui-admin@neutron.sg", is_superuser=True),
    )
    admin.employee_user_id.is_new_employee = False
    admin.employee_user_id.save()
    from django.test import RequestFactory
    from django.contrib.sessions.backends.db import SessionStore

    request = RequestFactory().get("/")
    request.user = admin.employee_user_id
    request.session = SessionStore()
    request.session["selected_company"] = str(company.pk)
    _thread_locals.request = request
    department = Department.objects.create(department="Product & Engineering")
    department.company_id.add(company)
    kind = LeaveType.objects.create(
        name="Annual leave", total_days=20, require_approval="yes"
    )
    PayrollSettings.objects.get_or_create(currency_symbol="S$")
    for i in range(40):
        employee = make_employee(
            company=company,
            email=f"zeyu+ui-{i}@neutron.sg",
            first_name=["Jamie", "Taylor", "Jordan", "Casey"][i % 4],
            last_name=f"QA {i:02}",
            department=department,
        )
        EmployeeWorkInformation.objects.filter(employee_id=employee).update(
            reporting_manager_id=admin, date_joining=date(2024, 1, 1)
        )
        AvailableLeave.objects.create(
            employee_id=employee, leave_type_id=kind, available_days=20
        )
        LeaveRequest.objects.create(
            employee_id=employee,
            leave_type_id=kind,
            start_date=date(2026, 11, 2),
            end_date=date(2026, 11, 2),
            description="Synthetic UI verification",
        )
        Reimbursement.objects.create(
            employee_id=employee,
            title=f"QA travel claim {i:02}",
            type="reimbursement",
            description="Synthetic taxi receipt",
            allowance_on=date(2026, 10, 14),
            amount=24.5,
            attachment="qa/receipt.pdf",
        )
        data = {
            "basic_pay": 4000,
            "gross_pay": 4000,
            "taxable_gross_pay": 4000,
            "net_pay": 3200,
            "total_deductions": 800,
            "contract_wage": 4000,
            "start_date": "2026-09-01",
            "end_date": "2026-09-30",
            **{
                k: []
                for k in [
                    "allowances",
                    "basic_pay_deductions",
                    "gross_pay_deductions",
                    "pretax_deductions",
                    "post_tax_deductions",
                    "tax_deductions",
                    "net_deductions",
                ]
            },
        }
        Payslip.objects.create(
            employee_id=employee,
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 30),
            status="confirmed",
            pay_head_data=data,
            basic_pay=4000,
            gross_pay=4000,
            deduction=800,
            net_pay=3200,
        )
if os.environ.get("HR_UI_DESIGN_FIXTURES") == "1":
    Employee.objects.filter(
        employee_work_info__company_id=company, email="zeyu+ui-31@neutron.sg"
    ).update(employee_last_name="QA 31 Customer Operations and Service Delivery")
    for slip in Payslip.objects.filter(employee_id__employee_work_info__company_id=company):
        pay_data = dict(slip.pay_head_data)
        deduction = round(slip.gross_pay - slip.net_pay, 2)
        pay_data["total_deductions"] = deduction
        pay_data["net_deductions"] = [
            {"title": "Sample deduction", "amount": deduction, "employer_contribution_amount": 0}
        ]
        Payslip.objects.filter(pk=slip.pk).update(deduction=deduction, pay_head_data=pay_data)

admin = Employee.objects.get(email="zeyu+ui-admin@neutron.sg")
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.auth import SESSION_KEY, BACKEND_SESSION_KEY, HASH_SESSION_KEY

session = SessionStore()
session[SESSION_KEY] = str(admin.employee_user_id_id)
session[BACKEND_SESSION_KEY] = "base.auth_backends.CompanyScopedBackend"
session[HASH_SESSION_KEY] = admin.employee_user_id.get_session_auth_hash()
session["selected_company"] = str(company.pk)
session.save()
# Explicit synthetic role switching for browser checks. Never resolve real users.
qa_sessions = {admin.email: session.session_key}
for actor in Employee.objects.filter(
    employee_work_info__company_id=company, email__startswith="zeyu+ui-"
).select_related("employee_user_id"):
    if actor.email in qa_sessions:
        continue
    actor.employee_user_id.is_new_employee = False
    actor.employee_user_id.save(update_fields=["is_new_employee"])
    actor_session = SessionStore()
    actor_session[SESSION_KEY] = str(actor.employee_user_id_id)
    actor_session[BACKEND_SESSION_KEY] = "base.auth_backends.CompanyScopedBackend"
    actor_session[HASH_SESSION_KEY] = actor.employee_user_id.get_session_auth_hash()
    actor_session["selected_company"] = str(company.pk)
    actor_session.save()
    qa_sessions[actor.email] = actor_session.session_key
document_fixture_id = None
if os.environ.get("HR_UI_COMPANY_DOCUMENT_FIXTURES") == "1":
    from tools.interface.company_documents_fixtures import seed_company_documents

    document_fixture_id = seed_company_documents(company)

from django.core.wsgi import get_wsgi_application
from django.contrib.staticfiles.handlers import StaticFilesHandler
from django.db import connection
from http.cookies import SimpleCookie
from wsgiref.simple_server import make_server, WSGIServer, WSGIRequestHandler
from socketserver import ThreadingMixIn


class Server(ThreadingMixIn, WSGIServer):
    daemon_threads = True


class Quiet(WSGIRequestHandler):
    def log_message(self, *args):
        pass


app = StaticFilesHandler(get_wsgi_application())


def preview(environ, start_response):
    # Optional local design iteration: refresh compiled templates between requests.
    if os.environ.get("HR_UI_TEMPLATE_CACHE") == "off":
        from django.template import engines

        for loader in engines["django"].engine.template_loaders:
            if hasattr(loader, "reset"):
                loader.reset()
    cookies = SimpleCookie(environ.get("HTTP_COOKIE", ""))
    actor_email = environ.get("HTTP_X_HR_UI_ACTOR", admin.email)
    if actor_email not in qa_sessions:
        start_response("403 Forbidden", [("Content-Type", "text/plain")])
        return [b"Only seeded synthetic actors are supported."]
    cookies[settings.SESSION_COOKIE_NAME] = qa_sessions[actor_email]
    environ["HTTP_COOKIE"] = cookies.output(header="", sep=";").strip()
    stats = {"count": 0, "ms": 0}
    start = time.perf_counter()

    def sql(execute, sql, params, many, context):
        t = time.perf_counter()
        try:
            return execute(sql, params, many, context)
        finally:
            stats["count"] += 1
            stats["ms"] += (time.perf_counter() - t) * 1000

    def response(status, headers, exc_info=None):
        elapsed = (time.perf_counter() - start) * 1000
        headers.append(
            (
                "Server-Timing",
                f'app;dur={elapsed:.2f}, sql;dur={stats["ms"]:.2f}, queries;desc="{stats["count"]}"',
            )
        )
        return start_response(status, headers, exc_info)

    with connection.execute_wrapper(sql):
        return app(environ, response)


state = {
    "company": company.pk,
    "employee": Employee.objects.filter(employee_work_info__company_id=company)
    .exclude(pk=admin.pk)
    .first()
    .pk,
    "payslip": Payslip.objects.filter(
        employee_id__employee_work_info__company_id=company
    )
    .first()
    .pk,
}
if document_fixture_id is not None:
    state["document"] = document_fixture_id
Path(os.environ.get("HR_UI_STATE", "/private/tmp/hr-interface/state.json")).write_text(json.dumps(state))
print(f"Synthetic UI QA at http://127.0.0.1:{os.environ.get('HR_UI_PORT', '8765')}", state, flush=True)
make_server(
    "127.0.0.1",
    int(os.environ.get("HR_UI_PORT", "8765")),
    preview,
    server_class=Server,
    handler_class=Quiet,
).serve_forever()
