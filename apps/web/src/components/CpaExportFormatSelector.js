import { useEffect, useState } from 'react';
import { Alert, Form, Spinner } from 'react-bootstrap';
import { FaFileInvoiceDollar } from 'react-icons/fa';

import { brandingService } from '../services/branding';

// Keep these in sync with `SUPPORTED_FORMATS` in
// apps/api/app/services/bookkeeper_exporters/registry.py and the
// `cpa_export_format` column added by migration 117.
const FORMAT_OPTIONS = [
  { value: 'xlsx',             label: 'Excel (XLSX) — AAHA-categorized workbook' },
  { value: 'csv',              label: 'Generic CSV — flat AAHA export' },
  { value: 'quickbooks_iif',   label: 'QuickBooks Desktop (IIF)' },
  { value: 'quickbooks_qbo',   label: 'QuickBooks Online (CSV)' },
  { value: 'xero_csv',         label: 'Xero (bank-statement CSV)' },
  { value: 'sage_intacct_csv', label: 'Sage Intacct (GL CSV)' },
];

const DEFAULT_FORMAT = 'xlsx';


/**
 * CPA-software export-format selector for the Bookkeeper Agent's
 * weekly AAHA-categorized output. AAHA stays canonical; this picks
 * which adapter writes the file the practice's CPA imports.
 *
 * Always renders — every tenant has a Bookkeeper-compatible CPA
 * software, even if it's just "send me an Excel file". Default is
 * XLSX so existing tenants pre-migration-117 keep getting the same
 * file shape they were getting before.
 */
const CpaExportFormatSelector = () => {
  const [currentFormat, setCurrentFormat] = useState(DEFAULT_FORMAT);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [savedAt, setSavedAt] = useState(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const features = await brandingService.getFeatures();
        if (!cancelled) {
          setCurrentFormat(features?.cpa_export_format || DEFAULT_FORMAT);
          setLoading(false);
        }
      } catch (err) {
        if (!cancelled) {
          setError('Could not load CPA export format');
          setLoading(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) return null;

  const handleChange = async (e) => {
    const value = e.target.value;
    setSaving(true);
    setError(null);
    try {
      await brandingService.updateFeatures({ cpa_export_format: value });
      setCurrentFormat(value);
      setSavedAt(Date.now());
    } catch (err) {
      setError('Could not save CPA export format. Please retry.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Alert
      variant="info"
      className="mb-3 d-flex align-items-center justify-content-between flex-wrap gap-2"
      style={{ fontSize: '0.85rem' }}
    >
      <div className="d-flex align-items-center gap-2 flex-grow-1">
        <FaFileInvoiceDollar />
        <span>
          <strong>CPA software</strong> — picks the format the Bookkeeper
          Agent's weekly AAHA-categorized export ships in. AAHA is always
          the source of truth; this only changes the file your CPA imports.
        </span>
      </div>
      <div className="d-flex align-items-center gap-2">
        <Form.Select
          size="sm"
          value={currentFormat}
          onChange={handleChange}
          disabled={saving}
          style={{ minWidth: 280 }}
          aria-label="CPA export format"
        >
          {FORMAT_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>{opt.label}</option>
          ))}
        </Form.Select>
        {saving && <Spinner animation="border" size="sm" />}
        {!saving && savedAt && (
          <small className="text-success">Saved</small>
        )}
      </div>
      {error && (
        <div className="w-100 mt-2 text-danger">
          <small>{error}</small>
        </div>
      )}
    </Alert>
  );
};

export default CpaExportFormatSelector;
