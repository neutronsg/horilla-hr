from datetime import date, timedelta
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import patch
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.forms.models import model_to_dict
from django.test import TestCase, RequestFactory, override_settings
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.messages.storage.fallback import FallbackStorage
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.template.loader import render_to_string
from base.models import CompanyGroupAssignment
from horilla.horilla_middlewares import _thread_locals, set_selected_company
from horilla.testkit import make_company, make_employee, clear_selected_company
from employee.forms import EmployeeWorkInformationUpdateForm
from employee.models import EmployeeWorkInformation
from employee.probation import annual_leave_eligible_on, can_manage_probation
from recruitment.models import Candidate
from leave.models import LeaveType, AvailableLeave, LeaveRequest

TODAY = date(2026, 10, 14)


@override_settings(COMPANY_SCOPED_PERMISSIONS=True)
class EmployeeProbationTests(TestCase):
    def setUp(self):
        _thread_locals.request = None
        clear_selected_company()
        self.company = make_company("Probation QA")
        self.other = make_company("Other probation QA")
        self.employee, self.hr, self.manager = [
            make_employee(company=self.company, email=f"zeyu+prob-{n}@neutron.sg")
            for n in ["staff", "hr", "manager"]
        ]
        self.work = self.employee.employee_work_info
        self.work.date_joining = date(2026, 8, 14)
        self.work.reporting_manager_id = self.manager
        self.work.save()
        group, _ = Group.objects.get_or_create(name="HR Manager")
        group.permissions.set(
            Permission.objects.filter(
                codename__in=[
                    "change_employee",
                    "view_employee",
                    "change_employeeworkinformation",
                    "change_stage",
                    "add_leaverequest",
                ]
            )
        )
        CompanyGroupAssignment.objects.create(
            user=self.hr.employee_user_id, company=self.company, group=group
        )
        self.patcher = patch(
            "employee.probation.timezone.localdate", return_value=TODAY
        )
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.addCleanup(setattr, _thread_locals, "request", None)
        self.addCleanup(clear_selected_company)

    def request(self, person=None, data=None):
        person = person or self.hr
        r = RequestFactory().post(
            "/", data or {}, secure=True, HTTP_HOST="hr.neutron.sg"
        )
        r.user = person.employee_user_id
        r.session = SessionStore()
        r.session["selected_company"] = "all"
        r.session.save()
        r._messages = FallbackStorage(r)
        _thread_locals.request = r
        set_selected_company("all")
        return r

    def data(self, **changes):
        data = model_to_dict(self.work)
        data.update(changes)
        return {
            key: (
                ""
                if value is None
                else value.isoformat() if hasattr(value, "isoformat") else value
            )
            for key, value in data.items()
        }

    def confirm(self):
        self.request()
        self.work.probation_status = "passed"
        self.work.probation_passed_on = TODAY
        self.work.save()
        self.employee._state.fields_cache.pop("employee_work_info", None)

    def test_hr_form_confirms_with_existing_permission_and_audit(self):
        self.request()
        form = EmployeeWorkInformationUpdateForm(
            self.data(probation_status="passed", probation_passed_on=TODAY),
            instance=self.work,
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.work.refresh_from_db()
        self.assertEqual(self.work.probation_updated_by_id, self.hr.employee_user_id_id)
        self.assertIsNotNone(self.work.probation_updated_at)
        history = self.work.history.first()
        self.assertEqual(history.probation_status, "passed")
        self.assertEqual(history.history_user_id, self.hr.employee_user_id_id)
        self.assertEqual(self.work.annual_leave_eligible_on, TODAY)

    def test_employee_and_reporting_manager_cannot_confirm(self):
        for actor in [self.employee, self.manager]:
            self.request(actor)
            form = EmployeeWorkInformationUpdateForm(
                self.data(probation_status="passed", probation_passed_on=TODAY),
                instance=self.work,
            )
            self.assertFalse(form.is_valid())
            self.work.probation_status = "passed"
            self.work.probation_passed_on = TODAY
            with self.assertRaises(PermissionDenied):
                self.work.save()
            self.work.refresh_from_db()
            self.assertEqual(self.work.probation_status, "not_recorded")

    def test_other_company_hr_and_view_only_hr_cannot_confirm(self):
        self.assertFalse(can_manage_probation(self.hr.employee_user_id, self.other.pk))
        group = Group.objects.get(name="HR Manager")
        group.permissions.set(Permission.objects.filter(codename="view_employee"))
        self.assertFalse(
            can_manage_probation(self.hr.employee_user_id, self.company.pk)
        )

    def test_confirmation_date_is_required_and_must_be_actual(self):
        self.request()
        for date_value in [
            None,
            TODAY + timedelta(days=1),
            self.work.date_joining - timedelta(days=1),
        ]:
            self.work.probation_status = "passed"
            self.work.probation_passed_on = date_value
            with self.assertRaises(ValidationError):
                self.work.save()
        self.work.refresh_from_db()
        self.assertEqual(self.work.probation_status, "not_recorded")

    def test_expected_end_and_extension_do_not_advance_or_delay_standard_gate(self):
        self.request()
        self.work.probation_status = "on_probation"
        self.work.probation_end = TODAY
        self.work.save()
        self.assertEqual(self.work.annual_leave_eligible_on, date(2026, 11, 14))
        self.work.probation_end = date(2027, 2, 14)
        self.work.save()
        self.assertEqual(self.work.annual_leave_eligible_on, date(2026, 11, 14))

    def test_waiver_opens_from_joining_and_reset_removes_early_access(self):
        self.request()
        self.work.probation_status = "not_required"
        self.work.save()
        self.assertEqual(self.work.annual_leave_eligible_on, self.work.date_joining)
        self.confirm()
        self.work.probation_status = "on_probation"
        self.work.probation_passed_on = None
        self.work.save()
        self.assertEqual(self.work.annual_leave_eligible_on, date(2026, 11, 14))

    def test_legacy_work_post_keeps_probation_state(self):
        self.confirm()
        self.request()
        data = self.data(location="New QA location")
        for field in ["probation_status", "probation_end", "probation_passed_on"]:
            data.pop(field)
        form = EmployeeWorkInformationUpdateForm(data, instance=self.work)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.work.refresh_from_db()
        self.assertEqual(
            (self.work.probation_status, self.work.probation_passed_on),
            ("passed", TODAY),
        )

    def test_api_requires_company_hr_and_validates_dates(self):
        from horilla_api.api_serializers.employee.serializers import (
            EmployeeWorkInformationSerializer,
        )

        for actor, expected in [
            (self.employee, False),
            (self.manager, False),
            (self.hr, True),
        ]:
            r = self.request(actor)
            serializer = EmployeeWorkInformationSerializer(
                self.work,
                data={
                    "probation_status": "passed",
                    "probation_passed_on": TODAY.isoformat(),
                },
                partial=True,
                context={"request": r},
            )
            self.assertEqual(serializer.is_valid(), expected, serializer.errors)
        _thread_locals.request = (
            None  # token-auth API actor must come from serializer context
        )
        serializer.save()
        self.work.refresh_from_db()
        self.assertEqual(self.work.probation_status, "passed")
        self.assertEqual(self.work.probation_updated_by_id, self.hr.employee_user_id_id)
        self.assertEqual(
            self.work.history.first().history_user_id, self.hr.employee_user_id_id
        )

    def test_early_confirmation_only_opens_annual_leave_not_sick_leave(self):
        self.confirm()
        for policy, allowed in [
            ("annual", True),
            ("outpatient_sick", False),
            ("hospitalisation", False),
        ]:
            kind = LeaveType.objects.create(
                name=f"Probation {policy}", total_days=14, auto_leave_policy=policy
            )
            AvailableLeave.objects.create(employee_id=self.employee, leave_type_id=kind)
            self.request(self.employee)
            item = LeaveRequest(
                employee_id=self.employee,
                leave_type_id=kind,
                start_date=TODAY,
                end_date=TODAY,
                description="Synthetic QA",
            )
            if allowed:
                item.clean()
            else:
                with self.assertRaisesMessage(ValidationError, "three months"):
                    item.clean()
        balance = AvailableLeave.objects.get(
            employee_id=self.employee, leave_type_id__auto_leave_policy="annual"
        )
        self.assertEqual(balance.available_days, 0)  # no automatic full-year grant

    def candidate(self, **changes):
        values = {
            "name": "Synthetic Candidate QA",
            "email": "zeyu+prob-candidate@neutron.sg",
            "joining_date": self.work.date_joining,
            "probation_end": TODAY,
        }
        values.update(changes)
        obj = Candidate(**values)
        Candidate._base_manager.bulk_create([obj])
        return obj

    def test_conversion_copies_plan_once_and_onboarding_reads_employee_master(self):
        from employee.probation import copy_candidate_plan

        self.request()
        c = self.candidate(converted_employee_id=self.employee)
        copy_candidate_plan(c)
        self.work.refresh_from_db()
        self.assertEqual(
            (self.work.probation_status, self.work.probation_end),
            ("on_probation", TODAY),
        )
        self.assertIsNone(self.work.probation_passed_on)
        self.work.probation_end = TODAY + timedelta(days=30)
        self.work.save()
        copy_candidate_plan(c)
        c.refresh_from_db()
        self.assertEqual(c.effective_probation_end(), self.work.probation_end)
        from recruitment.filters import CandidateFilter

        self.assertTrue(
            CandidateFilter(
                {"probation_end_from": self.work.probation_end.isoformat()},
                queryset=Candidate._base_manager.filter(pk=c.pk),
            ).qs.exists()
        )
        self.assertFalse(
            CandidateFilter(
                {"probation_end": TODAY.isoformat()},
                queryset=Candidate._base_manager.filter(pk=c.pk),
            ).qs.exists()
        )

    def test_converted_candidate_endpoint_does_not_write_another_copy(self):
        import inspect
        from onboarding.views import update_probation_end

        c = self.candidate(converted_employee_id=self.employee)
        r = self.request(data={"candidate_id": c.pk, "probation_end": "2026-12-01"})
        response = inspect.unwrap(update_probation_end)(r)
        self.assertEqual(response.status_code, 409)
        c.refresh_from_db()
        self.assertEqual(c.probation_end, TODAY)

    def test_migration_keeps_plan_unconfirmed_and_is_idempotent(self):
        c = self.candidate(converted_employee_id=self.employee)
        migration = import_module("employee.migrations.0014_move_probation_plans")
        apps = (
            MigrationExecutor(connection)
            .loader.project_state([("employee", "0014_move_probation_plans")])
            .apps
        )
        editor = SimpleNamespace(connection=connection)
        migration.move_plans(apps, editor)
        migration.move_plans(apps, editor)
        self.work.refresh_from_db()
        self.assertEqual(
            (
                self.work.probation_status,
                self.work.probation_end,
                self.work.probation_passed_on,
            ),
            ("on_probation", TODAY, None),
        )
        self.assertEqual(
            self.work.history.filter(
                history_change_reason__startswith="Moved planned"
            ).count(),
            1,
        )

    def test_migration_retains_invalid_and_conflicting_plans(self):
        self.candidate(
            converted_employee_id=self.employee,
            probation_end=self.work.date_joining - timedelta(days=1),
        )
        migration = import_module("employee.migrations.0014_move_probation_plans")
        apps = (
            MigrationExecutor(connection)
            .loader.project_state([("employee", "0014_move_probation_plans")])
            .apps
        )
        editor = SimpleNamespace(connection=connection)
        migration.move_plans(apps, editor)
        self.work.refresh_from_db()
        self.assertIsNone(self.work.probation_end)
        self.candidate(converted_employee_id=self.employee, probation_end=TODAY)
        migration.move_plans(apps, editor)
        self.work.refresh_from_db()
        self.assertEqual(self.work.probation_status, "not_recorded")
        self.assertEqual(
            Candidate._base_manager.filter(converted_employee_id=self.employee).count(),
            2,
        )

    def test_probation_extension_cannot_block_annual_leave_after_three_months(self):
        self.request()
        self.work.date_joining = date(2026, 7, 14)
        self.work.probation_status = "on_probation"
        self.work.probation_end = date(2027, 1, 1)
        self.work.save()
        kind = LeaveType.objects.create(
            name="Extended probation AL", total_days=14, auto_leave_policy="annual"
        )
        AvailableLeave.objects.create(employee_id=self.employee, leave_type_id=kind)
        self.request(self.employee)
        LeaveRequest(
            employee_id=self.employee,
            leave_type_id=kind,
            start_date=TODAY,
            end_date=TODAY,
            description="QA",
        ).clean()

    def test_confirmation_does_not_allow_leave_before_confirmed_date(self):
        self.confirm()
        kind = LeaveType.objects.create(
            name="Confirmed AL", total_days=14, auto_leave_policy="annual"
        )
        AvailableLeave.objects.create(employee_id=self.employee, leave_type_id=kind)
        self.request(self.employee)
        with self.assertRaisesMessage(ValidationError, "three months"):
            LeaveRequest(
                employee_id=self.employee,
                leave_type_id=kind,
                start_date=TODAY - timedelta(days=1),
                end_date=TODAY - timedelta(days=1),
                description="QA",
            ).clean()

    def test_linked_onboarding_does_not_fall_back_to_stale_candidate_date(self):
        c = self.candidate(converted_employee_id=self.employee)
        self.assertIsNone(c.effective_probation_end())
        r = self.request()
        html = render_to_string(
            "cbv/onboarding_candidates/probation_date.html",
            {"instance": c, "request": r},
        )
        self.assertIn("Manage in Employee", html)
        self.assertNotIn("onchange=", html)

    def test_employee_edit_route_saves_probation_and_renders_work_tab(self):
        from employee.views import employee_view_update

        r = self.request(
            data={
                **self.data(probation_status="passed", probation_passed_on=TODAY),
                "form": "work",
                "container": "true",
            }
        )
        response = employee_view_update(r, self.employee.pk)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Probation & annual leave", response.content)
        self.work.refresh_from_db()
        self.assertEqual(self.work.probation_status, "passed")
        self.assertEqual(self.work.probation_updated_by_id, self.hr.employee_user_id_id)

    def test_onboarding_kanban_filters_use_employee_master(self):
        from onboarding.filters import KanbanCandidateFilter

        c = self.candidate(converted_employee_id=self.employee)
        self.request()
        self.work.probation_end = TODAY + timedelta(days=20)
        self.work.save()
        self.assertTrue(
            KanbanCandidateFilter(
                {"probation_end": self.work.probation_end.isoformat()},
                queryset=Candidate._base_manager.filter(pk=c.pk),
            ).qs.exists()
        )
        self.assertFalse(
            KanbanCandidateFilter(
                {"probation_end": TODAY.isoformat()},
                queryset=Candidate._base_manager.filter(pk=c.pk),
            ).qs.exists()
        )

    def test_ui_keeps_probation_with_work_information(self):
        r = self.request()
        form = EmployeeWorkInformationUpdateForm(instance=self.work)
        html = render_to_string(
            "employee/update_form/probation.html", {"work_form": form, "request": r}
        )
        self.assertIn("Probation & annual leave", html)
        self.assertIn("probation_status", html)
        self.assertIn("Actual confirmation date", html)
