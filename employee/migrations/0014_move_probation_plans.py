"""Move legacy plans without inferring that anyone has passed probation."""

from collections import defaultdict
from django.db import migrations
from django.utils import timezone


def move_plans(apps, schema_editor):
    db = schema_editor.connection.alias
    Candidate = apps.get_model("recruitment", "Candidate")
    Work = apps.get_model("employee", "EmployeeWorkInformation")
    History = apps.get_model("employee", "HistoricalEmployeeWorkInformation")
    Tracking = apps.get_model("horilla_audit", "HistoryTrackingFields")
    plans = defaultdict(set)
    for employee_id, end in (
        Candidate.objects.using(db)
        .exclude(converted_employee_id=None)
        .exclude(probation_end=None)
        .values_list("converted_employee_id", "probation_end")
    ):
        plans[employee_id].add(end)
    moved = invalid = conflicts = 0
    for employee_id, dates in plans.items():
        if len(dates) != 1:
            conflicts += 1
            continue
        end = next(iter(dates))
        work = Work.objects.using(db).filter(employee_id=employee_id).first()
        if not work or (work.date_joining and end < work.date_joining):
            invalid += 1
            continue
        if (
            work.probation_status != "not_recorded"
            or work.probation_end
            or work.probation_updated_at
        ):
            continue
        now = timezone.now()
        Work.objects.using(db).filter(pk=work.pk).update(
            probation_end=end, probation_status="on_probation", probation_updated_at=now
        )
        work.probation_end, work.probation_status, work.probation_updated_at = (
            end,
            "on_probation",
            now,
        )
        history_fields = {f.attname for f in History._meta.concrete_fields}
        data = {
            f.attname: getattr(work, f.attname)
            for f in Work._meta.concrete_fields
            if f.attname in history_fields
        }
        History.objects.using(db).create(
            **data,
            history_relation_id=work.pk,
            history_type="~",
            history_date=now,
            history_change_reason="Moved planned probation end from onboarding; not a confirmation.",
        )
        moved += 1
    fields = [
        "probation_status",
        "probation_end",
        "probation_passed_on",
        "probation_updated_by",
        "probation_updated_at",
    ]
    for tracker in Tracking.objects.using(db).all():
        previous = tracker.tracking_fields or {}
        names = (
            previous.get("tracking_fields", [])
            if isinstance(previous, dict)
            else previous
        )
        payload = dict(previous) if isinstance(previous, dict) else {}
        payload["tracking_fields"] = list(dict.fromkeys(list(names or []) + fields))
        Tracking.objects.using(db).filter(pk=tracker.pk).update(tracking_fields=payload)
    print(
        f"Probation plans moved={moved}; retained for HR review: invalid/missing-work={invalid}, conflicting={conflicts}. No employees marked passed."
    )


class Migration(migrations.Migration):
    dependencies = [
        ("employee", "0013_employee_probation"),
        (
            "recruitment",
            "0006_alter_rejectreason_options_alter_skillzone_options_and_more",
        ),
        ("horilla_audit", "0003_alter_historytrackingfields_options_and_more"),
    ]
    operations = [migrations.RunPython(move_plans, migrations.RunPython.noop)]
