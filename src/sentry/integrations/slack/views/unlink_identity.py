from django.core.signing import BadSignature, SignatureExpired
from django.db import IntegrityError
from django.http import Http404, HttpResponse
from rest_framework.request import Request

from sentry.integrations.utils import get_identity_or_404
from sentry.models import Identity
from sentry.types.integrations import ExternalProviders
from sentry.utils.signing import unsign
from sentry.web.decorators import transaction_start
from sentry.web.frontend.base import BaseView
from sentry.web.helpers import render_to_response

from ..utils import logger, send_slack_response
from . import build_linking_url as base_build_linking_url
from . import never_cache

SUCCESS_UNLINKED_MESSAGE = "Your Slack identity has been unlinked from your Sentry account."


def build_unlinking_url(
    integration_id: int, slack_id: str, channel_id: str, response_url: str
) -> str:
    return base_build_linking_url(
        "sentry-integration-slack-unlink-identity",
        integration_id=integration_id,
        slack_id=slack_id,
        channel_id=channel_id,
        response_url=response_url,
    )


class SlackUnlinkIdentityView(BaseView):
    """
    Django view for unlinking user from slack account. Deletes from Identity table.
    """

    @transaction_start("SlackUnlinkIdentityView")
    @never_cache
    def handle(self, request: Request, signed_params: str) -> HttpResponse:
        try:
            params = unsign(signed_params)
        except (SignatureExpired, BadSignature):
            return render_to_response(
                "sentry/integrations/slack/expired-link.html",
                request=request,
            )

        organization, integration, idp = get_identity_or_404(
            ExternalProviders.SLACK,
            request.user,
            integration_id=params["integration_id"],
        )

        if request.method != "POST":
            return render_to_response(
                "sentry/auth-unlink-identity.html",
                request=request,
                context={"organization": organization, "provider": integration.get_provider()},
            )

        try:
            Identity.objects.filter(idp_id=idp.id, external_id=params["slack_id"]).delete()
        except IntegrityError:
            logger.exception("slack.unlink.integrity-error")
            raise Http404

        send_slack_response(integration, SUCCESS_UNLINKED_MESSAGE, params, command="unlink")

        return render_to_response(
            "sentry/integrations/slack/unlinked.html",
            request=request,
            context={"channel_id": params["channel_id"], "team_id": integration.external_id},
        )
