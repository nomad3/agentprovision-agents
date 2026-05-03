/*
 * Defensive helper for converting an axios error into a string suitable
 * to render as a React child.
 *
 * Background: FastAPI / Pydantic v2 returns 422 with
 *   { "detail": [{type, loc, msg, input, ctx}, ...] }
 * If a page does `setError(err.response?.data?.detail || 'fallback')`
 * and renders {error}, React error #31 fires ("Objects are not valid
 * as a React child") and the entire app tree unmounts to a blank page.
 *
 * This helper unwraps that case (and any other non-string detail) into
 * a human-readable string. Use it from every page's catch block.
 */
export function formatApiError(err, fallback = 'Request failed.') {
  const detail = err?.response?.data?.detail;
  if (typeof detail === 'string' && detail.trim()) {
    return detail;
  }
  if (Array.isArray(detail)) {
    // Pydantic v2 validation error array — pick the first one's message.
    const first = detail[0];
    if (first && typeof first === 'object' && typeof first.msg === 'string') {
      const loc = Array.isArray(first.loc) ? first.loc.join('.') : '';
      return loc ? `${loc}: ${first.msg}` : first.msg;
    }
    return fallback;
  }
  if (detail && typeof detail === 'object') {
    if (typeof detail.message === 'string') return detail.message;
    return fallback;
  }
  return fallback;
}
