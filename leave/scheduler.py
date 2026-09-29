import sys
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from django.utils import timezone

from horilla.signals import post_scheduler, pre_scheduler


def leave_reset():
    pre_scheduler.send(sender=leave_reset)
    from leave.models import LeaveType
    from leave.annual_policy import sync_annual_leave
    from leave.sick_policy import sync_sick_leave

    today = datetime.now()
    today_date = timezone.localdate()
    for auto_type in LeaveType.objects.exclude(auto_leave_policy="none"):
        for assignment in auto_type.employee_available_leave.all():
            if auto_type.auto_leave_policy == "annual":
                sync_annual_leave(assignment.employee_id, auto_type, today_date)
            else:
                sync_sick_leave(assignment.employee_id, auto_type, today_date)

    leave_types = LeaveType.objects.filter(reset=True, auto_leave_policy="none")
    # Looping through filtered leave types with reset is true
    for leave_type in leave_types:
        # Looping through all available leaves
        available_leaves = leave_type.employee_available_leave.all()

        for available_leave in available_leaves:
            reset_date = available_leave.reset_date
            expired_date = available_leave.expired_date
            if reset_date == today_date:
                available_leave.update_carryforward()
                # new_reset_date = available_leave.set_reset_date(assigned_date=today_date,available_leave = available_leave)
                new_reset_date = available_leave.set_reset_date(
                    assigned_date=today_date, available_leave=available_leave
                )
                available_leave.reset_date = new_reset_date
                available_leave.save()
            if expired_date and expired_date <= today_date:
                new_expired_date = available_leave.set_expired_date(
                    available_leave=available_leave, assigned_date=today_date
                )
                available_leave.expired_date = new_expired_date
                available_leave.save()

        if (
            leave_type.carryforward_expire_date
            and leave_type.carryforward_expire_date <= today_date
        ):
            leave_type.carryforward_expire_date = leave_type.set_expired_date(
                today_date
            )
            leave_type.save()
    post_scheduler.send(
        sender=leave_reset,
        **{
            "today": today,
            "today_date": today_date,
            "leave_types": leave_types,
        }
    )


if not any(
    cmd in sys.argv
    for cmd in ["makemigrations", "migrate", "compilemessages", "flush", "shell"]
):
    """
    Initializes and starts background tasks using APScheduler when the server is running.
    """
    scheduler = BackgroundScheduler()
    scheduler.add_job(leave_reset, "interval", hours=4)

    scheduler.start()
