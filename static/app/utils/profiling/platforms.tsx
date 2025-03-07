import {profiling} from 'sentry/data/platformCategories';
import {Project} from 'sentry/types/project';

export const supportedProfilingPlatforms = profiling;
export const supportedProfilingPlatformSDKs = [
  'android',
  'apple-ios',
  'go',
  'node',
  'python',
  'php',
  'php',
  'php-laravel',
  'php-symfony2',
  'ruby',
  'javascript-nextjs',
  'javascript-remix',
  'javascript-sveltekit',
] as const;
export type SupportedProfilingPlatform = (typeof supportedProfilingPlatforms)[number];
export type SupportedProfilingPlatformSDK =
  (typeof supportedProfilingPlatformSDKs)[number];

export function getDocsPlatformSDKForPlatform(
  platform: string | undefined
): SupportedProfilingPlatform | null {
  if (!platform) {
    return null;
  }

  // Android
  if (platform === 'android') {
    return 'android';
  }
  // iOS
  if (platform === 'apple-ios') {
    return 'apple-ios';
  }

  // Go
  if (platform === 'go') {
    return 'go';
  }

  // Javascript
  if (platform.startsWith('node')) {
    return 'node';
  }
  if (platform === 'javascript-nextjs') {
    return 'javascript-nextjs';
  }
  if (platform === 'javascript-remix') {
    return 'javascript-remix';
  }
  if (platform === 'javascript-sveltekit') {
    return 'javascript-sveltekit';
  }

  // Python
  if (platform.startsWith('python')) {
    return 'python';
  }

  // PHP
  if (platform === 'php-laravel') {
    return 'php-laravel';
  }
  if (platform === 'php-symfony') {
    return 'php-symfony2';
  }
  if (platform.startsWith('php')) {
    return 'php';
  }

  // Ruby
  if (platform.startsWith('ruby')) {
    return 'ruby';
  }

  return null;
}

export function isProfilingSupportedOrProjectHasProfiles(project: Project): boolean {
  return !!(
    (project.platform && getDocsPlatformSDKForPlatform(project.platform)) ||
    // If this project somehow managed to send profiles, then profiling is supported for this project.
    // Sometimes and for whatever reason, platform can also not be set on a project so the above check alone would fail
    project.hasProfiles
  );
}

export function getProfilingDocsForPlatform(platform: string | undefined): string | null {
  const docsPlatform = getDocsPlatformSDKForPlatform(platform);
  if (!docsPlatform) {
    return null;
  }
  return docsPlatform === 'apple-ios'
    ? 'https://docs.sentry.io/platforms/apple/guides/ios/profiling/'
    : `https://docs.sentry.io/platforms/${docsPlatform}/profiling/`;
}
