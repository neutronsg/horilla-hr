"""Preview or repair missing attendance records for explicitly scoped approved leave."""
from django.core.management.base import BaseCommand, CommandError
from django.db import router
from django.db.models import QuerySet
from attendance.models import WorkRecords
from leave.locking import employee_leave_lock
from leave.models import LeaveRequest
from leave.signals import leave_work_record_defaults


class Command(BaseCommand):
    help = "Preview missing approved-leave WorkRecords. --apply creates only missing records; existing attendance and leave balances are preserved."

    def add_arguments(self, parser):
        parser.add_argument('--request-id', type=int, action='append')
        parser.add_argument('--company-id', type=int)
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        if not options['request_id'] and not options['company_id']:
            raise CommandError('Specify --request-id or --company-id; an unscoped repair is refused.')
        requests = LeaveRequest._base_manager.filter(status='approved')
        if options['request_id']:
            requests = requests.filter(pk__in=options['request_id'])
        if options['company_id']:
            requests = requests.filter(employee_id__employee_work_info__company_id_id=options['company_id'])
        repaired = 0
        for candidate in requests.order_by('employee_id_id', 'pk'):
            with employee_leave_lock(candidate.employee_id_id):
                instance = LeaveRequest._base_manager.get(pk=candidate.pk)
                if instance.status != 'approved':
                    continue
                records = QuerySet(model=WorkRecords, using=router.db_for_write(WorkRecords))
                missing = [day for day in instance.requested_dates()
                    if not records.filter(employee_id=instance.employee_id, date=day).exists()]
                if missing:
                    self.stdout.write(f'Request {instance.pk}: {len(missing)} missing record(s)')
                if options['apply']:
                    for day in missing:
                        records.create(employee_id=instance.employee_id, date=day,
                            **leave_work_record_defaults(instance, day))
                repaired += len(missing)
        self.stdout.write(f'{"Created" if options["apply"] else "Would create"} {repaired} record(s). Leave balances and existing records unchanged.')
