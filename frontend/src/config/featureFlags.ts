const isDisabled = (value: unknown) => String(value).toLowerCase() === 'false';

export const FEATURE_FLAGS = {
  sponsor: !isDisabled(import.meta.env.VITE_ENABLE_SPONSOR),
  announcementModal: !isDisabled(import.meta.env.VITE_ENABLE_ANNOUNCEMENT_MODAL),
  mumuApiLinks: !isDisabled(import.meta.env.VITE_ENABLE_MUMU_API_LINKS),
};
