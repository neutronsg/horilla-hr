from datetime import date
from unittest.mock import patch

from django.contrib.auth.models import Group, Permission
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings

from base.methods import has_export_access
from base.models import CompanyGroupAssignment
from employee.contributions import ContributionProfileForm, singapore_contributions
from employee.models import Employee
from employee.singapore_models import SingaporeContributionProfile, SingaporeDetailsAudit
from horilla.testkit import make_company, make_employee
from payroll.shg import profile_for


class ContributionPrivacyTests(TestCase):
    def setUp(self):
        self.company=make_company("SHG HR QA")
        self.hr=make_employee(company=self.company,email="shg-hr@test.example")
        self.employee=make_employee(company=self.company,email="shg-staff@test.example")
        self.other=make_employee(company=make_company("Other SHG QA"),email="shg-other@test.example")

    def grant(self,*codenames):
        self.hr.employee_user_id.user_permissions.add(*Permission.objects.filter(codename__in=codenames))
        for attr in ("_perm_cache","_user_perm_cache","_group_perm_cache"):
            self.hr.employee_user_id.__dict__.pop(attr,None)

    def request(self,method="get",data=None,query=""):
        req=getattr(RequestFactory(),method)("/employee/singapore-contributions/1/"+query,data or {})
        req.user=self.hr.employee_user_id;req.session={}
        return req

    def data(self,**kwargs):
        data={"effective_month":"2026-09-01","primary_race":"chinese","muslim_status":"no",
              "residency_status":"citizen","declaration_reference":"HR verified declaration", "revision":""}
        data.update({f"{fund}_mode":"auto" for fund in ("cdac","ecf","sinda","mbmf")})
        data.update(kwargs)
        return data

    def test_ordinary_and_general_hr_permissions_cannot_read_or_edit(self):
        self.grant("view_employee","change_employee")
        for method in ("get","post"):
            self.assertEqual(singapore_contributions(self.request(method,self.data()),self.employee.pk).status_code,403)
        self.assertFalse(SingaporeDetailsAudit.objects.exists())

    def test_reuses_view_permission_but_edit_requires_existing_change_permission(self):
        self.grant("view_singaporeemployeedetails")
        with patch("employee.contributions.render",return_value=HttpResponse("ok")):
            response=singapore_contributions(self.request(),self.employee.pk)
        self.assertEqual(response.status_code,200);self.assertIn("no-store",response["Cache-Control"])
        self.assertEqual(singapore_contributions(self.request(query="?edit=1"),self.employee.pk).status_code,403)
        self.assertEqual(singapore_contributions(self.request("post",self.data()),self.employee.pk).status_code,403)

    def test_company_boundary_remains_enforced(self):
        self.grant("view_singaporeemployeedetails","change_singaporeemployeedetails")
        self.assertEqual(singapore_contributions(self.request(),self.other.pk).status_code,403)

    @override_settings(COMPANY_SCOPED_PERMISSIONS=True)
    def test_cross_company_role_union_cannot_access_profile(self):
        group=Group.objects.create(name="SHG restricted QA")
        group.permissions.add(*Permission.objects.filter(codename__in=["view_singaporeemployeedetails","change_singaporeemployeedetails"]))
        basic=Group.objects.create(name="SHG basic QA")
        CompanyGroupAssignment.objects.create(user=self.hr.employee_user_id,group=group,company_id=self.company.pk)
        CompanyGroupAssignment.objects.create(user=self.hr.employee_user_id,group=basic,company_id=self.other.employee_work_info.company_id_id)
        for method in ("get","post"):
            self.assertEqual(singapore_contributions(self.request(method,self.data()),self.other.pk).status_code,403)

    def test_save_adds_version_and_audits_field_names_without_sensitive_values(self):
        self.grant("view_singaporeemployeedetails","change_singaporeemployeedetails")
        data=self.data(cdac_mode="opt_out",cdac_reference="Private form reference")
        with patch("employee.contributions.messages.success"):
            response=singapore_contributions(self.request("post",data),self.employee.pk)
        self.assertEqual(response.status_code,302)
        record=SingaporeContributionProfile.objects.get(employee=self.employee)
        self.assertEqual(record.fund_adjustments["cdac"]["mode"],"opt_out")
        self.assertEqual(record.created_by,self.hr.employee_user_id)
        event=SingaporeDetailsAudit.objects.get();self.assertEqual(event.action,"update_contribution")
        self.assertNotIn("Private form reference",str(event.fields));self.assertNotIn("chinese",str(event.fields))
        second=self.data(revision=str(record.pk),effective_month="2026-10-01")
        with patch("employee.contributions.messages.success"):
            singapore_contributions(self.request("post",second),self.employee.pk)
        self.assertEqual(SingaporeContributionProfile.objects.count(),2)
        self.assertEqual(profile_for(self.employee,date(2026,9,30)).pk,record.pk)

    def test_stale_revision_rejected_without_overwriting_history(self):
        self.grant("view_singaporeemployeedetails","change_singaporeemployeedetails")
        with patch("employee.contributions.messages.success"):
            singapore_contributions(self.request("post",self.data()),self.employee.pk)
        with patch("employee.contributions.render",return_value=HttpResponse("ok")) as render:
            singapore_contributions(self.request("post",self.data()),self.employee.pk)
        self.assertIn("changed while",str(render.call_args.args[2]["form"].non_field_errors()))
        self.assertEqual(SingaporeContributionProfile.objects.count(),1)

    def test_unknown_race_and_faith_must_be_confirmed(self):
        form=ContributionProfileForm(self.data(primary_race="",muslim_status=""),instance=SingaporeContributionProfile(employee=self.employee))
        self.assertFalse(form.is_valid());self.assertIn("primary_race",form.errors);self.assertIn("muslim_status",form.errors)

    def test_adjustments_require_proof_and_correct_amount(self):
        for overrides in [{"cdac_mode":"opt_out"}, {"cdac_mode":"fixed","cdac_reference":"proof"},
                          {"cdac_mode":"opt_out","cdac_reference":"proof","cdac_amount":"1"},
                          {"cdac_mode":"fixed","cdac_reference":"proof","cdac_amount":"NaN"},
                          {"cdac_mode":"auto","cdac_reference":"proof"}]:
            with self.subTest(overrides=overrides):
                form=ContributionProfileForm(self.data(**overrides),instance=SingaporeContributionProfile(employee=self.employee))
                self.assertFalse(form.is_valid());self.assertTrue(form.errors)

    def test_documented_fixed_amount_accepts_one_cent(self):
        form=ContributionProfileForm(self.data(cdac_mode="fixed",cdac_amount="0.01",cdac_reference="Approved form"),
            instance=SingaporeContributionProfile(employee=self.employee))
        self.assertTrue(form.is_valid(),form.errors)
        self.assertEqual(form.instance.fund_adjustments["cdac"]["amount"],"0.01")

    def test_model_requires_first_day_and_student_evidence(self):
        for overrides in [{"effective_month":"2026-09-15"},{"student_cpf_exempt":"on"},
                          {"residency_status":"pr"},{"residency_status":"foreigner"},
                          {"residency_status":"pr","pr_effective_date":"2026-10-01"},
                          {"primary_race":"malay","cdac_mode":"fixed","cdac_amount":"2","cdac_reference":"proof"}]:
            with self.subTest(overrides=overrides):
                form=ContributionProfileForm(self.data(**overrides),instance=SingaporeContributionProfile(employee=self.employee))
                self.assertFalse(form.is_valid())

    def test_history_view_is_scoped_to_the_employee_and_read_permission(self):
        self.grant("view_singaporeemployeedetails")
        record=SingaporeContributionProfile.objects.create(employee=self.employee,effective_month=date(2026,9,1),
            primary_race="chinese",muslim_status="no",residency_status="citizen",declaration_reference="QA")
        with patch("employee.contributions.render",return_value=HttpResponse("ok")) as render:
            singapore_contributions(self.request(query=f"?version={record.pk}"),self.employee.pk)
        self.assertEqual(render.call_args.args[2]["current"].pk,record.pk)
        from django.http import Http404
        for query in (f"?version={record.pk}","?version=invalid"):
            with self.assertRaises(Http404): singapore_contributions(self.request(query=query),self.hr.pk if query.endswith(str(record.pk)) else self.employee.pk)

    def test_declarations_are_immutable_and_latest_same_month_correction_wins(self):
        record=SingaporeContributionProfile.objects.create(employee=self.employee,effective_month=date(2026,9,1),
            primary_race="chinese",muslim_status="no",residency_status="citizen",declaration_reference="verified")
        record.primary_race="other"
        with self.assertRaisesMessage(ValidationError,"immutable"):record.save()
        record.refresh_from_db();self.assertEqual(record.primary_race,"chinese")
        new=SingaporeContributionProfile.objects.create(employee=self.employee,effective_month=date(2026,9,1),
            primary_race="other",muslim_status="no",residency_status="citizen",declaration_reference="corrected")
        self.assertEqual(profile_for(self.employee,date(2026,9,30)).pk,new.pk)

    def test_no_new_permissions_or_employee_relations_or_generic_export(self):
        self.assertFalse(Permission.objects.filter(content_type__model="singaporecontributionprofile").exists())
        self.assertNotIn("singaporecontributionprofile",[field.name for field in Employee._meta.get_fields()])
        self.assertFalse(has_export_access(self.request(),SingaporeContributionProfile))
        req=self.request();req.user.is_superuser=True
        self.assertFalse(has_export_access(req,SingaporeContributionProfile))
        from horilla_views.views import export_data
        req=self.request("post",{"ids":"[]","columns":"[]"})
        req.GET={"model":"employee.SingaporeContributionProfile"}
        self.assertEqual(export_data(req).status_code,403)

    def test_read_only_page_does_not_include_edit_form(self):
        self.grant("view_singaporeemployeedetails")
        with patch("employee.contributions.render",return_value=HttpResponse("ok")) as render:
            singapore_contributions(self.request(),self.employee.pk)
        context=render.call_args.args[2];self.assertIsNone(context["form"]);self.assertFalse(context["can_edit"])

    def test_default_salary_month_uses_singapore_local_date(self):
        self.grant("view_singaporeemployeedetails","change_singaporeemployeedetails")
        with patch("employee.contributions.timezone.localdate",return_value=date(2026,10,1)), \
             patch("employee.contributions.render",return_value=HttpResponse("ok")) as render:
            singapore_contributions(self.request(query="?edit=1"),self.employee.pk)
        self.assertEqual(render.call_args.args[2]["form"].initial["effective_month"],date(2026,10,1))
