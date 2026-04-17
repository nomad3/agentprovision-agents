import { render, screen, fireEvent } from '@testing-library/react';
import ProductDemo from '../ProductDemo';

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

test('renders all 5 tab labels', () => {
  render(<ProductDemo />);
  expect(screen.getByText(/Dashboard/i)).toBeInTheDocument();
  expect(screen.getByText(/Agent Memory/i)).toBeInTheDocument();
  expect(screen.getByText(/AI Command/i)).toBeInTheDocument();
  expect(screen.getByText(/Agent Fleet/i)).toBeInTheDocument();
  expect(screen.getByText(/Workflows/i)).toBeInTheDocument();
});

test('clicking a tab updates active state', () => {
  render(<ProductDemo />);
  const memoryTab = screen.getByText(/Agent Memory/i);
  fireEvent.click(memoryTab);
  expect(memoryTab.closest('button')).toHaveClass('product-demo__tab--active');
});
