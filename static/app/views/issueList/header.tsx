import {ReactNode} from 'react';
import {InjectedRouter} from 'react-router';
import styled from '@emotion/styled';

import GuideAnchor from 'sentry/components/assistant/guideAnchor';
import Badge from 'sentry/components/badge';
import {Button} from 'sentry/components/button';
import ButtonBar from 'sentry/components/buttonBar';
import GlobalEventProcessingAlert from 'sentry/components/globalEventProcessingAlert';
import * as Layout from 'sentry/components/layouts/thirds';
import {PageHeadingQuestionTooltip} from 'sentry/components/pageHeadingQuestionTooltip';
import QueryCount from 'sentry/components/queryCount';
import {TabList, Tabs} from 'sentry/components/tabs';
import {Tooltip} from 'sentry/components/tooltip';
import {SLOW_TOOLTIP_DELAY} from 'sentry/constants';
import {IconPause, IconPlay} from 'sentry/icons';
import {t} from 'sentry/locale';
import {space} from 'sentry/styles/space';
import {Organization} from 'sentry/types';
import useProjects from 'sentry/utils/useProjects';
import {normalizeUrl} from 'sentry/utils/withDomainRequired';
import IssueListSetAsDefault from 'sentry/views/issueList/issueListSetAsDefault';

import {
  FOR_REVIEW_QUERIES,
  getTabs,
  IssueSortOptions,
  Query,
  QueryCounts,
  TAB_MAX_COUNT,
} from './utils';

type IssueListHeaderProps = {
  displayReprocessingTab: boolean;
  onRealtimeChange: (realtime: boolean) => void;
  organization: Organization;
  query: string;
  queryCounts: QueryCounts;
  realtimeActive: boolean;
  router: InjectedRouter;
  selectedProjectIds: number[];
  sort: string;
  queryCount?: number;
};

type IssueListHeaderTabProps = {
  name: string;
  count?: number;
  hasMore?: boolean;
  tooltipHoverable?: boolean;
  tooltipTitle?: ReactNode;
};

function IssueListHeaderTabContent({
  count = 0,
  hasMore = false,
  name,
  tooltipHoverable,
  tooltipTitle,
}: IssueListHeaderTabProps) {
  return (
    <Tooltip
      title={tooltipTitle}
      position="bottom"
      isHoverable={tooltipHoverable}
      delay={SLOW_TOOLTIP_DELAY}
    >
      {name}{' '}
      {count > 0 && (
        <Badge>
          <QueryCount hideParens count={count} max={hasMore ? TAB_MAX_COUNT : 1000} />
        </Badge>
      )}
    </Tooltip>
  );
}

function IssueListHeader({
  organization,
  query,
  sort,
  queryCounts,
  realtimeActive,
  onRealtimeChange,
  router,
  displayReprocessingTab,
  selectedProjectIds,
}: IssueListHeaderProps) {
  const {projects} = useProjects();
  const tabs = getTabs(organization);
  const visibleTabs = displayReprocessingTab
    ? tabs
    : tabs.filter(([tab]) => tab !== Query.REPROCESSING);
  // Remove cursor and page when switching tabs
  const {cursor: _, page: __, ...queryParms} = router?.location?.query ?? {};
  const sortParam =
    queryParms.sort === IssueSortOptions.INBOX ? undefined : queryParms.sort;

  const selectedProjects = projects.filter(({id}) =>
    selectedProjectIds.includes(Number(id))
  );
  const realtimeTitle = realtimeActive
    ? t('Pause real-time updates')
    : t('Enable real-time updates');

  return (
    <Layout.Header noActionWrap>
      <Layout.HeaderContent>
        <Layout.Title>
          {t('Issues')}
          <PageHeadingQuestionTooltip
            docsUrl="https://docs.sentry.io/product/issues/"
            title={t(
              'Detailed views of errors and performance problems in your application grouped by events with a similar set of characteristics.'
            )}
          />
        </Layout.Title>
      </Layout.HeaderContent>
      <Layout.HeaderActions>
        <ButtonBar gap={1}>
          <IssueListSetAsDefault {...{sort, query, organization}} />
          <Button
            size="sm"
            data-test-id="real-time"
            title={realtimeTitle}
            aria-label={realtimeTitle}
            icon={realtimeActive ? <IconPause size="xs" /> : <IconPlay size="xs" />}
            onClick={() => onRealtimeChange(!realtimeActive)}
          />
        </ButtonBar>
      </Layout.HeaderActions>
      <StyledGlobalEventProcessingAlert projects={selectedProjects} />
      <StyledTabs selectedKey={query} onSelectionChange={() => {}}>
        <TabList hideBorder>
          {[
            ...visibleTabs.map(
              ([tabQuery, {name: queryName, tooltipTitle, tooltipHoverable}]) => {
                const to = normalizeUrl({
                  query: {
                    ...queryParms,
                    query: tabQuery,
                    sort: FOR_REVIEW_QUERIES.includes(tabQuery || '')
                      ? IssueSortOptions.INBOX
                      : sortParam,
                  },
                  pathname: `/organizations/${organization.slug}/issues/`,
                });

                return (
                  <TabList.Item key={tabQuery} to={to} textValue={queryName}>
                    <GuideAnchor
                      disabled={tabQuery !== Query.ARCHIVED}
                      target="issue_stream_archive_tab"
                      position="bottom"
                    >
                      <IssueListHeaderTabContent
                        tooltipTitle={tooltipTitle}
                        tooltipHoverable={tooltipHoverable}
                        name={queryName}
                        count={queryCounts[tabQuery]?.count}
                        hasMore={queryCounts[tabQuery]?.hasMore}
                      />
                    </GuideAnchor>
                  </TabList.Item>
                );
              }
            ),
          ]}
        </TabList>
      </StyledTabs>
    </Layout.Header>
  );
}

export default IssueListHeader;

const StyledGlobalEventProcessingAlert = styled(GlobalEventProcessingAlert)`
  grid-column: 1/-1;
  margin-top: ${space(1)};
  margin-bottom: ${space(1)};

  @media (min-width: ${p => p.theme.breakpoints.medium}) {
    margin-top: ${space(2)};
    margin-bottom: 0;
  }
`;

const StyledTabs = styled(Tabs)`
  grid-column: 1/-1;
`;
