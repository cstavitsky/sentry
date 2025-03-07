import logging

from django.conf import settings

from sentry import features
from sentry.integrations import IntegrationInstallation
from sentry.models import ExternalIssue, Organization

logger = logging.getLogger("sentry.tasks.integrations")


def should_comment_sync(
    installation: IntegrationInstallation, external_issue: ExternalIssue
) -> bool:
    organization = Organization.objects.get(id=external_issue.organization_id)
    has_issue_sync = features.has("organizations:integrations-issue-sync", organization)
    return has_issue_sync and installation.should_sync("comment")


__all__ = (
    "create_comment",
    "kick_off_status_syncs",
    "kickoff_vsts_subscription_check",
    "logger",
    "migrate_issues",
    "migrate_repo",
    "should_comment_sync",
    "sync_assignee_outbound",
    "sync_metadata",
    "sync_status_inbound",
    "sync_status_outbound",
    "update_comment",
    "vsts_subscription_check",
)

_tasks_list = (
    "create_comment",
    "github.pr_comment",
    "kick_off_status_syncs",
    "migrate_issues",
    "migrate_repo",
    "sync_assignee_outbound",
    "sync_metadata",
    "sync_status_inbound",
    "sync_status_outbound",
    "update_comment",
    "vsts.kickoff_subscription_check",
    "vsts.subscription_check",
)
settings.CELERY_IMPORTS += tuple(f"sentry.tasks.integrations.{task}" for task in _tasks_list)

from .create_comment import create_comment
from .kick_off_status_syncs import kick_off_status_syncs
from .migrate_issues import migrate_issues
from .migrate_repo import migrate_repo
from .sync_assignee_outbound import sync_assignee_outbound
from .sync_metadata import sync_metadata
from .sync_status_inbound import sync_status_inbound
from .sync_status_outbound import sync_status_outbound
from .update_comment import update_comment
from .vsts import kickoff_vsts_subscription_check, vsts_subscription_check
