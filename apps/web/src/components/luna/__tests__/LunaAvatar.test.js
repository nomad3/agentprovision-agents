import { render, screen, fireEvent } from '@testing-library/react';
import LunaAvatar from '../LunaAvatar';
import LunaStateBadge from '../LunaStateBadge';

describe('LunaAvatar', () => {
  test('renders with the default state and image', () => {
    const { container } = render(<LunaAvatar />);
    expect(container.querySelector('.luna-avatar')).toBeInTheDocument();
    expect(container.querySelector('.luna-state-idle')).toBeInTheDocument();
    expect(container.querySelector('img.luna-face-img')).toHaveAttribute('alt', 'Luna');
  });

  test('applies state and mood classes', () => {
    const { container } = render(<LunaAvatar state="happy" mood="excited" />);
    expect(container.querySelector('.luna-state-happy')).toBeInTheDocument();
    expect(container.querySelector('.luna-mood-excited')).toBeInTheDocument();
  });

  test('hides the emote on small sizes', () => {
    const { container, rerender } = render(<LunaAvatar size="xs" />);
    expect(container.querySelector('.luna-emote')).toBeNull();
    rerender(<LunaAvatar size="md" />);
    expect(container.querySelector('.luna-emote')).toBeInTheDocument();
  });

  test('fires onClick when clicked', () => {
    const onClick = jest.fn();
    const { container } = render(<LunaAvatar onClick={onClick} />);
    fireEvent.click(container.querySelector('.luna-avatar'));
    expect(onClick).toHaveBeenCalled();
  });

  test('falls back to idle emote for unknown states', () => {
    const { container } = render(<LunaAvatar state="not-a-state" />);
    // idle emote is "~" — should appear in the .luna-emote element
    expect(container.querySelector('.luna-emote').textContent).toBe('~');
  });
});

describe('LunaStateBadge', () => {
  test('renders the state label with underscores replaced', () => {
    render(<LunaStateBadge state="private_mode" />);
    expect(screen.getByText('private mode')).toBeInTheDocument();
  });

  test('falls back to idle when given an unknown state', () => {
    const { container } = render(<LunaStateBadge state="weird" />);
    // Color must be set to a non-empty hex string
    const dot = container.querySelector('span > span');
    expect(dot.style.backgroundColor).toBeTruthy();
  });

  test('size=xs renders smaller font', () => {
    const { container, rerender } = render(<LunaStateBadge state="idle" size="xs" />);
    const wrap = container.firstChild;
    expect(wrap.style.fontSize).toBe('9px');

    rerender(<LunaStateBadge state="idle" size="md" />);
    const wrap2 = container.firstChild;
    expect(wrap2.style.fontSize).toBe('13px');
  });
});
