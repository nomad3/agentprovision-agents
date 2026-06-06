import { describe, it, expect } from 'vitest';

import { __desktopCommandDownchannelTest } from '../useDesktopCommandDownchannel';

describe('useDesktopCommandDownchannel', () => {
  it('treats expired command leases as stale before execution', () => {
    expect(__desktopCommandDownchannelTest.leaseExpired({
      lease_expires_at: new Date(Date.now() - 1000).toISOString(),
    })).toBe(true);

    expect(__desktopCommandDownchannelTest.leaseExpired({
      lease_expires_at: new Date(Date.now() + 10000).toISOString(),
    })).toBe(false);
  });
});
