"""Company reminder policy and narrowly scoped email attempt records."""

import datetime

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class ClaimReminderPolicy(models.Model):
    restricted_hr_model = True
    company = models.OneToOneField("base.Company", on_delete=models.CASCADE)
    submission_enabled = models.BooleanField(default=False)
    cutoff_day = models.PositiveSmallIntegerField(
        default=25, validators=[MinValueValidator(1), MaxValueValidator(31)]
    )
    days_before = models.PositiveSmallIntegerField(
        default=3, validators=[MaxValueValidator(14)]
    )
    submission_time = models.TimeField(default=datetime.time(9))
    approval_enabled = models.BooleanField(default=False)
    approval_time = models.TimeField(default=datetime.time(9))
    include_admin = models.BooleanField(default=False)
    timezone = models.CharField(max_length=64, default="Asia/Singapore")
    base_url = models.URLField(default="https://hr.neutron.sg")
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        default_permissions = ()


class ClaimReminderDelivery(models.Model):
    restricted_hr_model = True
    policy = models.ForeignKey(ClaimReminderPolicy, on_delete=models.CASCADE)
    kind = models.CharField(max_length=16)
    cycle = models.CharField(max_length=10)
    employee = models.ForeignKey("employee.Employee", on_delete=models.CASCADE)
    recipient = models.EmailField(blank=True)
    status = models.CharField(max_length=16, default="sending")
    detail = models.CharField(max_length=240, blank=True)
    attempted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(
                fields=("policy", "kind", "cycle", "employee"),
                name="unique_claim_reminder_delivery",
            )
        ]


class PayslipEmailDelivery(models.Model):
    restricted_hr_model = True
    batch = models.UUIDField(db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL
    )
    employee = models.ForeignKey("employee.Employee", on_delete=models.CASCADE)
    payslip_ids = models.JSONField(default=list)
    recipient = models.EmailField(blank=True)
    status = models.CharField(max_length=16, default="pending")
    detail = models.CharField(max_length=240, blank=True)
    attempted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        default_permissions = ()
