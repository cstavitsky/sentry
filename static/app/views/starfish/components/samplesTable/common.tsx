import styled from '@emotion/styled';

import {t} from 'sentry/locale';
import {getDuration} from 'sentry/utils/formatters';
import {TextAlignRight} from 'sentry/views/starfish/components/textAlign';

type Props = {
  duration: number;
  p95: number;
  containerProps?: React.DetailedHTMLProps<
    React.HTMLAttributes<HTMLSpanElement>,
    HTMLSpanElement
  >;
};

export function DurationComparisonCell({duration, p95, containerProps}: Props) {
  const diff = duration - p95;

  if (Math.floor(duration) === Math.floor(p95)) {
    return <TextAlignRight>{t('At baseline')}</TextAlignRight>;
  }

  const readableDiff = getDuration(diff / 1000, 2, true, true);
  const labelString = diff > 0 ? `+${readableDiff} above` : `${readableDiff} below`;

  return (
    <ComparisonLabel {...containerProps} value={diff}>
      {labelString}
    </ComparisonLabel>
  );
}

export const PlaintextLabel = styled('div')``;

export const ComparisonLabel = styled('span')<{value: number}>`
  color: ${p =>
    p.value === 0 ? p.theme.subText : p.value < 0 ? p.theme.green400 : p.theme.red400};
  text-align: right;
`;
