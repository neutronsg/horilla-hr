"""Serialize balance mutations before reading balances or request status."""
from contextlib import contextmanager, ExitStack
from functools import wraps
from inspect import signature

from django.db import transaction, router
from django.db.models import QuerySet


@contextmanager
def employee_leave_lock(employee):
    from employee.models import Employee
    employee_id = getattr(employee, "pk", employee)
    with transaction.atomic():
        if employee_id:
            # One stable lock also covers missing/new assignments and shared sick limits.
            QuerySet(model=Employee, using=router.db_for_write(Employee)).select_for_update().get(pk=employee_id)
        yield


def locked_employee_sync(func):
    @wraps(func)
    def wrapped(employee, *args, **kwargs):
        with employee_leave_lock(employee):
            return func(employee, *args, **kwargs)
    return wrapped


def locked_leave_operation(model_name=None, id_parameter="id"):
    """Keep existing access decorators outside this transaction decorator.

    Resolve an existing object with its company-scoped manager, then refetch it
    inside the operation after the employee lock. POST forms lock before validation.
    """
    def decorate(func):
        sig = signature(func)
        @wraps(func)
        def wrapped(*args, **kwargs):
            bound = sig.bind(*args, **kwargs)
            request = bound.arguments.get("request")
            if request is None:
                request = bound.arguments["self"].request
            from leave import models
            employee_id = None
            if model_name:
                identifier = bound.arguments.get(id_parameter)
                if identifier is None and "self" in bound.arguments:
                    identifier = bound.arguments["self"].kwargs.get(id_parameter)
                obj = getattr(models, model_name).objects.filter(pk=identifier).first()
                employee_id = obj.employee_id_id if obj else None
            else:
                data = getattr(request, "data", request.POST)
                employee_id = data.get("employee_id") or bound.arguments.get("emp_id")
                if not employee_id:
                    employee = getattr(request.user, "employee_get", None)
                    employee_id = getattr(employee, "pk", None)
            if employee_id and not str(employee_id).isdigit():
                employee_id = None
            if employee_id:
                from employee.models import Employee
                if not Employee._base_manager.filter(pk=employee_id).exists():
                    employee_id = None
            form = bound.arguments.get("form")
            instance = getattr(form, "instance", None)
            old_employee = getattr(instance, "employee_id_id", None)
            if instance is not None and instance.pk:
                # A validated ModelForm may already contain the new employee.
                old_employee = type(instance).objects.filter(pk=instance.pk).values_list(
                    "employee_id_id", flat=True).first()
            ids = sorted({int(i) for i in (employee_id, old_employee) if i})
            with ExitStack() as locks:
                for identifier in ids:
                    locks.enter_context(employee_leave_lock(identifier))
                if instance is not None and instance.pk:
                    # Form validation may have loaded the request before the lock.
                    fresh = type(instance).objects.get(pk=instance.pk)
                    if fresh._meta.model_name != "leaverequest":
                        # Preserve values already applied by a bound ModelForm;
                        # refresh unrelated fields from the locked record.
                        for field in fresh._meta.concrete_fields:
                            if field.name in form.fields:
                                setattr(fresh, field.attname, getattr(instance, field.attname))
                    form.instance = fresh
                    view = bound.arguments.get("self")
                    if view is not None and getattr(view, "form", None):
                        view.form.instance = fresh
                return func(*args, **kwargs)
        return wrapped
    return decorate


def locked_bulk_balances(func):
    @wraps(func)
    def wrapped(self, request, *args, **kwargs):
        import ast
        from leave.models import AvailableLeave
        values = request.POST.getlist("instance_ids")
        if values and values[0].startswith("["):
            try:
                values = ast.literal_eval(values[0])
            except (ValueError, SyntaxError):
                values = []
        ids = [int(value) for value in values if str(value).isdigit()]
        employee_ids = sorted(set(AvailableLeave.objects.filter(pk__in=ids)
                                  .values_list("employee_id_id", flat=True)))
        with ExitStack() as locks:
            for employee_id in employee_ids:
                locks.enter_context(employee_leave_lock(employee_id))
            return func(self, request, *args, **kwargs)
    return wrapped
