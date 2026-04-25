import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { CircleDollarSign, RefreshCw, SendHorizonal } from 'lucide-react';
import './styles.css';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

function formatINR(paise) {
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
  }).format((paise || 0) / 100);
}

function statusClass(status) {
  return {
    pending: 'bg-amber-100 text-amber-900 ring-amber-200',
    processing: 'bg-sky-100 text-sky-900 ring-sky-200',
    completed: 'bg-emerald-100 text-emerald-900 ring-emerald-200',
    failed: 'bg-rose-100 text-rose-900 ring-rose-200',
  }[status] || 'bg-slate-100 text-slate-700 ring-slate-200';
}

function App() {
  const [merchantId, setMerchantId] = useState('1');
  const [dashboard, setDashboard] = useState(null);
  const [amountRupees, setAmountRupees] = useState('');
  const [bankAccountId, setBankAccountId] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  async function loadDashboard(signal) {
    const response = await fetch(`${API_BASE_URL}/api/v1/dashboard`, {
      headers: { 'X-Merchant-Id': merchantId },
      signal,
    });
    if (!response.ok) throw new Error('Unable to load dashboard');
    const data = await response.json();
    setDashboard(data);
    if (!bankAccountId && data.bank_accounts.length) {
      setBankAccountId(String(data.bank_accounts[0].id));
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    setError('');
    loadDashboard(controller.signal).catch((err) => {
      if (err.name !== 'AbortError') setError(err.message);
    });
    const interval = setInterval(() => {
      loadDashboard(controller.signal).catch(() => {});
    }, 3000);
    return () => {
      controller.abort();
      clearInterval(interval);
    };
  }, [merchantId]);

  const ledgerRows = useMemo(() => dashboard?.recent_ledger || [], [dashboard]);
  const payouts = useMemo(() => dashboard?.payouts || [], [dashboard]);

  async function submitPayout(event) {
    event.preventDefault();
    setError('');
    setSubmitting(true);
    const amountPaise = Math.round(Number(amountRupees) * 100);
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/payouts`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Merchant-Id': merchantId,
          'Idempotency-Key': crypto.randomUUID(),
        },
        body: JSON.stringify({
          amount_paise: amountPaise,
          bank_account_id: Number(bankAccountId),
        }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || 'Payout request failed');
      setAmountRupees('');
      await loadDashboard();
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="min-h-screen bg-zinc-50 text-zinc-950">
      <header className="border-b border-zinc-200 bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-4">
          <div className="flex items-center gap-3">
            <CircleDollarSign className="h-7 w-7 text-emerald-700" />
            <div>
              <h1 className="text-xl font-semibold">Playto Payout Engine</h1>
              <p className="text-sm text-zinc-500">{dashboard?.merchant?.name || 'Loading merchant'}</p>
            </div>
          </div>
          <select
            className="h-10 rounded-md border border-zinc-300 bg-white px-3 text-sm"
            value={merchantId}
            onChange={(event) => {
              setMerchantId(event.target.value);
              setBankAccountId('');
            }}
          >
            <option value="1">Merchant 1</option>
            <option value="2">Merchant 2</option>
            <option value="3">Merchant 3</option>
          </select>
        </div>
      </header>

      <div className="mx-auto grid max-w-6xl gap-5 px-4 py-6 lg:grid-cols-[1fr_360px]">
        <section className="space-y-5">
          <div className="grid gap-4 sm:grid-cols-3">
            <Balance label="Available" value={dashboard?.balances?.available_paise} />
            <Balance label="Held" value={dashboard?.balances?.held_paise} />
            <Balance label="Total liability" value={dashboard?.balances?.total_paise} />
          </div>

          <Panel title="Payout History" action={<RefreshCw className="h-4 w-4 text-zinc-500" />}>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[680px] text-left text-sm">
                <thead className="border-b border-zinc-200 text-xs uppercase text-zinc-500">
                  <tr>
                    <th className="py-3">Payout</th>
                    <th>Amount</th>
                    <th>Status</th>
                    <th>Attempts</th>
                    <th>Bank</th>
                    <th>Created</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-100">
                  {payouts.map((payout) => (
                    <tr key={payout.id}>
                      <td className="py-3 font-mono text-xs text-zinc-600">{payout.id.slice(0, 8)}</td>
                      <td className="font-medium">{formatINR(payout.amount_paise)}</td>
                      <td>
                        <span className={`rounded-full px-2 py-1 text-xs ring-1 ${statusClass(payout.status)}`}>
                          {payout.status}
                        </span>
                      </td>
                      <td>{payout.attempts}</td>
                      <td>{payout.bank_account.masked_account_number}</td>
                      <td>{new Date(payout.created_at).toLocaleString()}</td>
                    </tr>
                  ))}
                  {!payouts.length && (
                    <tr>
                      <td className="py-6 text-zinc-500" colSpan="6">No payouts yet.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </Panel>

          <Panel title="Recent Ledger">
            <div className="divide-y divide-zinc-100">
              {ledgerRows.map((entry) => (
                <div className="grid gap-2 py-3 text-sm sm:grid-cols-[150px_1fr_130px_130px]" key={entry.id}>
                  <span className="font-medium">{entry.entry_type.replaceAll('_', ' ')}</span>
                  <span className="text-zinc-600">{entry.description}</span>
                  <span>{formatINR(entry.available_delta_paise)}</span>
                  <span>{formatINR(entry.held_delta_paise)} held</span>
                </div>
              ))}
            </div>
          </Panel>
        </section>

        <aside>
          <Panel title="Request Payout">
            <form className="space-y-4" onSubmit={submitPayout}>
              <label className="block text-sm font-medium">
                Amount in rupees
                <input
                  className="mt-2 h-11 w-full rounded-md border border-zinc-300 px-3"
                  min="1"
                  step="0.01"
                  type="number"
                  value={amountRupees}
                  onChange={(event) => setAmountRupees(event.target.value)}
                  required
                />
              </label>
              <label className="block text-sm font-medium">
                Bank account
                <select
                  className="mt-2 h-11 w-full rounded-md border border-zinc-300 bg-white px-3"
                  value={bankAccountId}
                  onChange={(event) => setBankAccountId(event.target.value)}
                  required
                >
                  {(dashboard?.bank_accounts || []).map((account) => (
                    <option key={account.id} value={account.id}>
                      {account.bank_name} {account.masked_account_number}
                    </option>
                  ))}
                </select>
              </label>
              {error && <p className="rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-800">{error}</p>}
              <button
                className="flex h-11 w-full items-center justify-center gap-2 rounded-md bg-emerald-700 px-4 text-sm font-semibold text-white disabled:opacity-60"
                disabled={submitting}
                type="submit"
              >
                <SendHorizonal className="h-4 w-4" />
                {submitting ? 'Submitting' : 'Submit payout'}
              </button>
            </form>
          </Panel>
        </aside>
      </div>
    </main>
  );
}

function Balance({ label, value }) {
  return (
    <div className="rounded-lg border border-zinc-200 bg-white p-4">
      <div className="text-sm text-zinc-500">{label}</div>
      <div className="mt-2 text-2xl font-semibold">{formatINR(value)}</div>
    </div>
  );
}

function Panel({ title, action, children }) {
  return (
    <section className="rounded-lg border border-zinc-200 bg-white p-4">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-base font-semibold">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

createRoot(document.getElementById('root')).render(<App />);
