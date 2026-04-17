import { render, screen } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import HeroSection from '../HeroSection';

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

const Wrapper = ({ children }) => <BrowserRouter>{children}</BrowserRouter>;

test('renders headline and CTAs', () => {
  render(<HeroSection />, { wrapper: Wrapper });
  expect(screen.getByRole('heading', { level: 1 })).toBeInTheDocument();
  expect(screen.getByText(/Get Started/i)).toBeInTheDocument();
});
