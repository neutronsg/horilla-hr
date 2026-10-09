"""Exercise real PostgreSQL locks with independent HTTP sessions/connections."""
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from unittest import skipUnless
from unittest.mock import patch
from django.db import connection, connections, close_old_connections
from django.test import Client, TransactionTestCase
from horilla.testkit import make_employee, make_company
from horilla.horilla_middlewares import _thread_locals, set_selected_company
from leave.models import AvailableLeave, LeaveRequest, LeaveType


@skipUnless(connection.vendor=='postgresql','Requires PostgreSQL row locks')
class ConcurrentApprovalTests(TransactionTestCase):
    def setUp(self):
        self.company=make_company('Concurrent leave QA')
        self.employee=make_employee(company=self.company,email='concurrent-employee@test.example')
        self.admin=make_employee(company=self.company,email='concurrent-admin@test.example')
        user=self.admin.employee_user_id;user.is_superuser=True;user.is_staff=True;user.is_new_employee=False;user.save()
        self.kind=LeaveType.objects.create(name='Concurrency annual',total_days=1)
        self.balance=AvailableLeave.objects.create(employee_id=self.employee,leave_type_id=self.kind,
            available_days=1,carryforward_days=0)
        self.requests=[LeaveRequest.objects.create(employee_id=self.employee,leave_type_id=self.kind,
            start_date=date(2026,10,day),end_date=date(2026,10,day),description='Concurrent QA') for day in [19,20]]
        self.clients=[]
        for _ in range(2):
            client=Client();client.force_login(user,backend='base.auth_backends.CompanyScopedBackend')
            session=client.session;session['selected_company']=str(self.company.pk);session.save()
            self.clients.append(client)

    def approve(self,index,barrier):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return self.clients[index].get(f'/leave/request-approve/{self.requests[index].pk}/',HTTP_HX_REQUEST='true').status_code
        finally:
            connections.close_all();_thread_locals.request=None;set_selected_company(None)

    def test_two_requests_compete_for_one_day_and_only_one_is_approved(self):
        barrier=threading.Barrier(2)
        with patch('leave.views.LeaveMailSendThread.start'),ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(self.approve,index,barrier) for index in range(2)]
            self.assertEqual([future.result(timeout=20) for future in futures],[200,200])
        self.balance.refresh_from_db()
        for request in self.requests:request.refresh_from_db()
        self.assertEqual(sum(r.status=='approved' for r in self.requests),1)
        self.assertEqual(sum(r.approved_available_days for r in self.requests),1)
        self.assertEqual(self.balance.available_days,0)
