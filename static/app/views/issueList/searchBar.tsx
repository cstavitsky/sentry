import {useCallback} from 'react';
import styled from '@emotion/styled';

// eslint-disable-next-line no-restricted-imports
import {fetchTagValues} from 'sentry/actionCreators/tags';
import SmartSearchBar from 'sentry/components/smartSearchBar';
import {ItemType, SearchGroup} from 'sentry/components/smartSearchBar/types';
import {IconStar} from 'sentry/icons';
import {t} from 'sentry/locale';
import {space} from 'sentry/styles/space';
import {Organization, SavedSearchType, Tag, TagCollection} from 'sentry/types';
import {getUtcDateString} from 'sentry/utils/dates';
import {
  DEVICE_CLASS_TAG_VALUES,
  FieldKind,
  getFieldDefinition,
  isDeviceClass,
} from 'sentry/utils/fields';
import useApi from 'sentry/utils/useApi';
import usePageFilters from 'sentry/utils/usePageFilters';
import withIssueTags, {WithIssueTagsProps} from 'sentry/utils/withIssueTags';

const getSupportedTags = (supportedTags: TagCollection) =>
  Object.fromEntries(
    Object.keys(supportedTags).map(key => [
      key,
      {
        ...supportedTags[key],
        kind:
          getFieldDefinition(key)?.kind ??
          (supportedTags[key].predefined ? FieldKind.FIELD : FieldKind.TAG),
      },
    ])
  );

interface Props extends React.ComponentProps<typeof SmartSearchBar>, WithIssueTagsProps {
  organization: Organization;
}

const EXCLUDED_TAGS = ['environment'];

function IssueListSearchBar({organization, tags, ...props}: Props) {
  const api = useApi();
  const {selection: pageFilters} = usePageFilters();

  const tagValueLoader = useCallback(
    (key: string, search: string) => {
      const orgSlug = organization.slug;
      const projectIds = pageFilters.projects.map(id => id.toString());
      const endpointParams = {
        start: getUtcDateString(pageFilters.datetime.start),
        end: getUtcDateString(pageFilters.datetime.end),
        statsPeriod: pageFilters.datetime.period,
      };

      return fetchTagValues({
        api,
        orgSlug,
        tagKey: key,
        search,
        projectIds,
        endpointParams,
      });
    },
    [
      api,
      organization.slug,
      pageFilters.datetime.end,
      pageFilters.datetime.period,
      pageFilters.datetime.start,
      pageFilters.projects,
    ]
  );

  const getTagValues = useCallback(
    async (tag: Tag, query: string): Promise<string[]> => {
      // device.class is stored as "numbers" in snuba, but we want to suggest high, medium,
      // and low search filter values because discover maps device.class to these values.
      if (isDeviceClass(tag.key)) {
        return DEVICE_CLASS_TAG_VALUES;
      }
      const values = await tagValueLoader(tag.key, query);
      return values.map(({value}) => {
        // Truncate results to 5000 characters to avoid exceeding the max url query length
        // The message attribute for example can be 8192 characters.
        if (typeof value === 'string' && value.length > 5000) {
          return value.substring(0, 5000);
        }
        return value;
      });
    },
    [tagValueLoader]
  );

  const hasSearchShortcuts = organization.features.includes('issue-search-shortcuts');
  const recommendedGroup: SearchGroup = {
    title: t('Recommended'),
    type: 'header',
    icon: <IconStar size="xs" />,
    childrenWrapper: RecommendedWrapper,
    children: [
      {
        type: ItemType.RECOMMENDED,
        title: t('Assignee'),
        desc: t('Filter by team or member.'),
        value: 'assigned_or_suggested:',
      },
      {
        type: ItemType.RECOMMENDED,
        title: t('Release'),
        desc: t('Filter by release version.'),
        value: 'release:',
      },
      {
        type: ItemType.RECOMMENDED,
        title: t('Level'),
        desc: t('Filter by fatal, error, etc.'),
        value: 'level:',
      },
      {
        type: ItemType.RECOMMENDED,
        title: t('Device'),
        desc: t('Filter events by device.'),
        value: 'device.',
      },
      {
        type: ItemType.RECOMMENDED,
        title: t('Unhandled'),
        desc: t('Filter by unhandled events.'),
        value: 'error.unhandled:true ',
      },
      {
        type: ItemType.RECOMMENDED,
        title: t('Custom Tags'),
        desc: t('Filter events by custom tags.'),
        // Shows only tags when clicked
        applyFilter: item => item.kind === FieldKind.TAG,
      },
    ],
  };

  return (
    <SmartSearchBar
      hasRecentSearches
      savedSearchType={SavedSearchType.ISSUE}
      onGetTagValues={getTagValues}
      excludedTags={EXCLUDED_TAGS}
      maxMenuHeight={500}
      supportedTags={getSupportedTags(tags)}
      defaultSearchGroup={hasSearchShortcuts ? recommendedGroup : undefined}
      organization={organization}
      {...props}
    />
  );
}

export default withIssueTags(IssueListSearchBar);

const RecommendedWrapper = styled('div')`
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: ${space(1.5)};
  padding: ${space(1.5)};

  & > li {
    ${p => p.theme.overflowEllipsis}
    border-radius: ${p => p.theme.borderRadius};
    border: 1px solid ${p => p.theme.border};
    padding: ${space(1.5)} ${space(2)};
    margin: 0;
  }
`;
