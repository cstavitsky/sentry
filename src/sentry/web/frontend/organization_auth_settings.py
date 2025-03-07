from __future__ import annotations

from django import forms
from django.contrib import messages
from django.db import transaction
from django.db.models import F
from django.http import HttpResponse, HttpResponseRedirect
from django.urls import reverse
from django.utils.translation import ugettext_lazy as _
from rest_framework.request import Request

from sentry import audit_log, features, roles
from sentry.auth import manager
from sentry.auth.helper import AuthHelper
from sentry.db.postgres.roles import in_test_psql_role_override
from sentry.models import AuthProvider, Organization, OrganizationMember, User
from sentry.plugins.base import Response
from sentry.services.hybrid_cloud.auth import RpcAuthProvider
from sentry.services.hybrid_cloud.organization import RpcOrganization, organization_service
from sentry.tasks.auth import email_missing_links, email_unlink_notifications
from sentry.utils.http import absolute_uri
from sentry.web.frontend.base import ControlSiloOrganizationView

ERR_NO_SSO = _("The SSO feature is not enabled for this organization.")

OK_PROVIDER_DISABLED = _("SSO authentication has been disabled.")

OK_REMINDERS_SENT = _(
    "A reminder email has been sent to members who have not yet linked their accounts."
)


def auth_provider_settings_form(provider, auth_provider, organization, request):
    class AuthProviderSettingsForm(forms.Form):
        disabled = provider.is_partner
        require_link = forms.BooleanField(
            label=_("Require SSO"),
            help_text=_(
                "Require members use a valid linked SSO account to access this organization"
            ),
            required=False,
            disabled=disabled,
        )

        enable_scim = (
            forms.BooleanField(
                label=_("Enable SCIM"),
                help_text=_("Enable SCIM to manage Memberships and Teams via your Provider"),
                required=False,
                disabled=disabled,
            )
            if provider.can_use_scim(organization.id, request.user)
            else None
        )

        default_role = forms.ChoiceField(
            label=_("Default Role"),
            choices=roles.get_choices(),
            help_text=_(
                "The default role new members will receive when logging in for the first time."
            ),
            disabled=disabled,
        )

    initial = {
        "require_link": not auth_provider.flags.allow_unlinked,
        "default_role": organization.default_role,
    }
    if provider.can_use_scim(organization.id, request.user):
        initial["enable_scim"] = bool(auth_provider.flags.scim_enabled)

    form = AuthProviderSettingsForm(
        data=request.POST if request.POST.get("op") == "settings" else None, initial=initial
    )

    return form


class OrganizationAuthSettingsView(ControlSiloOrganizationView):
    # We restrict auth settings to org:write as it allows a non-owner to
    # escalate members to own by disabling the default role.
    required_scope = "org:write"

    def _disable_provider(self, request: Request, organization: RpcOrganization, auth_provider):
        self.create_audit_entry(
            request,
            organization=organization,
            target_object=auth_provider.id,
            event=audit_log.get_event_id("SSO_DISABLE"),
            data=auth_provider.get_audit_log_data(),
        )

        # This is safe -- we're not syncing flags to the org member mapping table.
        with in_test_psql_role_override("postgres"):
            OrganizationMember.objects.filter(organization_id=organization.id).update(
                flags=F("flags")
                .bitand(~OrganizationMember.flags["sso:linked"])
                .bitand(~OrganizationMember.flags["sso:invalid"])
            )

        user_ids = OrganizationMember.objects.filter(organization_id=organization.id).values(
            "user_id"
        )
        User.objects.filter(id__in=user_ids).update(is_managed=False)

        email_unlink_notifications.delay(organization.id, request.user.id, auth_provider.provider)

        if auth_provider.flags.scim_enabled:
            auth_provider.disable_scim(request.user)
        auth_provider.delete()

    def handle_existing_provider(
        self, request: Request, organization: RpcOrganization, auth_provider
    ):
        provider = auth_provider.get_provider()

        if request.method == "POST":
            if provider.is_partner:
                return HttpResponse("Can't disable partner authentication provider", status=405)

            op = request.POST.get("op")
            if op == "disable":
                self._disable_provider(request, organization, auth_provider)

                messages.add_message(request, messages.SUCCESS, OK_PROVIDER_DISABLED)

                next_uri = f"/settings/{organization.slug}/auth/"
                return self.redirect(next_uri)
            elif op == "reinvite":
                email_missing_links.delay(organization.id, request.user.id, provider.key)

                messages.add_message(request, messages.SUCCESS, OK_REMINDERS_SENT)

                next_uri = reverse(
                    "sentry-organization-auth-provider-settings", args=[organization.slug]
                )
                return self.redirect(next_uri)

        form = auth_provider_settings_form(provider, auth_provider, organization, request)

        if form.is_valid():
            auth_provider.flags.allow_unlinked = not form.cleaned_data["require_link"]

            form_scim_enabled = form.cleaned_data.get("enable_scim", False)
            if auth_provider.flags.scim_enabled != form_scim_enabled:
                if form_scim_enabled:
                    auth_provider.enable_scim(request.user)
                else:
                    auth_provider.disable_scim(request.user)

            auth_provider.save()

            organization = organization_service.update_default_role(
                organization_id=organization.id, default_role=form.cleaned_data["default_role"]
            )

            if form.initial != form.cleaned_data:
                changed_data = {}
                for key, value in form.cleaned_data.items():
                    if form.initial.get(key) != value:
                        changed_data[key] = f"to {value}"

                self.create_audit_entry(
                    request,
                    organization=organization,
                    target_object=auth_provider.id,
                    event=audit_log.get_event_id("SSO_EDIT"),
                    data=changed_data,
                )

        view = provider.get_configure_view()
        response = view(request, organization, auth_provider)
        if isinstance(response, HttpResponse):
            return response
        elif isinstance(response, Response):
            response = response.render(
                request,
                {
                    "auth_provider": auth_provider,
                    "organization": organization,
                    "provider": provider,
                },
            )

        pending_links_count = OrganizationMember.objects.filter(
            organization_id=organization.id,
            flags=F("flags").bitand(~OrganizationMember.flags["sso:linked"]),
        ).count()

        context = {
            "form": form,
            "pending_links_count": pending_links_count,
            "login_url": organization.absolute_url(Organization.get_url(organization.slug)),
            "settings_url": organization.absolute_url(
                reverse("sentry-organization-settings", args=[organization.slug])
            ),
            "auth_provider": auth_provider,
            "provider_name": provider.name,
            "scim_api_token": auth_provider.get_scim_token(),
            "scim_url": get_scim_url(auth_provider, organization),
            "content": response,
            "disabled": provider.is_partner,
        }

        return self.respond("sentry/organization-auth-provider-settings.html", context)

    @transaction.atomic
    def handle(self, request: Request, organization: RpcOrganization) -> HttpResponse:
        try:
            auth_provider = AuthProvider.objects.get(organization_id=organization.id)
        except AuthProvider.DoesNotExist:
            pass
        else:
            # if the org has SSO set up already, allow them to modify the existing provider
            # regardless if the feature flag is set up. This allows orgs who might no longer
            # have the SSO feature to be able to turn it off
            return self.handle_existing_provider(
                request=request, organization=organization, auth_provider=auth_provider
            )

        if request.method == "POST":
            provider_key = request.POST.get("provider")
            if not manager.exists(provider_key):
                raise ValueError(f"Provider not found: {provider_key}")

            helper = AuthHelper(
                request=request,
                organization=organization,
                provider_key=provider_key,
                flow=AuthHelper.FLOW_SETUP_PROVIDER,
            )

            feature = helper.provider.required_feature
            if feature and not features.has(feature, organization, actor=request.user):
                return HttpResponse("Provider is not enabled", status=401)

            if request.POST.get("init"):
                helper.initialize()

            if not helper.is_valid():
                return helper.error("Something unexpected happened during authentication.")

            # render first time setup view
            return helper.current_step()

        # Otherwise user is in bad state since frontend/react should handle this case
        return HttpResponseRedirect(Organization.get_url(organization.slug))


def get_scim_url(
    auth_provider: AuthProvider | RpcAuthProvider, organization: Organization | RpcOrganization
) -> str | None:
    if auth_provider.flags.scim_enabled:
        # the SCIM protocol doesn't use trailing slashes in URLs
        return absolute_uri(f"api/0/organizations/{organization.slug}/scim/v2")

    else:
        return None
