from datetime import datetime, timedelta
from unittest.mock import Mock, patch

import pytest
from django.http import QueryDict

from sentry.api.helpers.group_index import update_groups, validate_search_filter_permissions
from sentry.api.helpers.group_index.update import (
    handle_assigned_to,
    handle_has_seen,
    handle_is_bookmarked,
    handle_is_public,
    handle_is_subscribed,
)
from sentry.api.helpers.group_index.validators import ValidationError
from sentry.api.issue_search import parse_search_query
from sentry.models import (
    Activity,
    GroupBookmark,
    GroupInbox,
    GroupInboxReason,
    GroupSeen,
    GroupShare,
    GroupSnooze,
    GroupStatus,
    GroupSubscription,
    add_group_to_inbox,
)
from sentry.models.actor import ActorTuple
from sentry.models.groupassignee import GroupAssignee
from sentry.testutils import TestCase
from sentry.testutils.helpers.features import with_feature
from sentry.types.activity import ActivityType
from sentry.types.group import GroupSubStatus


class ValidateSearchFilterPermissionsTest(TestCase):
    def run_test(self, query: str) -> None:
        validate_search_filter_permissions(self.organization, parse_search_query(query), self.user)

    def assert_analytics_recorded(self, mock_record: Mock) -> None:
        mock_record.assert_called_with(
            "advanced_search.feature_gated",
            user_id=self.user.id,
            default_user_id=self.user.id,
            organization_id=self.organization.id,
        )

    @patch("sentry.analytics.record")
    def test_negative(self, mock_record: Mock) -> None:
        query = "!has:user"
        with self.feature({"organizations:advanced-search": False}), pytest.raises(
            ValidationError, match=".*negative search.*"
        ):
            self.run_test(query)

        self.run_test(query)
        self.assert_analytics_recorded(mock_record)

        query = "!something:123"
        with self.feature({"organizations:advanced-search": False}), pytest.raises(
            ValidationError, match=".*negative search.*"
        ):
            self.run_test(query)

        self.run_test(query)
        self.assert_analytics_recorded(mock_record)

    @patch("sentry.analytics.record")
    def test_wildcard(self, mock_record: Mock) -> None:
        query = "abc:hello*"
        with self.feature({"organizations:advanced-search": False}), pytest.raises(
            ValidationError, match=".*wildcard search.*"
        ):
            self.run_test(query)

        self.run_test(query)
        self.assert_analytics_recorded(mock_record)

        query = "raw * search"
        with self.feature({"organizations:advanced-search": False}), pytest.raises(
            ValidationError, match=".*wildcard search.*"
        ):
            self.run_test(query)

        self.run_test(query)
        self.assert_analytics_recorded(mock_record)


class UpdateGroupsTest(TestCase):
    @patch("sentry.signals.issue_unresolved.send_robust")
    @patch("sentry.signals.issue_ignored.send_robust")
    def test_unresolving_resolved_group(self, send_robust: Mock, send_unresolved: Mock) -> None:
        resolved_group = self.create_group(status=GroupStatus.RESOLVED)
        assert resolved_group.status == GroupStatus.RESOLVED

        request = self.make_request(user=self.user, method="GET")
        request.user = self.user
        request.data = {"status": "unresolved"}
        request.GET = QueryDict(query_string=f"id={resolved_group.id}")

        search_fn = Mock()
        update_groups(
            request, request.GET.getlist("id"), [self.project], self.organization.id, search_fn
        )

        resolved_group.refresh_from_db()

        assert resolved_group.status == GroupStatus.UNRESOLVED
        assert not send_robust.called
        assert send_unresolved.called

    @patch("sentry.signals.issue_resolved.send_robust")
    def test_resolving_unresolved_group(self, send_robust: Mock) -> None:
        unresolved_group = self.create_group(status=GroupStatus.UNRESOLVED)
        add_group_to_inbox(unresolved_group, GroupInboxReason.NEW)
        assert unresolved_group.status == GroupStatus.UNRESOLVED

        request = self.make_request(user=self.user, method="GET")
        request.user = self.user
        request.data = {"status": "resolved"}
        request.GET = QueryDict(query_string=f"id={unresolved_group.id}")

        search_fn = Mock()
        update_groups(
            request, request.GET.getlist("id"), [self.project], self.organization.id, search_fn
        )

        unresolved_group.refresh_from_db()

        assert unresolved_group.status == GroupStatus.RESOLVED
        assert not GroupInbox.objects.filter(group=unresolved_group).exists()
        assert send_robust.called

    @patch("sentry.signals.issue_ignored.send_robust")
    def test_ignoring_group_archived_forever(self, send_robust: Mock) -> None:
        group = self.create_group()
        add_group_to_inbox(group, GroupInboxReason.NEW)

        request = self.make_request(user=self.user, method="GET")
        request.user = self.user
        request.data = {"status": "ignored", "substatus": "archived_forever"}
        request.GET = QueryDict(query_string=f"id={group.id}")

        search_fn = Mock()
        update_groups(
            request, request.GET.getlist("id"), [self.project], self.organization.id, search_fn
        )

        group.refresh_from_db()

        assert group.status == GroupStatus.IGNORED
        assert group.substatus == GroupSubStatus.FOREVER
        assert send_robust.called
        assert not GroupInbox.objects.filter(group=group).exists()

    @patch("sentry.signals.issue_ignored.send_robust")
    def test_ignoring_group_archived_until_condition_met(self, send_robust: Mock) -> None:
        group = self.create_group()
        add_group_to_inbox(group, GroupInboxReason.NEW)

        request = self.make_request(user=self.user, method="GET")
        request.user = self.user
        request.data = {
            "status": "ignored",
            "substatus": "archived_until_condition_met",
            "statusDetails": {"ignoreDuration": 1},
        }
        request.GET = QueryDict(query_string=f"id={group.id}")

        search_fn = Mock()
        update_groups(
            request, request.GET.getlist("id"), [self.project], self.organization.id, search_fn
        )

        group.refresh_from_db()

        assert group.status == GroupStatus.IGNORED
        assert group.substatus == GroupSubStatus.UNTIL_CONDITION_MET
        assert send_robust.called
        assert not GroupInbox.objects.filter(group=group).exists()
        assert GroupSnooze.objects.filter(group=group).exists()

    @patch("sentry.signals.issue_unignored.send_robust")
    def test_unignoring_group(self, send_robust: Mock) -> None:
        for data in [
            {
                "group": self.create_group(
                    status=GroupStatus.IGNORED, first_seen=datetime.now() - timedelta(days=4)
                ),
                "request_data": {"status": "unresolved"},
                "expected_substatus": GroupSubStatus.ONGOING,
            },
            {
                "group": self.create_group(
                    status=GroupStatus.IGNORED, first_seen=datetime.now() - timedelta(days=4)
                ),
                "request_data": {"status": "unresolved", "substatus": "ongoing"},
                "expected_substatus": GroupSubStatus.ONGOING,
            },
            {
                "group": self.create_group(status=GroupStatus.IGNORED, first_seen=datetime.now()),
                "request_data": {"status": "unresolved"},
                "expected_substatus": GroupSubStatus.NEW,
            },
        ]:
            group = data["group"]
            request = self.make_request(user=self.user, method="GET")
            request.user = self.user
            request.data = data["request_data"]
            request.GET = QueryDict(query_string=f"id={group.id}")

            update_groups(
                request, request.GET.getlist("id"), [self.project], self.organization.id, Mock()
            )

            group.refresh_from_db()

            assert group.status == GroupStatus.UNRESOLVED
            assert group.substatus == data["expected_substatus"]
            assert send_robust.called

    @patch("sentry.signals.issue_mark_reviewed.send_robust")
    def test_mark_reviewed_group(self, send_robust: Mock) -> None:
        group = self.create_group()
        add_group_to_inbox(group, GroupInboxReason.NEW)

        request = self.make_request(user=self.user, method="GET")
        request.user = self.user
        request.data = {"inbox": False}
        request.GET = QueryDict(query_string=f"id={group.id}")

        search_fn = Mock()
        update_groups(
            request, request.GET.getlist("id"), [self.project], self.organization.id, search_fn
        )

        group.refresh_from_db()

        assert not GroupInbox.objects.filter(group=group).exists()
        assert send_robust.called

    @with_feature("organizations:escalating-issues")
    @patch("sentry.signals.issue_ignored.send_robust")
    def test_ignore_with_substatus_archived_until_escalating(self, send_robust: Mock) -> None:
        group = self.create_group()
        add_group_to_inbox(group, GroupInboxReason.NEW)

        request = self.make_request(user=self.user, method="GET")
        request.user = self.user
        request.data = {"status": "ignored", "substatus": "archived_until_escalating"}
        request.GET = QueryDict(query_string=f"id={group.id}")

        search_fn = Mock()
        update_groups(
            request, request.GET.getlist("id"), [self.project], self.organization.id, search_fn
        )

        group.refresh_from_db()

        assert group.status == GroupStatus.IGNORED
        assert group.substatus == GroupSubStatus.UNTIL_ESCALATING
        assert send_robust.called
        assert not GroupInbox.objects.filter(group=group).exists()


class TestHandleIsSubscribed(TestCase):
    def setUp(self) -> None:
        self.group = self.create_group()
        self.group_list = [self.group]
        self.project_lookup = {self.group.project_id: self.group.project}

    def test_is_subscribed(self) -> None:
        resp = handle_is_subscribed(True, self.group_list, self.project_lookup, self.user)

        assert GroupSubscription.objects.filter(group=self.group, user_id=self.user.id).exists()
        assert resp["reason"] == "unknown"

    def test_is_subscribed_updates(self) -> None:
        GroupSubscription.objects.create(
            group=self.group, project=self.group.project, user_id=self.user.id, is_active=False
        )

        resp = handle_is_subscribed(True, self.group_list, self.project_lookup, self.user)

        subscription = GroupSubscription.objects.filter(group=self.group, user_id=self.user.id)
        assert subscription.exists()
        assert subscription.first().is_active
        assert resp["reason"] == "unknown"


class TestHandleIsBookmarked(TestCase):
    def setUp(self) -> None:
        self.group = self.create_group()
        self.group_list = [self.group]
        self.group_ids = [self.group]
        self.project_lookup = {self.group.project_id: self.group.project}

    def test_is_bookmarked(self) -> None:
        handle_is_bookmarked(True, self.group_list, self.group_ids, self.project_lookup, self.user)

        assert GroupBookmark.objects.filter(group=self.group, user_id=self.user.id).exists()

    def test_not_is_bookmarked(self) -> None:
        GroupBookmark.objects.create(
            group=self.group, user_id=self.user.id, project_id=self.group.project_id
        )

        handle_is_bookmarked(False, self.group_list, self.group_ids, self.project_lookup, self.user)

        assert not GroupBookmark.objects.filter(group=self.group, user_id=self.user.id).exists()


class TestHandleHasSeen(TestCase):
    def setUp(self) -> None:
        self.group = self.create_group()
        self.group_list = [self.group]
        self.group_ids = [self.group]
        self.project_lookup = {self.group.project_id: self.group.project}

    def test_has_seen(self) -> None:
        handle_has_seen(
            True, self.group_list, self.group_ids, self.project_lookup, [self.project], self.user
        )

        assert GroupSeen.objects.filter(group=self.group, user_id=self.user.id).exists()

    def test_not_has_seen(self) -> None:
        GroupSeen.objects.create(
            group=self.group, user_id=self.user.id, project_id=self.group.project_id
        )

        handle_has_seen(
            False, self.group_list, self.group_ids, self.project_lookup, [self.project], self.user
        )

        assert not GroupSeen.objects.filter(group=self.group, user_id=self.user.id).exists()


class TestHandleIsPublic(TestCase):
    def setUp(self) -> None:
        self.group = self.create_group()
        self.group_list = [self.group]
        self.project_lookup = {self.group.project_id: self.group.project}

    def test_is_public(self) -> None:
        share_id = handle_is_public(True, self.group_list, self.project_lookup, self.user)

        new_share = GroupShare.objects.get(group=self.group)
        assert Activity.objects.filter(
            group=self.group, type=ActivityType.SET_PUBLIC.value
        ).exists()
        assert share_id == new_share.uuid

    def test_is_public_existing_shares(self) -> None:
        share = GroupShare.objects.create(group=self.group, project=self.group.project)

        share_id = handle_is_public(True, self.group_list, self.project_lookup, self.user)

        new_share = GroupShare.objects.get(group=self.group)
        assert Activity.objects.filter(
            group=self.group, type=ActivityType.SET_PRIVATE.value
        ).exists()
        assert new_share != share
        assert Activity.objects.filter(
            group=self.group, type=ActivityType.SET_PUBLIC.value
        ).exists()
        assert share_id == new_share.uuid

    def test_not_is_public(self) -> None:
        GroupShare.objects.create(group=self.group, project=self.group.project)

        share_id = handle_is_public(False, self.group_list, self.project_lookup, self.user)
        assert Activity.objects.filter(
            group=self.group, type=ActivityType.SET_PRIVATE.value
        ).exists()
        assert not GroupShare.objects.filter(group=self.group).exists()
        assert not Activity.objects.filter(
            group=self.group, type=ActivityType.SET_PUBLIC.value
        ).exists()
        assert share_id is None


class TestHandleAssignedTo(TestCase):
    def setUp(self) -> None:
        self.group = self.create_group()
        self.group_list = [self.group]
        self.project_lookup = {self.group.project_id: self.group.project}

    @patch("sentry.analytics.record")
    def test_assigned_to(self, mock_record: Mock) -> None:
        assigned_to = handle_assigned_to(
            ActorTuple.from_actor_identifier(self.user.id),
            None,
            None,
            self.group_list,
            self.project_lookup,
            self.user,
        )

        assert GroupAssignee.objects.filter(group=self.group, user_id=self.user.id).exists()

        assert assigned_to == {
            "email": self.user.email,
            "id": str(self.user.id),
            "name": self.user.username,
            "type": "user",
        }
        mock_record.assert_called_with(
            "manual.issue_assignment",
            group_id=self.group.id,
            organization_id=self.group.project.organization_id,
            project_id=self.group.project_id,
            assigned_by=None,
            had_to_deassign=False,
        )

    @patch("sentry.analytics.record")
    def test_unassign(self, mock_record: Mock) -> None:
        assigned_to = handle_assigned_to(
            None, None, None, self.group_list, self.project_lookup, self.user
        )

        assert not GroupAssignee.objects.filter(group=self.group, user_id=self.user.id).exists()

        assert assigned_to is None
        mock_record.assert_called_with(
            "manual.issue_assignment",
            group_id=self.group.id,
            organization_id=self.group.project.organization_id,
            project_id=self.group.project_id,
            assigned_by=None,
            had_to_deassign=True,
        )
