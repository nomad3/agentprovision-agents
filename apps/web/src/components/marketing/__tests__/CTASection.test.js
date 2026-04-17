import { render, screen } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import CTASection from '../CTASection';

// jsdom does not implement IntersectionObserver (used by framer-motion useInView)
beforeAll(() => {
  global.IntersectionObserver = class IntersectionObserver {
    constructor() {}
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

jest.mock('react-i18next', () => {
  // eslint-disable-next-line global-require
  const path = require('path');
  const landing = require(path.resolve(__dirname, '../../../i18n/locales/en/landing.json'));
  return {
    useTranslation: (ns) => ({
      t: (key) => {
        const parts = key.split('.');
        let value = ns === 'landing' ? landing : {};
        for (const part of parts) {
          value = value?.[part];
        }
        return typeof value === 'string' ? value : key;
      },
    }),
  };
});

test('renders CTA button', () => {
  render(<CTASection />, { wrapper: ({ children }) => <BrowserRouter>{children}</BrowserRouter> });
  expect(screen.getByText(/Get Started Free/i)).toBeInTheDocument();
});
