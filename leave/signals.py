from django.db import router
from django.db.models import QuerySet
# leave/signals.py

import threading

from django.apps import apps
from django.db.models.signals import post_migrate, post_save, pre_delete, pre_save
from django.dispatch import receiver
from django.utils.translation import gettext_lazy as _

from employee.models import EmployeeWorkInformation
from horilla.methods import get_horilla_model_class
from leave.models import LeaveRequest, LeaveRequestConditionApproval
from leave.services import schedule_auto_leave_sync

def leave_work_record_defaults(instance, day):
    half_day = (day == instance.start_date and instance.start_date_breakdown != "full_day") or (
        day == instance.end_date and instance.end_date_breakdown != "full_day")
    return {
        "is_leave_record": True, "leave_request_id": instance,
        "day_percentage": 0.5 if half_day else 0.0,
        "work_record_type": "CONF" if half_day else "ABS",
        "message": _("Half day Attendance need to validate") if half_day else "Leave",
    }


if apps.is_installed("attendance"):

    @receiver(post_save, sender=LeaveRequest)
    def leaverequest_pre_save(sender, instance, **_kwargs):
        """
        Overriding LeaveRequest model save method
        """
        WorkRecords = get_horilla_model_class(
            app_label="attendance", model="workrecords"
        )
        if (
            instance.start_date == instance.end_date
            and instance.end_date_breakdown != instance.start_date_breakdown
        ):
            instance.end_date_breakdown = instance.start_date_breakdown
            super(LeaveRequest, instance).save()

        period_dates = instance.requested_dates()
        if instance.status == "approved":
            for day in period_dates:
                # A failure must propagate to the approval transaction. Silently
                # swallowing a DB error leaves an approved request without its
                # attendance record (and breaks PostgreSQL's transaction).
                # The company manager adds DISTINCT, which is incompatible with
                # update_or_create's PostgreSQL row lock. The request already scopes the employee.
                QuerySet(model=WorkRecords, using=router.db_for_write(WorkRecords)).update_or_create(
                    date=day,
                    employee_id=instance.employee_id,
                    defaults=leave_work_record_defaults(instance, day),
                )
        else:
            WorkRecords._base_manager.filter(
                is_leave_record=True,
                leave_request_id=instance,
            ).delete()


    @receiver(pre_delete, sender=LeaveRequest)
    def leaverequest_pre_delete(sender, instance, **kwargs):
        from attendance.models import WorkRecords

        work_records = WorkRecords._base_manager.filter(
            leave_request_id=instance
        ).delete()


# @receiver(post_migrate)
def add_missing_leave_to_workrecords(sender, **kwargs):
    if sender.label not in ["attendance", "leave"]:
        return

    if not apps.is_installed("attendance"):
        return
    try:
        from attendance.models import WorkRecords
        from leave.models import LeaveRequest

        work_records = WorkRecords.objects.filter(
            is_leave_record=True, leave_request_id__isnull=True
        )
        if not work_records.exists():
            return

        leave_requests = LeaveRequest.objects.all()
        date_leave_map = {}

        for leave in leave_requests:
            for date in leave.requested_dates():
                key = (leave.employee_id, date)
                date_leave_map[key] = leave

        records_to_update = []
        for record in work_records:
            leave_request = date_leave_map.get((record.employee_id, record.date))
            if leave_request:
                record.leave_request_id = leave_request
                records_to_update.append(record)

        if records_to_update:
            WorkRecords.objects.bulk_update(
                records_to_update, ["leave_request_id"], batch_size=500
            )
            print(
                f"Successfully updated {len(records_to_update)} work records with leave information"
            )

    except Exception as e:
        print(f"Error in leave/work records sync: {e}")


@receiver(post_save, sender=LeaveRequestConditionApproval)
def auto_approve_self_approval_stage(sender, instance, created, **kwargs):
    """
    When an approver in the multiple-approval chain is the same employee who
    submitted the leave request, automatically approve their stage so the
    request is not stuck and can progress to the next approver.
    """
    if created and instance.manager_id == instance.leave_request_id.employee_id:
        sender.objects.filter(pk=instance.pk).update(is_approved=True)


# Automatic leave entitlement depends on these dates.
AUTO_LEAVE_DATE_FIELDS = ("date_joining", "contract_end_date")


@receiver(pre_save, sender=EmployeeWorkInformation)
def remember_auto_leave_dates(sender, instance, raw=False, **kwargs):
    if raw or not instance.pk:
        return
    instance._previous_auto_leave_dates = (
        EmployeeWorkInformation._base_manager.filter(pk=instance.pk)
        .values_list(*AUTO_LEAVE_DATE_FIELDS)
        .first()
    )


@receiver(post_save, sender=EmployeeWorkInformation)
def resync_auto_leave_on_date_change(sender, instance, created, raw=False, **kwargs):
    """
    Recalculate annual and sick leave when HR corrects the joining or
    contract end date, instead of waiting for the periodic leave job.
    """
    if raw or created:
        return
    previous = getattr(instance, "_previous_auto_leave_dates", None)
    current = tuple(getattr(instance, field) for field in AUTO_LEAVE_DATE_FIELDS)
    if previous is not None and previous != current:
        schedule_auto_leave_sync([instance.employee_id])
