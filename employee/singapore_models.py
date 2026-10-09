"""Restricted Singapore employment data, separate from generic employee APIs."""

from datetime import date
import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from employee.singapore_fields import EncryptedHRTextField


class SingaporeEmployeeDetails(models.Model):
    restricted_hr_model = True
    employee = models.OneToOneField(
        "employee.Employee", on_delete=models.PROTECT, related_name="+"
    )
    identity_type = models.CharField(
        max_length=4, blank=True, choices=[("NRIC", "NRIC"), ("FIN", "FIN")]
    )
    identity_number = EncryptedHRTextField(max_length=9, blank=True, default="")
    residency_status = models.CharField(max_length=12, blank=True, choices=[
        ("citizen", _("Singapore Citizen")),
        ("pr", _("Permanent Resident")),
        ("foreigner", _("Foreigner")),
    ])
    pr_effective_date = models.DateField(null=True, blank=True)
    work_pass_type = models.CharField(max_length=30, blank=True, choices=[
        ("EP", _("Employment Pass")), ("S_PASS", _("S Pass")),
        ("WORK_PERMIT", _("Work Permit")), ("PEP", _("Personalised Employment Pass")),
        ("ENTREPASS", _("EntrePass")), ("ONE_PASS", _("ONE Pass")),
        ("LTVP", _("Long-Term Visit Pass")), ("DP", _("Dependant's Pass")),
        ("OTHER", _("Other")),
    ])
    work_pass_number = EncryptedHRTextField(max_length=50, blank=True, default="")
    work_pass_expiry = models.DateField(null=True, blank=True)
    personal_email = models.EmailField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        default_permissions = ("view", "change")
        verbose_name = _("Singapore employment details")
        verbose_name_plural = _("Singapore employment details")

    def __str__(self):
        return f"Singapore employment details — employee {self.employee_id}"

    @property
    def masked_identity_number(self):
        return "•••••" + self.identity_number[-4:] if self.identity_number else ""

    @property
    def masked_work_pass_number(self):
        return "•••••" + self.work_pass_number[-4:] if self.work_pass_number else ""

    def clean(self):
        super().clean()
        errors = {}
        self.identity_number = (self.identity_number or "").strip().upper()
        self.work_pass_number = (self.work_pass_number or "").strip().upper()
        if self.identity_number:
            pattern = {"NRIC": r"[ST][0-9]{7}[A-Z]", "FIN": r"[FGM][0-9]{7}[A-Z]"}
            if not self.identity_type:
                errors["identity_type"] = _("Select NRIC or FIN when supplying an identifier.")
            elif not re.fullmatch(pattern.get(self.identity_type, r"(?!)"), self.identity_number):
                errors["identity_number"] = _("Enter a valid identifier format for the selected type.")
        if self.pr_effective_date:
            if self.residency_status != "pr":
                errors["pr_effective_date"] = _("PR effective date requires Permanent Resident status.")
            elif self.pr_effective_date > date.today():
                errors["pr_effective_date"] = _("PR effective date cannot be in the future.")
        if self.residency_status in ("citizen", "pr") and self.identity_type == "FIN":
            errors["identity_type"] = _("Select NRIC for a citizen or permanent resident.")
        if self.residency_status == "foreigner" and self.identity_type == "NRIC":
            errors["identity_type"] = _("Select FIN for a foreign employee.")
        if self.work_pass_type and self.residency_status in ("citizen", "pr"):
            errors["work_pass_type"] = _("Work-pass details apply to foreign employees.")
        if (self.work_pass_number or self.work_pass_expiry) and not self.work_pass_type:
            errors["work_pass_type"] = _("Select a work-pass type when supplying pass details.")
        if errors:
            raise ValidationError(errors)


class SingaporeDetailsAudit(models.Model):
    """Who accessed/changed which fields, never their sensitive values."""

    restricted_hr_model = True
    employee = models.ForeignKey("employee.Employee", on_delete=models.PROTECT, related_name="+")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    occurred_at = models.DateTimeField(auto_now_add=True)
    action = models.CharField(max_length=20)
    fields = models.JSONField(default=list)

    class Meta:
        default_permissions = ()
        ordering = ["-occurred_at"]


class SingaporeContributionProfile(models.Model):
    """Append-only HR declarations, effective by salary month, with no public API relation."""

    restricted_hr_model = True
    employee = models.ForeignKey("employee.Employee", on_delete=models.PROTECT, related_name="+")
    effective_month = models.DateField(verbose_name=_("Effective salary month"))
    primary_race = models.CharField(max_length=12, choices=[
        ("chinese", _("Chinese")), ("malay", _("Malay")), ("indian", _("Indian")),
        ("eurasian", _("Eurasian")), ("other", _("Other")),
    ], verbose_name=_("Primary race on NRIC / employee declaration"))
    muslim_status = models.CharField(max_length=3, choices=[("yes", _("Yes")), ("no", _("No"))],
                                     verbose_name=_("Muslim"))
    residency_status = models.CharField(max_length=12, choices=SingaporeEmployeeDetails._meta.get_field("residency_status").choices,
                                       verbose_name=_("Residency during this period"))
    pr_effective_date = models.DateField(null=True, blank=True)
    work_pass_type = models.CharField(max_length=30, blank=True,
        choices=SingaporeEmployeeDetails._meta.get_field("work_pass_type").choices)
    declaration_reference = models.CharField(max_length=255, verbose_name=_("HR verification / declaration reference"))
    student_cpf_exempt = models.BooleanField(default=False,
        verbose_name=_("Verified student exemption for CPF / CDAC / ECF / SINDA"))
    student_mbmf_exempt = models.BooleanField(default=False,
        verbose_name=_("Verified student exemption for MBMF"))
    student_exempt_from = models.DateField(null=True, blank=True)
    student_exempt_until = models.DateField(null=True, blank=True)
    student_exemption_reference = models.CharField(max_length=255, blank=True)
    fund_adjustments = models.JSONField(default=dict, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        default_permissions = ()
        ordering = ["-effective_month", "-pk"]
        indexes = [models.Index(fields=["employee", "effective_month"], name="sg_shg_employee_month")]

    def clean(self):
        super().clean()
        errors = {}
        if self.effective_month and self.effective_month.day != 1:
            errors["effective_month"] = _("Use the first day of the effective salary month.")
        if not self.declaration_reference.strip():
            errors["declaration_reference"] = _("Record the NRIC / employee declaration verification reference.")
        if self.residency_status == "pr" and not self.pr_effective_date:
            errors["pr_effective_date"] = _("Record the PR effective date.")
        if self.pr_effective_date and self.residency_status != "pr":
            errors["pr_effective_date"] = _("PR effective date requires Permanent Resident status.")
        if self.pr_effective_date and self.effective_month:
            import calendar
            last_day = self.effective_month.replace(day=calendar.monthrange(self.effective_month.year, self.effective_month.month)[1])
            if self.pr_effective_date > last_day:
                errors["pr_effective_date"] = _("PR effective date cannot be after the declaration's salary month.")
        if self.residency_status in {"citizen", "pr"} and self.work_pass_type:
            errors["work_pass_type"] = _("Work-pass type applies to foreign employees.")
        if self.residency_status == "foreigner" and not self.work_pass_type:
            errors["work_pass_type"] = _("Confirm the foreign employee's work-pass type.")
        if self.student_cpf_exempt or self.student_mbmf_exempt:
            if not self.student_exemption_reference.strip():
                errors["student_exemption_reference"] = _("Record the qualifying institution / MUIS exemption evidence.")
            if not self.student_exempt_from or not self.student_exempt_until:
                errors["student_exempt_until"] = _("Record both exemption dates.")
            elif self.student_exempt_until < self.student_exempt_from:
                errors["student_exempt_until"] = _("Exemption end cannot precede its start.")
        from payroll.shg import validate_adjustments
        try:
            validate_adjustments(self.fund_adjustments)
        except ValidationError as exc:
            errors["__all__"] = exc.messages
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Contribution declarations are immutable. Save a new effective version.")
        self.full_clean()
        return super().save(*args, **kwargs)
