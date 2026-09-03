from leave.models import EmployeePastLeaveRestrict

try:
    enabled_restriction = EmployeePastLeaveRestrict.objects.first()
    if not enabled_restriction:
        enabled_restriction = EmployeePastLeaveRestrict.objects.create(enabled=False)
except:
    pass
