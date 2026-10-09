from datetime import date
from unittest.mock import patch
from django.db import DataError
from django.test import TestCase
from attendance.models import WorkRecords
from horilla.testkit import make_company, make_employee
from leave.models import AvailableLeave, LeaveRequest, LeaveType


class LeaveWorkRecordTests(TestCase):
    def setUp(self):
        self.employee=make_employee(company=make_company('Leave work records'),email='leave-work-records@test.example')
        self.kind=LeaveType.objects.create(name='Work record unpaid',payment='unpaid',payment_type='unpaid')

    def request(self,**kwargs):
        return LeaveRequest.objects.create(employee_id=self.employee,leave_type_id=self.kind,
            start_date=date(2026,9,8),end_date=date(2026,9,9),status='approved',description='QA',**kwargs)

    def test_both_half_boundaries_are_preserved_with_full_explanation(self):
        for first,last in [('first_half','second_half'),('second_half','first_half')]:
            req=self.request(start_date_breakdown=first,end_date_breakdown=last)
            rows=list(WorkRecords.objects.filter(leave_request_id=req).order_by('date'))
            self.assertEqual(len(rows),2)
            self.assertEqual([r.day_percentage for r in rows],[0.5,0.5])
            self.assertTrue(all(len(r.message)>30 for r in rows))
            req.delete()

    def test_work_record_failure_rolls_back_request_instead_of_success(self):
        with patch('django.db.models.query.QuerySet.update_or_create',side_effect=DataError('QA failure')):
            with self.assertRaises(DataError):self.request()
        self.assertFalse(LeaveRequest.objects.filter(employee_id=self.employee).exists())

    def test_rejection_only_removes_own_records(self):
        req=self.request();req.status='rejected';req.save()
        self.assertFalse(WorkRecords.objects.filter(leave_request_id=req).exists())

    def test_scoped_historical_repair_previews_and_is_idempotent(self):
        from io import StringIO
        from django.core.management import call_command
        from django.core.management.base import CommandError
        req=self.request(start_date_breakdown='first_half',end_date_breakdown='second_half')
        WorkRecords.objects.filter(leave_request_id=req).delete()
        before=list(LeaveRequest.objects.filter(pk=req.pk).values())
        with self.assertRaisesMessage(CommandError,'unscoped'):
            call_command('repair_leave_work_records',stdout=StringIO())
        call_command('repair_leave_work_records',request_id=[req.pk],stdout=StringIO())
        self.assertFalse(WorkRecords.objects.filter(leave_request_id=req).exists())
        for _ in range(2):
            call_command('repair_leave_work_records',request_id=[req.pk],apply=True,stdout=StringIO())
        self.assertEqual(WorkRecords.objects.filter(leave_request_id=req).count(),2)
        self.assertEqual(before,list(LeaveRequest.objects.filter(pk=req.pk).values()))


class BulkApiApprovalTests(TestCase):
    def test_manager_bulk_action_skips_own_request_but_approves_report(self):
        from rest_framework.test import APIRequestFactory, force_authenticate
        from horilla_api.api_views.leave.views import LeaveRequestBulkApproveDeleteAPIview
        company=make_company('Bulk approval QA')
        manager=make_employee(company=company,email='bulk-manager@test.example')
        report=make_employee(company=company,email='bulk-report@test.example')
        work=report.employee_work_info;work.reporting_manager_id=manager;work.save()
        kind=LeaveType.objects.create(name='Bulk approval leave',total_days=10)
        requests=[];balances=[]
        for employee in [manager,report]:
            balances.append(AvailableLeave.objects.create(employee_id=employee,leave_type_id=kind,
                available_days=10,carryforward_days=0))
            requests.append(LeaveRequest.objects.create(employee_id=employee,leave_type_id=kind,
                start_date=date(2026,9,8),end_date=date(2026,9,8),description='QA'))
        request=APIRequestFactory().put('/api/leave/request-bulk-action/',
            {'leave_request_id':[str(item.pk) for item in requests]},format='multipart')
        force_authenticate(request,user=manager.employee_user_id)
        response=LeaveRequestBulkApproveDeleteAPIview.as_view()(request)
        self.assertEqual(response.status_code,200)
        for item in requests+balances:item.refresh_from_db()
        self.assertEqual([item.status for item in requests],['requested','approved'])
        self.assertEqual([item.available_days for item in balances],[10,9])
