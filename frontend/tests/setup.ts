import '@testing-library/jest-dom/vitest';

// jsdom's window is narrower than the desktop layout. Treat min-width queries
// as matched so sidebar collapse can be tested the way the app is used.
window.matchMedia = ((query: string) => ({
  matches: query.includes('min-width'),
  media: query,
  onchange: null,
  addListener: () => undefined,
  removeListener: () => undefined,
  addEventListener: () => undefined,
  removeEventListener: () => undefined,
  dispatchEvent: () => false,
})) as typeof window.matchMedia;
