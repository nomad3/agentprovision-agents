import { render, screen } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import { mockUseTranslation } from '../../../test-utils/i18nMock';
import HeroSection from '../HeroSection';

beforeAll(() => {
  global.IntersectionObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

jest.mock('react-i18next', () => ({ useTranslation: mockUseTranslation }));

const Wrapper = ({ children }) => <BrowserRouter>{children}</BrowserRouter>;

test('renders hero title and CTAs', () => {
  render(<HeroSection />, { wrapper: Wrapper });
  expect(screen.getByRole('heading', { level: 1 })).toBeInTheDocument();
  expect(screen.getByText(/Get Started/i)).toBeInTheDocument();
  expect(screen.getByText(/Sign In/i)).toBeInTheDocument();
});

test('renders both images', () => {
  render(<HeroSection />, { wrapper: Wrapper });
  const imgs = screen.getAllByRole('img', { hidden: true });
  expect(imgs.length).toBeGreaterThanOrEqual(2);
});
