from __future__ import absolute_import, print_function

from django.conf.urls import patterns, url

from .webhook import GitHubIntegrationsWebhookEndpoint
from .search import GitHubSearchEndpoint

urlpatterns = patterns(
    "",
    url(r"^webhook/$", GitHubIntegrationsWebhookEndpoint.as_view()),
    url(
        r"^search/(?P<organization_slug>[^\/]+)/(?P<integration_id>\d+)/$",
        GitHubSearchEndpoint.as_view(),
        name="sentry-extensions-github-search",
    ),
)
