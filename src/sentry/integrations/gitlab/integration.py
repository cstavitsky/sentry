from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse

from django import forms
from django.http import HttpResponse
from django.utils.translation import ugettext_lazy as _
from rest_framework.request import Request

from sentry.identity.gitlab import get_oauth_data, get_user_info
from sentry.identity.gitlab.provider import GitlabIdentityProvider
from sentry.identity.pipeline import IdentityProviderPipeline
from sentry.integrations import (
    FeatureDescription,
    IntegrationFeatures,
    IntegrationInstallation,
    IntegrationMetadata,
    IntegrationProvider,
)
from sentry.integrations.mixins import RepositoryMixin
from sentry.integrations.mixins.commit_context import CommitContextMixin
from sentry.models import Repository
from sentry.pipeline import NestedPipelineView, PipelineView
from sentry.shared_integrations.exceptions import ApiError, IntegrationError
from sentry.utils.hashlib import sha1_text
from sentry.utils.http import absolute_uri
from sentry.web.helpers import render_to_response

from .client import GitLabProxyApiClient, GitlabProxySetupClient
from .issues import GitlabIssueBasic
from .repository import GitlabRepositoryProvider

DESCRIPTION = """
Connect your Sentry organization to an organization in your GitLab instance or gitlab.com, enabling the following features:
"""

FEATURES = [
    FeatureDescription(
        """
        Track commits and releases (learn more
        [here](https://docs.sentry.io/learn/releases/))
        """,
        IntegrationFeatures.COMMITS,
    ),
    FeatureDescription(
        """
        Resolve Sentry issues via GitLab commits and merge requests by
        including `Fixes PROJ-ID` in the message
        """,
        IntegrationFeatures.COMMITS,
    ),
    FeatureDescription(
        """
        Create GitLab issues from Sentry
        """,
        IntegrationFeatures.ISSUE_BASIC,
    ),
    FeatureDescription(
        """
        Link Sentry issues to existing GitLab issues
        """,
        IntegrationFeatures.ISSUE_BASIC,
    ),
    FeatureDescription(
        """
        Link your Sentry stack traces back to your GitLab source code with stack
        trace linking.
        """,
        IntegrationFeatures.STACKTRACE_LINK,
    ),
    FeatureDescription(
        """
        Import your GitLab [CODEOWNERS file](https://docs.sentry.io/product/integrations/source-code-mgmt/gitlab/#code-owners) and use it alongside your ownership rules to assign Sentry issues.
        """,
        IntegrationFeatures.CODEOWNERS,
    ),
]

metadata = IntegrationMetadata(
    description=DESCRIPTION.strip(),
    features=FEATURES,
    author="The Sentry Team",
    noun=_("Installation"),
    issue_url="https://github.com/getsentry/sentry/issues/new?assignees=&labels=Component:%20Integrations&template=bug.yml&title=GitLab%20Integration%20Problem",
    source_url="https://github.com/getsentry/sentry/tree/master/src/sentry/integrations/gitlab",
    aspects={},
)


class GitlabIntegration(
    IntegrationInstallation, GitlabIssueBasic, RepositoryMixin, CommitContextMixin
):
    repo_search = True
    codeowners_locations = ["CODEOWNERS", ".gitlab/CODEOWNERS", "docs/CODEOWNERS"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.default_identity = None

    def get_group_id(self):
        return self.model.metadata["group_id"]

    def get_client(self):
        if self.default_identity is None:
            self.default_identity = self.get_default_identity()

        return GitLabProxyApiClient(self)

    def get_repositories(self, query=None):
        # Note: gitlab projects are the same things as repos everywhere else
        group = self.get_group_id()
        resp = self.get_client().search_projects(group, query)
        return [{"identifier": repo["id"], "name": repo["name_with_namespace"]} for repo in resp]

    def format_source_url(self, repo: Repository, filepath: str, branch: str) -> str:
        base_url = self.model.metadata["base_url"]
        repo_name = repo.config["path"]

        # Must format the url ourselves since `check_file` is a head request
        # "https://gitlab.com/gitlab-org/gitlab/blob/master/README.md"
        return f"{base_url}/{repo_name}/blob/{branch}/{filepath}"

    def search_projects(self, query):
        client = self.get_client()
        group_id = self.get_group_id()
        return client.search_projects(group_id, query)

    def search_issues(self, project_id, query, iids):
        client = self.get_client()
        return client.search_project_issues(project_id, query, iids)

    def error_message_from_json(self, data):
        """
        Extract error messages from gitlab API errors.
        Generic errors come in the `error` key while validation errors
        are generally in `message`.

        See https://docs.gitlab.com/ee/api/#data-validation-and-error-reporting
        """
        if "message" in data:
            return data["message"]
        if "error" in data:
            return data["error"]

    def get_commit_context(
        self, repo: Repository, filepath: str, ref: str, event_frame: Mapping[str, Any]
    ) -> Mapping[str, str] | None:
        """
        Returns the latest commit that altered the line from the event frame if it exists.
        """
        lineno = event_frame.get("lineno", 0)
        if not lineno:
            return None
        try:
            blame_range: Sequence[Mapping[str, Any]] | None = self.get_blame_for_file(
                repo, filepath, ref, lineno
            )
            if blame_range is None:
                return None
        except ApiError as e:
            raise e

        date_format_expected = "%Y-%m-%dT%H:%M:%S.%f%z"
        try:
            commit = max(
                blame_range,
                key=lambda blame: datetime.strptime(
                    blame.get("commit", {}).get("committed_date"), date_format_expected
                ),
            )
        except (ValueError, IndexError):
            return None

        commitInfo = commit.get("commit")
        if not commitInfo:
            return None
        else:
            committed_date = "{}Z".format(
                datetime.strptime(commitInfo.get("committed_date"), date_format_expected)
                .astimezone(timezone.utc)
                .strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
            )
            return {
                "commitId": commitInfo.get("id"),
                "committedDate": committed_date,
                "commitMessage": commitInfo.get("message"),
                "commitAuthorName": commitInfo.get("committer_name"),
                "commitAuthorEmail": commitInfo.get("committer_email"),
            }


class InstallationForm(forms.Form):
    url = forms.CharField(
        label=_("GitLab URL"),
        help_text=_(
            "The base URL for your GitLab instance, including the host and protocol. "
            "Do not include the group path."
            "<br>"
            "If using gitlab.com, enter https://gitlab.com/"
        ),
        widget=forms.TextInput(attrs={"placeholder": "https://gitlab.example.com"}),
    )
    group = forms.CharField(
        label=_("GitLab Group Path"),
        help_text=_(
            "This can be found in the URL of your group's GitLab page."
            "<br>"
            "For example, if your group URL is "
            "https://gitlab.com/my-group/my-subgroup, enter `my-group/my-subgroup`."
            "<br>"
            "If you are trying to integrate an entire self-managed GitLab instance, "
            "leave this empty. Doing so will also allow you to select projects in "
            "all group and user namespaces (such as users' personal repositories and forks)."
        ),
        widget=forms.TextInput(attrs={"placeholder": _("my-group/my-subgroup")}),
        required=False,
    )
    include_subgroups = forms.BooleanField(
        label=_("Include Subgroups"),
        help_text=_(
            "Include projects in subgroups of the GitLab group."
            "<br>"
            "Not applicable when integrating an entire GitLab instance. "
            "All groups are included for instance-level integrations."
        ),
        widget=forms.CheckboxInput(),
        required=False,
        initial=False,
    )
    verify_ssl = forms.BooleanField(
        label=_("Verify SSL"),
        help_text=_(
            "By default, we verify SSL certificates "
            "when delivering payloads to your GitLab instance, "
            "and request GitLab to verify SSL when it delivers "
            "webhooks to Sentry."
        ),
        widget=forms.CheckboxInput(),
        required=False,
        initial=True,
    )
    client_id = forms.CharField(
        label=_("GitLab Application ID"),
        widget=forms.TextInput(
            attrs={
                "placeholder": _("5832fc6e14300a0d962240a8144466eef4ee93ef0d218477e55f11cf12fc3737")
            }
        ),
    )
    client_secret = forms.CharField(
        label=_("GitLab Application Secret"),
        widget=forms.TextInput(attrs={"placeholder": _("XXXXXXXXXXXXXXXXXXXXXXXXXXX")}),
    )

    def clean_url(self):
        """Strip off trailing / as they cause invalid URLs downstream"""
        return self.cleaned_data["url"].rstrip("/")


class InstallationConfigView(PipelineView):
    def dispatch(self, request: Request, pipeline) -> HttpResponse:
        if "goback" in request.GET:
            pipeline.state.step_index = 0
            return pipeline.current_step()

        if request.method == "POST":
            form = InstallationForm(request.POST)
            if form.is_valid():
                form_data = form.cleaned_data

                pipeline.bind_state("installation_data", form_data)

                pipeline.bind_state(
                    "oauth_config_information",
                    {
                        "access_token_url": "{}/oauth/token".format(form_data.get("url")),
                        "authorize_url": "{}/oauth/authorize".format(form_data.get("url")),
                        "client_id": form_data.get("client_id"),
                        "client_secret": form_data.get("client_secret"),
                        "verify_ssl": form_data.get("verify_ssl"),
                    },
                )
                pipeline.get_logger().info(
                    "gitlab.setup.installation-config-view.success",
                    extra={
                        "base_url": form_data.get("url"),
                        "client_id": form_data.get("client_id"),
                        "verify_ssl": form_data.get("verify_ssl"),
                    },
                )
                return pipeline.next_step()
        else:
            form = InstallationForm()

        return render_to_response(
            template="sentry/integrations/gitlab-config.html",
            context={"form": form},
            request=request,
        )


class InstallationGuideView(PipelineView):
    def dispatch(self, request: Request, pipeline) -> HttpResponse:
        if "completed_installation_guide" in request.GET:
            return pipeline.next_step()
        return render_to_response(
            template="sentry/integrations/gitlab-config.html",
            context={
                "next_url": f'{absolute_uri("/extensions/gitlab/setup/")}?completed_installation_guide',
                "setup_values": [
                    {"label": "Name", "value": "Sentry"},
                    {"label": "Redirect URI", "value": absolute_uri("/extensions/gitlab/setup/")},
                    {"label": "Scopes", "value": "api"},
                ],
            },
            request=request,
        )


class GitlabIntegrationProvider(IntegrationProvider):
    key = "gitlab"
    name = "GitLab"
    metadata = metadata
    integration_cls = GitlabIntegration

    needs_default_identity = True

    features = frozenset(
        [
            IntegrationFeatures.ISSUE_BASIC,
            IntegrationFeatures.COMMITS,
            IntegrationFeatures.STACKTRACE_LINK,
            IntegrationFeatures.CODEOWNERS,
        ]
    )

    setup_dialog_config = {"width": 1030, "height": 1000}

    def _make_identity_pipeline_view(self):
        """
        Make the nested identity provider view. It is important that this view is
        not constructed until we reach this step and the
        ``oauth_config_information`` is available in the pipeline state. This
        method should be late bound into the pipeline vies.
        """
        identity_pipeline_config = dict(
            oauth_scopes=sorted(GitlabIdentityProvider.oauth_scopes),
            redirect_url=absolute_uri("/extensions/gitlab/setup/"),
            **self.pipeline.fetch_state("oauth_config_information"),
        )

        return NestedPipelineView(
            bind_key="identity",
            provider_key="gitlab",
            pipeline_cls=IdentityProviderPipeline,
            config=identity_pipeline_config,
        )

    def get_group_info(self, access_token, installation_data):
        client = GitlabProxySetupClient(
            base_url=installation_data["url"],
            access_token=access_token,
            verify_ssl=installation_data["verify_ssl"],
        )
        try:
            resp = client.get_group(installation_data["group"])
            return resp.json
        except ApiError as e:
            self.get_logger().info(
                "gitlab.installation.get-group-info-failure",
                extra={
                    "base_url": installation_data["url"],
                    "verify_ssl": installation_data["verify_ssl"],
                    "group": installation_data["group"],
                    "include_subgroups": installation_data["include_subgroups"],
                    "error_message": str(e),
                    "error_status": e.code,
                },
            )
            raise IntegrationError("The requested GitLab group could not be found.")

    def get_pipeline_views(self):
        return [
            InstallationGuideView(),
            InstallationConfigView(),
            lambda: self._make_identity_pipeline_view(),
        ]

    def build_integration(self, state):
        data = state["identity"]["data"]

        # Gitlab requires the client_id and client_secret for refreshing the access tokens
        oauth_config = state.get("oauth_config_information", {})
        oauth_data = {
            **get_oauth_data(data),
            "client_id": oauth_config.get("client_id"),
            "client_secret": oauth_config.get("client_secret"),
        }

        user = get_user_info(data["access_token"], state["installation_data"])
        scopes = sorted(GitlabIdentityProvider.oauth_scopes)
        base_url = state["installation_data"]["url"]

        if state["installation_data"].get("group"):
            group = self.get_group_info(data["access_token"], state["installation_data"])
            include_subgroups = state["installation_data"]["include_subgroups"]
        else:
            group = {}
            include_subgroups = False

        hostname = urlparse(base_url).netloc
        verify_ssl = state["installation_data"]["verify_ssl"]

        # Generate a hash to prevent stray hooks from being accepted
        # use a consistent hash so that reinstalls/shared integrations don't
        # rotate secrets.
        secret = sha1_text("".join([hostname, state["installation_data"]["client_id"]]))

        integration = {
            "name": group.get("full_name", hostname),
            # Splice the gitlab host and project together to
            # act as unique link between a gitlab instance, group + sentry.
            # This value is embedded then in the webhook token that we
            # give to gitlab to allow us to find the integration a hook came
            # from.
            "external_id": "{}:{}".format(hostname, group.get("id", "_instance_")),
            "metadata": {
                "icon": group.get("avatar_url"),
                "instance": hostname,
                "domain_name": "{}/{}".format(hostname, group.get("full_path", "")).rstrip("/"),
                "scopes": scopes,
                "verify_ssl": verify_ssl,
                "base_url": base_url,
                "webhook_secret": secret.hexdigest(),
                "group_id": group.get("id"),
                "include_subgroups": include_subgroups,
            },
            "user_identity": {
                "type": "gitlab",
                "external_id": "{}:{}".format(hostname, user["id"]),
                "scopes": scopes,
                "data": oauth_data,
            },
        }
        return integration

    def setup(self):
        from sentry.plugins.base import bindings

        bindings.add(
            "integration-repository.provider", GitlabRepositoryProvider, id="integrations:gitlab"
        )
