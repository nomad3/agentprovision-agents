/*
 * CostInsightsPage — Tier 2 of the visibility roadmap.
 *
 * Per-tenant cost / quota dashboard. Backed by `GET /insights/cost`
 * which aggregates `agent_performance_snapshots` (already-rolled-up
 * hourly per-agent data) into stacked time series + top-10 + quota
 * burn projection.
 *
 * Lives at `/insights/cost`. Same INSIGHTS sidebar bucket as
 * /insights/fleet-health (Tier 3).
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Alert, Badge, Form, Spinner, Table } from 'react-bootstrap';
import {
  FaChartLine,
  FaCoins,
  FaExclamationTriangle,
  FaUserFriends,
  FaUserCircle,
  FaRobot,
} from 'react-icons/fa';
import { useNavigate } from 'react-router-dom';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import Layout from '../components/Layout';
import api from '../services/api';
import { formatApiError } from '../services/apiError';
import './CostInsightsPage.css';


const RANGE_OPTIONS = [
  { value: '7d', label: '7 days' },
  { value: '30d', label: '30 days' },
  { value: '90d', label: '90 days' },
];

const GROUP_BY_OPTIONS = [
  { value: 'agent', label: 'Agent', Icon: FaRobot },
  { value: 'team',  label: 'Team',  Icon: FaUserFriends },
  { value: 'owner', label: 'Owner', Icon: FaUserCircle },
];


function _money(n) {
  if (typeof n !== 'number') return '$0';
  return `$${n.toFixed(4)}`;
}

function _intl(n) {
  if (typeof n !== 'number') return '0';
  return n.toLocaleString('en-US');
}


/**
 * Reshape backend `series` (one entry per group, each with buckets)
 * into recharts-friendly rows (one row per date, columns per group).
 */
function buildChartData(series) {
  const dateMap = new Map(); // date -> {date, group_a: cost, group_b: cost, ...}
  series.forEach((s) => {
    s.buckets.forEach((b) => {
      const row = dateMap.get(b.date) || { date: b.date };
      row[s.label] = (row[s.label] || 0) + b.cost_usd;
      dateMap.set(b.date, row);
    });
  });
  return Array.from(dateMap.values()).sort((a, b) => (a.date < b.date ? -1 : 1));
}


// Stable color palette for the stacked bar — generates a deterministic
// color per series label so renders are stable across navigation.
const PALETTE = [
  '#2b7de9', '#2d9d78', '#d65a5a', '#f59e0b', '#9333ea',
  '#0891b2', '#a16207', '#be185d', '#65a30d', '#475569',
];
function colorFor(label, idx) {
  return PALETTE[idx % PALETTE.length];
}


const CostInsightsPage = () => {
  const navigate = useNavigate();
  const [range, setRange] = useState('30d');
  const [groupBy, setGroupBy] = useState('agent');
  const [granularity, setGranularity] = useState('day');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await api.get('/insights/cost', {
        params: { range, group_by: groupBy, granularity },
      });
      setData(resp.data);
    } catch (err) {
      setError(formatApiError(err, 'Failed to load cost insights.'));
    } finally {
      setLoading(false);
    }
  }, [range, groupBy, granularity]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const chartData = useMemo(
    () => (data?.series ? buildChartData(data.series) : []),
    [data],
  );

  const seriesLabels = useMemo(
    () => (data?.series || []).map((s, i) => ({ label: s.label, color: colorFor(s.label, i) })),
    [data],
  );

  const quotaBanner = useMemo(() => {
    const qb = data?.quota_burn;
    if (!qb || qb.days_until_exhaustion === null || qb.days_until_exhaustion === undefined) {
      return null;
    }
    if (qb.days_until_exhaustion >= 14) return null;
    const variant = qb.days_until_exhaustion < 7 ? 'danger' : 'warning';
    return (
      <Alert variant={variant} className="mb-3">
        <FaExclamationTriangle className="me-2" />
        <strong>
          Projected token-quota exhaustion in {qb.days_until_exhaustion} day(s)
        </strong>{' '}
        — usage of {_intl(qb.tokens_used_mtd)} tokens MTD against limit of{' '}
        {_intl(qb.monthly_limit_tokens)}. Projected hit:{' '}
        {qb.projected_exhaustion_date}.
      </Alert>
    );
  }, [data]);

  return (
    <Layout>
      <div className="cost-insights-page">
        <header className="ap-page-header">
          <div>
            <h1 className="ap-page-title">
              <FaChartLine className="me-2" /> Cost & Usage
            </h1>
            <p className="ap-page-subtitle">
              Token + cost rollup across your agent fleet. Aggregated from
              hourly performance snapshots; updates as the snapshot worker runs.
            </p>
          </div>
        </header>

        {error && (
          <Alert variant="danger" onClose={() => setError(null)} dismissible>
            {error}
          </Alert>
        )}

        {quotaBanner}

        {/* Filter row */}
        <div className="cost-filters mb-4">
          <div>
            <label className="cost-filter-label">Range</label>
            <div className="ap-chip-row">
              {RANGE_OPTIONS.map((r) => (
                <button
                  key={r.value}
                  type="button"
                  className={`ap-chip-filter ${range === r.value ? 'active' : ''}`}
                  onClick={() => setRange(r.value)}
                >
                  {r.label}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label className="cost-filter-label">Granularity</label>
            <Form.Select
              size="sm"
              value={granularity}
              onChange={(e) => setGranularity(e.target.value)}
              style={{ maxWidth: 140 }}
            >
              <option value="day">Day</option>
              <option value="week">Week</option>
            </Form.Select>
          </div>
          <div>
            <label className="cost-filter-label">Group by</label>
            <div className="ap-chip-row">
              {GROUP_BY_OPTIONS.map((g) => {
                const Icon = g.Icon;
                return (
                  <button
                    key={g.value}
                    type="button"
                    className={`ap-chip-filter ${groupBy === g.value ? 'active' : ''}`}
                    onClick={() => setGroupBy(g.value)}
                  >
                    <Icon size={11} /> {g.label}
                  </button>
                );
              })}
            </div>
          </div>
        </div>

        {loading ? (
          <div className="text-center py-5">
            <Spinner animation="border" variant="primary" />
          </div>
        ) : !data ? null : (
          <>
            {/* Total tiles */}
            <div className="cost-totals-grid mb-4">
              <div className="cost-total-tile">
                <FaCoins className="cost-tile-icon" />
                <div>
                  <div className="cost-tile-value">${data.totals.cost_usd?.toFixed(2) || '0.00'}</div>
                  <div className="cost-tile-label">Total cost ({range})</div>
                </div>
              </div>
              <div className="cost-total-tile">
                <FaChartLine className="cost-tile-icon" />
                <div>
                  <div className="cost-tile-value">{_intl(data.totals.tokens)}</div>
                  <div className="cost-tile-label">Tokens</div>
                </div>
              </div>
              <div className="cost-total-tile">
                <FaRobot className="cost-tile-icon" />
                <div>
                  <div className="cost-tile-value">{_intl(data.totals.invocations)}</div>
                  <div className="cost-tile-label">Invocations</div>
                </div>
              </div>
            </div>

            {/* Stacked bar chart */}
            {chartData.length === 0 ? (
              <Alert variant="info">
                No usage in this range. Try a wider range or a different group-by.
              </Alert>
            ) : (
              <div className="cost-chart-wrapper" style={{ height: 360 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chartData} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(180,200,220,0.25)" />
                    <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                    <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => `$${v.toFixed(2)}`} />
                    <Tooltip
                      formatter={(v) => [`$${(v ?? 0).toFixed(4)}`, 'cost']}
                      contentStyle={{ fontSize: '0.8rem' }}
                    />
                    <Legend wrapperStyle={{ fontSize: '0.8rem' }} />
                    {seriesLabels.map(({ label, color }) => (
                      <Bar
                        key={label}
                        dataKey={label}
                        stackId="cost"
                        fill={color}
                      />
                    ))}
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}

            {/* Top-10 most-expensive agents */}
            <div className="mt-4">
              <h5 className="mb-3">Top agents by cost</h5>
              {data.top_agents?.length ? (
                <Table hover responsive className="cost-top-table">
                  <thead>
                    <tr>
                      <th>Agent</th>
                      <th className="text-end">Tokens</th>
                      <th className="text-end">Cost</th>
                      <th className="text-end">Invocations</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.top_agents.map((a) => (
                      <tr
                        key={a.id}
                        onClick={() => navigate(`/agents/${a.id}`)}
                        style={{ cursor: 'pointer' }}
                      >
                        <td><strong>{a.name}</strong></td>
                        <td className="text-end">{_intl(a.tokens)}</td>
                        <td className="text-end">{_money(a.cost_usd)}</td>
                        <td className="text-end">{_intl(a.invocations)}</td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              ) : (
                <Alert variant="info" className="py-2" style={{ fontSize: '0.85rem' }}>
                  No agents have any cost in this range yet.
                </Alert>
              )}
            </div>
          </>
        )}
      </div>
    </Layout>
  );
};

export default CostInsightsPage;
