from sentry.issues.ongoing import transition_group_to_ongoing
from sentry.models import (
    Activity,
    GroupHistory,
    GroupHistoryStatus,
    GroupInbox,
    GroupInboxReason,
    GroupStatus,
)
from sentry.testutils import TestCase
from sentry.types.activity import ActivityType
from sentry.types.group import GroupSubStatus


class TransitionNewToOngoingTest(TestCase):
    def test_new_to_ongoing(self) -> None:
        group = self.create_group(status=GroupStatus.UNRESOLVED, substatus=GroupSubStatus.NEW)

        transition_group_to_ongoing(GroupStatus.UNRESOLVED, GroupSubStatus.NEW, group)
        assert GroupInbox.objects.filter(
            group=group, reason=GroupInboxReason.ONGOING.value
        ).exists()
        assert Activity.objects.filter(
            group=group, type=ActivityType.AUTO_SET_ONGOING.value
        ).exists()
        assert GroupHistory.objects.filter(
            group=group, status=GroupHistoryStatus.UNRESOLVED
        ).exists()

    def test_regressed_to_ongoing(self) -> None:
        group = self.create_group(status=GroupStatus.UNRESOLVED, substatus=GroupSubStatus.REGRESSED)

        transition_group_to_ongoing(GroupStatus.UNRESOLVED, GroupSubStatus.REGRESSED, group)
        assert GroupInbox.objects.filter(
            group=group, reason=GroupInboxReason.ONGOING.value
        ).exists()
        assert Activity.objects.filter(
            group=group, type=ActivityType.AUTO_SET_ONGOING.value
        ).exists()
        assert GroupHistory.objects.filter(
            group=group, status=GroupHistoryStatus.UNRESOLVED
        ).exists()
