import {useState} from 'react';
import {Link} from 'react-router';
import {useTheme} from '@emotion/react';
import styled from '@emotion/styled';
import cloneDeep from 'lodash/cloneDeep';
import * as qs from 'query-string';

import Checkbox from 'sentry/components/checkbox';
import {CompactSelect, SelectOption} from 'sentry/components/compactSelect';
import TextOverflow from 'sentry/components/textOverflow';
import {Tooltip} from 'sentry/components/tooltip';
import {t} from 'sentry/locale';
import {space} from 'sentry/styles/space';
import {Series} from 'sentry/types/echarts';
import {defined} from 'sentry/utils';
import {getUtcDateString} from 'sentry/utils/dates';
import {tooltipFormatterUsingAggregateOutputType} from 'sentry/utils/discover/charts';
import {NumberContainer} from 'sentry/utils/discover/styles';
import {formatPercentage} from 'sentry/utils/formatters';
import usePageFilters from 'sentry/utils/usePageFilters';
import {RightAlignedCell} from 'sentry/views/performance/landing/widgets/components/selectableList';
import Chart from 'sentry/views/starfish/components/chart';
import {DataRow} from 'sentry/views/starfish/views/webServiceView/spanGroupBreakdownContainer';

type Props = {
  colorPalette: string[];
  isCumulativeTimeLoading: boolean;
  isTableLoading: boolean;
  isTimeseriesLoading: boolean;
  tableData: DataRow[];
  topSeriesData: Series[];
  totalCumulativeTime: number;
  errored?: boolean;
  transaction?: string;
};

export enum DataDisplayType {
  CUMULATIVE_DURATION = 'cumulative_duration',
  PERCENTAGE = 'percentage',
}

export function SpanGroupBreakdown({
  tableData: transformedData,
  totalCumulativeTime: totalValues,
  topSeriesData: data,
  transaction,
  isTimeseriesLoading,
  errored,
}: Props) {
  const {selection} = usePageFilters();
  const theme = useTheme();
  const [showSeriesArray, setShowSeriesArray] = useState<boolean[]>([]);
  const options: SelectOption<DataDisplayType>[] = [
    {label: 'Total Duration', value: DataDisplayType.CUMULATIVE_DURATION},
    {label: 'Percentages', value: DataDisplayType.PERCENTAGE},
  ];
  const [dataDisplayType, setDataDisplayType] = useState<DataDisplayType>(
    DataDisplayType.CUMULATIVE_DURATION
  );

  if (showSeriesArray.length === 0 && transformedData.length > 0) {
    setShowSeriesArray(transformedData.map(() => true));
  }

  const visibleSeries: Series[] = [];

  for (let index = 0; index < data.length; index++) {
    const series = data[index];
    if (showSeriesArray[index]) {
      visibleSeries.push(series);
    }
  }
  const colorPalette = theme.charts.getColorPalette(transformedData.length - 2);

  const dataAsPercentages = cloneDeep(visibleSeries);
  const numDataPoints = data[0]?.data?.length ?? 0;
  for (let i = 0; i < numDataPoints; i++) {
    const totalTimeAtIndex = data.reduce((acc, datum) => acc + datum.data[i].value, 0);
    dataAsPercentages.forEach(segment => {
      const clone = {...segment.data[i]};
      clone.value = clone.value / totalTimeAtIndex;
      segment.data[i] = clone;
    });
  }

  const handleChange = (option: SelectOption<DataDisplayType>) =>
    setDataDisplayType(option.value);

  return (
    <FlexRowContainer>
      <ChartPadding>
        <Header>
          <ChartLabel>
            {transaction ? t('Endpoint Time Breakdown') : t('Service Breakdown')}
          </ChartLabel>
          <CompactSelect
            options={options}
            value={dataDisplayType}
            onChange={handleChange}
          />
        </Header>
        <Chart
          statsPeriod="24h"
          height={210}
          data={
            dataDisplayType === DataDisplayType.PERCENTAGE
              ? dataAsPercentages
              : visibleSeries
          }
          dataMax={dataDisplayType === DataDisplayType.PERCENTAGE ? 1 : undefined}
          durationUnit={dataDisplayType === DataDisplayType.PERCENTAGE ? 0.25 : undefined}
          start=""
          end=""
          errored={errored}
          loading={isTimeseriesLoading}
          utc={false}
          grid={{
            left: '0',
            right: '0',
            top: '8px',
            bottom: '0',
          }}
          definedAxisTicks={6}
          stacked
          aggregateOutputFormat={
            dataDisplayType === DataDisplayType.PERCENTAGE ? 'percentage' : 'duration'
          }
          tooltipFormatterOptions={{
            valueFormatter: value =>
              tooltipFormatterUsingAggregateOutputType(value, 'duration'),
          }}
        />
      </ChartPadding>
      <ListContainer>
        {transformedData.map((row, index) => {
          const checkedValue = showSeriesArray[index];
          const group = row.group;
          const {start, end, utc, period} = selection.datetime;
          const spansLinkQueryParams =
            start && end
              ? {start: getUtcDateString(start), end: getUtcDateString(end), utc}
              : {statsPeriod: period};

          if (group['span.category'] === 'Other') {
            spansLinkQueryParams['!span.module'] = ['db', 'http'];
            spansLinkQueryParams['!span.category'] = transformedData.map(
              r => r.group['span.category']
            );
          } else {
            if (['db', 'http'].includes(group['span.category'])) {
              spansLinkQueryParams['span.module'] = group['span.category'];
            } else {
              spansLinkQueryParams['span.module'] = 'Other';
            }
            spansLinkQueryParams['span.category'] = group['span.category'];
          }

          const spansLink = `/starfish/spans/?${qs.stringify(spansLinkQueryParams)}`;
          return (
            <StyledLineItem key={`${group['span.category']}`}>
              <ListItemContainer>
                <Checkbox
                  size="sm"
                  checkboxColor={colorPalette[index]}
                  inputCss={{backgroundColor: 'red'}}
                  checked={checkedValue}
                  onChange={() => {
                    const updatedSeries = [...showSeriesArray];
                    updatedSeries[index] = !checkedValue;
                    setShowSeriesArray(updatedSeries);
                  }}
                />
                <TextAlignLeft>
                  {defined(transaction) ? (
                    <TextOverflow>{group['span.category']}</TextOverflow>
                  ) : (
                    <Link to={spansLink}>
                      <TextOverflow>{group['span.category']}</TextOverflow>
                    </Link>
                  )}
                </TextAlignLeft>
                <RightAlignedCell>
                  <Tooltip
                    title={t(
                      '%s time spent on %s',
                      formatPercentage(row.cumulativeTime / totalValues, 1),
                      group['span.category']
                    )}
                    containerDisplayMode="block"
                    position="top"
                  >
                    <NumberContainer
                      style={{textDecoration: 'underline', textDecorationStyle: 'dotted'}}
                    >
                      {formatPercentage(row.cumulativeTime / totalValues, 1)}
                    </NumberContainer>
                  </Tooltip>
                </RightAlignedCell>
              </ListItemContainer>
            </StyledLineItem>
          );
        })}
      </ListContainer>
    </FlexRowContainer>
  );
}

const StyledLineItem = styled('li')`
  line-height: ${p => p.theme.text.lineHeightBody};
`;

const ListItemContainer = styled('div')`
  display: flex;
  padding: ${space(1)} ${space(2)};
  font-size: ${p => p.theme.fontSizeMedium};
`;

const ListContainer = styled('ul')`
  padding: ${space(1)} 0 0 0;
  margin: 0;
  border-left: 1px solid ${p => p.theme.border};
  list-style-type: none;
`;

const TextAlignLeft = styled('span')`
  text-align: left;
  width: 100%;
  padding: 0 ${space(1.5)};
`;

const ChartPadding = styled('div')`
  padding: 0 ${space(2)};
  flex: 2;
`;

const ChartLabel = styled('p')`
  ${p => p.theme.text.cardTitle}
`;

const Header = styled('div')`
  padding: 0 ${space(1)} 0 0;
  min-height: 36px;
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
`;

const FlexRowContainer = styled('div')`
  display: flex;
  min-height: 200px;
  padding-bottom: ${space(2)};
`;
