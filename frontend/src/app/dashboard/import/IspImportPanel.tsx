"use client";

import { useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import { useAccounts } from "@/lib/hooks/usePortfolio";
import { formatAUD, formatCurrency } from "@/lib/utils/formatters";
import {
  Upload,
  CheckCircle,
  XCircle,
  Loader2,
  Landmark,
} from "lucide-react";
import clsx from "clsx";

interface IspHolding {
  import_hash: string;
  isin: string;
  description: string;
  asset_class: string;
  quantity: number;
  price_per_unit: number | null;
  market_price_per_unit: number | null;
  market_value: number;
  currency: string;
  fx_rate_to_aud: number | null;
  price_per_unit_aud: number | null;
  market_value_aud: number | null;
  duplicate: boolean;
}

interface IspPreview {
  deposit_account: string | null;
  grand_total_eur: number | null;
  total_rows: number;
  duplicates: number;
  fx_rate_to_aud: number | null;
  cash_eur: number;
  cash_aud: number | null;
  cash_hash: string;
  holdings: IspHolding[];
}

interface IspConfirmResponse {
  saved: number;
  skipped_duplicates: number;
  deleted_stale: number;
}

const todayIso = () => new Date().toISOString().slice(0, 10);

export default function IspImportPanel() {
  const fileRef = useRef<HTMLInputElement>(null);
  const [accountId, setAccountId] = useState("");
  const [asOf, setAsOf] = useState(todayIso());
  const [preview, setPreview] = useState<IspPreview | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [confirmed, setConfirmed] = useState<IspConfirmResponse | null>(null);
  const { data: accounts } = useAccounts();

  const uploadMutation = useMutation({
    mutationFn: async (file: File) => {
      const form = new FormData();
      form.append("file", file);
      form.append("as_of", asOf);
      if (accountId) form.append("account_id", accountId);
      const { data } = await api.post("/isp-import/upload", form, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      return data as IspPreview;
    },
    onSuccess: (data) => {
      setPreview(data);
      setSelected(new Set(data.holdings.map((h) => h.import_hash)));
      setConfirmed(null);
    },
  });

  const confirmMutation = useMutation({
    mutationFn: async () => {
      if (!preview) return null;
      const { data } = await api.post("/isp-import/confirm", {
        account_id: accountId,
        as_of: asOf,
        import_hashes: [...selected, preview.cash_hash],
        cash_hash: preview.cash_hash,
        cash_eur: preview.cash_eur,
        cash_aud: preview.cash_aud,
        fx_rate_to_aud: preview.fx_rate_to_aud,
        holdings: preview.holdings,
      });
      return data as IspConfirmResponse;
    },
    onSuccess: (data) => {
      if (data) setConfirmed(data);
    },
  });

  const toggleRow = (hash: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(hash)) next.delete(hash);
      else next.add(hash);
      return next;
    });
  };

  const toggleAll = () => {
    if (!preview) return;
    setSelected(
      selected.size === preview.holdings.length
        ? new Set()
        : new Set(preview.holdings.map((h) => h.import_hash)),
    );
  };

  return (
    <div className="card-glass p-6 space-y-4">
      <div>
        <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wider flex items-center gap-2">
          <Landmark className="w-4 h-4" /> Intesa Sanpaolo — patrimonio.xlsx
        </h2>
        <p className="text-xs text-gray-500 mt-1">
          Import a holdings snapshot (positions + cash). Each position becomes an
          opening-balance lot at its average fiscal price; confirming replaces the
          account&apos;s previous Intesa snapshot.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div>
          <label className="block text-xs text-gray-400 mb-1">Destination account</label>
          <select
            value={accountId}
            onChange={(e) => setAccountId(e.target.value)}
            className="w-full bg-gray-800 border border-gray-700 text-gray-200 rounded-lg px-3 py-2 text-sm"
          >
            <option value="">Select account…</option>
            {(accounts ?? []).map((a: { id: string; name: string }) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs text-gray-400 mb-1">As-of date</label>
          <input
            type="date"
            value={asOf}
            max={todayIso()}
            onChange={(e) => setAsOf(e.target.value)}
            className="w-full bg-gray-800 border border-gray-700 text-gray-200 rounded-lg px-3 py-2 text-sm"
          />
        </div>
        <div>
          <label className="block text-xs text-gray-400 mb-1">File</label>
          <button
            onClick={() => fileRef.current?.click()}
            disabled={uploadMutation.isPending}
            className="w-full btn-secondary flex items-center justify-center gap-2 text-sm"
          >
            {uploadMutation.isPending ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Upload className="w-4 h-4" />
            )}
            Choose .xlsx…
          </button>
          <input
            ref={fileRef}
            type="file"
            accept=".xlsx,.xls"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) uploadMutation.mutate(file);
            }}
          />
        </div>
      </div>

      {uploadMutation.isError && (
        <div className="flex items-center gap-2 text-red-400 text-sm">
          <XCircle className="w-4 h-4" />
          Not an Intesa patrimonio file, or parsing failed.
        </div>
      )}

      {preview && !confirmed && (
        <>
          <div className="flex flex-wrap gap-4 text-sm text-gray-400">
            {preview.deposit_account && (
              <span>
                Account: <span className="text-gray-200">{preview.deposit_account}</span>
              </span>
            )}
            <span>
              Holdings: <span className="text-gray-200 font-medium">{preview.holdings.length}</span>
            </span>
            <span>
              Cash:{" "}
              <span className="text-gray-200 font-medium">
                {formatCurrency(preview.cash_eur, false, "EUR")}
              </span>{" "}
              ({preview.cash_aud !== null ? formatAUD(preview.cash_aud) : "—"})
            </span>
            {preview.fx_rate_to_aud !== null && (
              <span className="text-xs text-gray-500">
                EUR→AUD {preview.fx_rate_to_aud.toFixed(4)}
              </span>
            )}
            {preview.duplicates > 0 && (
              <span className="text-yellow-400 text-xs">
                {preview.duplicates} already imported
              </span>
            )}
          </div>

          <div className="overflow-x-auto border border-gray-800 rounded-lg">
            <table className="w-full text-sm">
              <thead className="bg-gray-900/50">
                <tr>
                  <th className="px-3 py-2 text-left w-8">
                    <input
                      type="checkbox"
                      checked={
                        preview.holdings.length > 0 &&
                        selected.size === preview.holdings.length
                      }
                      onChange={toggleAll}
                      className="accent-blue-500"
                    />
                  </th>
                  <th className="px-3 py-2 text-left text-xs text-gray-500 font-medium">ISIN</th>
                  <th className="px-3 py-2 text-left text-xs text-gray-500 font-medium">Description</th>
                  <th className="px-3 py-2 text-left text-xs text-gray-500 font-medium">Class</th>
                  <th className="px-3 py-2 text-right text-xs text-gray-500 font-medium">Qty</th>
                  <th className="px-3 py-2 text-right text-xs text-gray-500 font-medium">Cost/unit</th>
                  <th className="px-3 py-2 text-right text-xs text-gray-500 font-medium">Mkt value</th>
                  <th className="px-3 py-2 text-right text-xs text-gray-500 font-medium">AUD value</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800/50">
                {preview.holdings.map((h) => (
                  <tr
                    key={h.import_hash}
                    onClick={() => toggleRow(h.import_hash)}
                    className={clsx(
                      "cursor-pointer transition-colors",
                      selected.has(h.import_hash)
                        ? "bg-blue-500/5 hover:bg-blue-500/10"
                        : "opacity-50 hover:opacity-70",
                    )}
                  >
                    <td className="px-3 py-2">
                      <input
                        type="checkbox"
                        checked={selected.has(h.import_hash)}
                        onChange={() => toggleRow(h.import_hash)}
                        onClick={(e) => e.stopPropagation()}
                        className="accent-blue-500"
                      />
                    </td>
                    <td className="px-3 py-2 font-mono text-xs text-gray-400">{h.isin}</td>
                    <td className="px-3 py-2 text-gray-200 max-w-xs truncate">
                      {h.description}
                      {h.duplicate && (
                        <span className="ml-2 text-xs text-yellow-400">dup</span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-xs text-gray-400">{h.asset_class}</td>
                    <td className="px-3 py-2 text-right font-mono text-xs">
                      {h.quantity.toLocaleString("en-US")}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-xs">
                      {h.price_per_unit !== null
                        ? formatCurrency(h.price_per_unit, false, "EUR")
                        : "—"}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-xs">
                      {formatCurrency(h.market_value, false, "EUR")}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-xs">
                      {h.market_value_aud !== null ? formatAUD(h.market_value_aud) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="flex items-center justify-between">
            <p className="text-xs text-gray-500">
              <span className="text-gray-200 font-medium">{selected.size}</span> of{" "}
              {preview.holdings.length} positions selected (cash always included). Lots are
              dated {asOf}; the ATO CGT discount applies after 365 days.
            </p>
            <button
              onClick={() => confirmMutation.mutate()}
              disabled={selected.size === 0 || confirmMutation.isPending || !accountId}
              className="btn-primary flex items-center gap-2 disabled:opacity-40"
            >
              {confirmMutation.isPending ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <CheckCircle className="w-4 h-4" />
              )}
              Import snapshot
            </button>
          </div>
          {!accountId && (
            <p className="text-xs text-yellow-400">
              Select a destination account to enable import.
            </p>
          )}
        </>
      )}

      {confirmed && (
        <div className="border border-green-500/20 bg-green-500/5 rounded-lg p-4 space-y-1">
          <p className="text-sm text-gray-200 flex items-center gap-2">
            <CheckCircle className="w-4 h-4 text-green-400" />
            Snapshot imported:{" "}
            <span className="text-green-400 font-medium">{confirmed.saved}</span> rows saved
            {confirmed.skipped_duplicates > 0 && (
              <span className="text-gray-500">
                · {confirmed.skipped_duplicates} duplicates skipped
              </span>
            )}
            {confirmed.deleted_stale > 0 && (
              <span className="text-gray-500">
                · {confirmed.deleted_stale} stale positions removed
              </span>
            )}
          </p>
          <p className="text-xs text-gray-500">
            Positions are dated {asOf} at their average fiscal price; CGT discount
            applies after 365 days.
          </p>
          <button
            onClick={() => {
              setPreview(null);
              setConfirmed(null);
              if (fileRef.current) fileRef.current.value = "";
            }}
            className="btn-secondary text-sm mt-2"
          >
            Import another file
          </button>
        </div>
      )}
    </div>
  );
}
