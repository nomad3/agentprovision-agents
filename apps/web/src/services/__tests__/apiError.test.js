/**
 * @jest-environment jsdom
 *
 * Tests for formatApiError — the defensive unwrapper that prevents
 * React error #31 ("Objects are not valid as a React child") when
 * a page tries to render err.response.data.detail directly and detail
 * happens to be a Pydantic v2 validation array.
 *
 * Background: PR #263 (Tier 3 fleet-health) shipped without this guard,
 * causing the entire React tree to crash to a blank page when the
 * API returned a 422. This test pins the invariant for all four
 * curated visibility pages (CostInsights, FleetHealth, CoalitionReplay,
 * TenantHealth).
 */
import { formatApiError } from '../apiError';


describe('formatApiError', () => {
  test('returns string detail unchanged', () => {
    const err = { response: { data: { detail: 'Could not validate credentials' } } };
    expect(formatApiError(err)).toBe('Could not validate credentials');
  });

  test('unwraps Pydantic v2 validation array — first message wins', () => {
    const err = {
      response: {
        data: {
          detail: [
            {
              type: 'uuid_parsing',
              loc: ['path', 'agent_id'],
              msg: 'Input should be a valid UUID, invalid character',
              input: 'fleet-health',
              ctx: { error: 'invalid character' },
            },
          ],
        },
      },
    };
    expect(formatApiError(err)).toBe(
      'path.agent_id: Input should be a valid UUID, invalid character',
    );
  });

  test('handles validation array without loc', () => {
    const err = {
      response: { data: { detail: [{ msg: 'something went wrong' }] } },
    };
    expect(formatApiError(err)).toBe('something went wrong');
  });

  test('handles object detail with message field', () => {
    const err = { response: { data: { detail: { message: 'tenant quota exceeded' } } } };
    expect(formatApiError(err)).toBe('tenant quota exceeded');
  });

  test('falls back to provided default for unknown shapes', () => {
    const err = { response: { data: { detail: { weird: 'shape' } } } };
    expect(formatApiError(err, 'Failed to load X.')).toBe('Failed to load X.');
  });

  test('falls back when no response at all (network error)', () => {
    const err = new Error('Network Error');
    expect(formatApiError(err, 'Failed.')).toBe('Failed.');
  });

  test('falls back when detail missing entirely', () => {
    const err = { response: { data: {} } };
    expect(formatApiError(err, 'Failed.')).toBe('Failed.');
  });

  test('falls back when detail is empty string', () => {
    const err = { response: { data: { detail: '   ' } } };
    expect(formatApiError(err, 'Failed.')).toBe('Failed.');
  });

  test('returns a string for any input — guarantees React-safe output', () => {
    // The whole point of this helper. Hammer it with bad inputs.
    const inputs = [
      null,
      undefined,
      {},
      { response: null },
      { response: { data: null } },
      { response: { data: { detail: null } } },
      { response: { data: { detail: 42 } } },
      { response: { data: { detail: [] } } },  // empty array
      { response: { data: { detail: [{}] } } },  // array of object without msg
    ];
    inputs.forEach((err) => {
      expect(typeof formatApiError(err, 'Fallback.')).toBe('string');
    });
  });
});
