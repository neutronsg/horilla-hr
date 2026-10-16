"""Compatibility classes for the shared Company documents publishing service."""

from django.views import View

from employee.company_documents import legacy_edit, legacy_nav


class PolicyFormView(View):
    def get(self, request, pk=None):
        return legacy_edit(request, pk=pk)

    def post(self, request, pk=None):
        return legacy_edit(request, pk=pk)


class PoliciesNav(View):
    def get(self, request):
        return legacy_nav(request)
