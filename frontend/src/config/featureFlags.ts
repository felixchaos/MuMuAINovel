const normalizeEnv = (value: unknown) => String(value ?? '').trim().toLowerCase();
const isDisabled = (value: unknown) => ['0', 'false', 'no', 'off'].includes(normalizeEnv(value));
const isEnabled = (value: unknown) => ['1', 'true', 'yes', 'on'].includes(normalizeEnv(value));

const promoFeaturesDisabled =
  isEnabled(import.meta.env.VITE_DISABLE_PROMO_FEATURES) ||
  normalizeEnv(import.meta.env.VITE_DEPLOY_PROFILE) === 'felix';

const isFeatureEnabled = (value: unknown) => !promoFeaturesDisabled && !isDisabled(value);

export const FEATURE_FLAGS = {
  sponsor: isFeatureEnabled(import.meta.env.VITE_ENABLE_SPONSOR),
  announcementModal: isFeatureEnabled(import.meta.env.VITE_ENABLE_ANNOUNCEMENT_MODAL),
  mumuApiLinks: isFeatureEnabled(import.meta.env.VITE_ENABLE_MUMU_API_LINKS),
  springFestival: isFeatureEnabled(import.meta.env.VITE_ENABLE_SPRING_FESTIVAL),
};
