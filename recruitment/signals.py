from django.db.models.signals import m2m_changed, post_save, pre_save
from django.dispatch import receiver

from recruitment.models import (
    Candidate,
    CandidateDocument,
    CandidateDocumentRequest,
    Recruitment,
    Stage,
)


@receiver(post_save, sender=Recruitment)
def create_initial_stage(sender, instance, created, **kwargs):
    """
    This is post save method, used to create initial stage for the recruitment
    """
    # raw=True during fixture loading (loaddata): a fixture provides its own
    # Stage rows with explicit pks, and those load *after* this signal would
    # fire (Recruitment rows come first in the file). Auto-creating stages
    # here would grab the lowest pks first, which the fixture's own
    # explicit-pk Stage rows then silently overwrite by pk on save -- e.g. a
    # different recruitment's stage getting reassigned to this one.
    if kwargs.get("raw"):
        return
    if created:
        applied_stage = Stage()
        applied_stage.sequence = 0
        applied_stage.recruitment_id = instance
        applied_stage.stage = "Applied"
        applied_stage.stage_type = "applied"
        applied_stage.save()

        initial_stage = Stage()
        initial_stage.sequence = 1
        initial_stage.recruitment_id = instance
        initial_stage.stage = "Initial"
        initial_stage.stage_type = "initial"
        initial_stage.save()


@receiver(m2m_changed, sender=CandidateDocumentRequest.candidate_id.through)
def document_request_m2m_changed(sender, instance, action, **kwargs):
    if action == "post_add":
        candidate_document_create(instance)

    elif action == "post_remove":
        candidate_document_create(instance)


def candidate_document_create(instance):
    candidates = instance.candidate_id.all()
    for candidate in candidates:
        document, created = CandidateDocument.objects.get_or_create(
            candidate_id=candidate,
            document_request_id=instance,
            defaults={"title": f"Upload {instance.title}"},
        )
        document.title = f"Upload {instance.title}"
        document.save()


@receiver(pre_save, sender=Candidate)
def remember_probation_employee_link(sender, instance, raw=False, **kwargs):
    if not raw:
        instance._previous_probation_employee = (
            sender._base_manager.filter(pk=instance.pk)
            .values_list("converted_employee_id", flat=True)
            .first()
            if instance.pk
            else None
        )


@receiver(post_save, sender=Candidate)
def transfer_probation_plan_on_conversion(sender, instance, raw=False, **kwargs):
    if (
        not raw
        and instance.converted_employee_id_id
        and getattr(
            instance, "_previous_probation_employee", instance.converted_employee_id_id
        )
        != instance.converted_employee_id_id
    ):
        from employee.probation import copy_candidate_plan

        copy_candidate_plan(instance)
