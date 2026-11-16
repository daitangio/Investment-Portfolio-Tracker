"use client";

import { useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import { useAccounts } from "@/lib/hooks/usePortfolio";
import { formatAUD, formatCurrency, formatDate } from "@/lib/utils/formatters";
import {
  Upload,
  CheckCircle,
  XCircle,
  Loader2,
  FileText,
} from "lucide-react";
import clsx from "clsx";

interface IspTrade {
  import_hash: string;
  ordine: string;
  isin: string;
  description: string;
  transaction_type: string;
  asset_class: string;
  quantity: number;
  price_per_unit: number | null;
  fees: number;
  net_amount: number;
  currency: string;
  executed_at: string | null;
  settled_at: string | null;
  fx_rate_to_aud: number | null;
  net_amount_aud: number | null;
  price_per_unit_aud: number | null;
  duplicate: boolean;
}

interface IspTradePreview {
  total_trades: number;
  duplicates: number;
  trades: IspTrade[];
}

interface IspTradeConfirmResponse {
  saved: number;
  skipped_duplicates: number;
}

export default function IspTradePanel() {
  const fileRef = useRef<HTMLInputElement>(null);
  const [accountId, setAccountId] = useState("");
  const [preview, setPreview] = useState<IspTradePreview | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [confirmed, setConfirmed] = useState<IspTradeConfirmResponse | null>(null);
  const { data: accounts } = useAccounts();

  const uploadMutation = useMutation({
    mutationFn: async (file: File) => {
      const form = new FormData();
      form.append("file", file);
      if (accountId) form.append("account_id", accountId);
      const { data } = await api.post("/isp-import/trades/upload", form, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      return data as IspTradePreview;
    },
    onSuccess: (data) => {
      setPreview(data);
      setSelected(new Set(data.trades.map((t) => t.import_hash)));
      setConfirmed(null);
    },
  });

  const confirmMutation = useMutation({
    mutationFn: async () => {
      if (!preview) return null;
      const { data } = await api.post("/isp-import/trades/confirm", {
        account_id: accountId,
        import_hashes: [...selected],
        trades: preview.trades,
      });
      return data as IspTradeConfirmResponse;
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
      selected.size === preview.trades.length
        ? new Set()
        : new Set(preview.trades.map((t) => t.import_hash)),
    );
  };

  return (
    <div className="card-glass p-6 space-y-4">
      <div>
        <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wider flex items-center gap-2">
          <FileText className="w-4 h-4" /> Intesa Sanpaolo — trade confirmations (PDF)
        </h2>
        <p className="text-xs text-gray-500 mt-1">
          Import a &quot;Conferma Operazioni in Titoli&quot; PDF (one trade per page).
          Each trade becomes a BUY or SELL transaction with EUR→AUD enrichment at
          the execution date.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
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
            Choose .pdf…
          </button>
          <input
            ref={fileRef}
            type="file"
            accept=".pdf"
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
          Not an Intesa trade-confirmation PDF, or parsing failed.
        </div>
      )}

      {preview && !confirmed && (
        <>
          <div className="flex flex-wrap gap-4 text-sm text-gray-400">
            <span>
              Trades: <span className="text-gray-200 font-medium">{preview.total_trades}</span>
            </span>
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
                        preview.trades.length > 0 &&
                        selected.size === preview.trades.length
                      }
                      onChange={toggleAll}
                      className="accent-blue-500"
                    />
                  </th>
                  <th className="px-3 py-2 text-left text-xs text-gray-500 font-medium">Date</th>
                  <th className="px-3 py-2 text-left text-xs text-gray-500 font-medium">Type</th>
                  <th className="px-3 py-2 text-left text-xs text-gray-500 font-medium">ISIN</th>
                  <th className="px-3 py-2 text-left text-xs text-gray-500 font-medium">Description</th>
                  <th className="px-3 py-2 text-right text-xs text-gray-500 font-medium">Qty</th>
                  <th className="px-3 py-2 text-right text-xs text-gray-500 font-medium">Price</th>
                  <th className="px-3 py-2 text-right text-xs text-gray-500 font-medium">Fees</th>
                  <th className="px-3 py-2 text-right text-xs text-gray-500 font-medium">Net EUR</th>
                  <th className="px-3 py-2 text-right text-xs text-gray-500 font-medium">Net AUD</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800/50">
                {preview.trades.map((t) => (
                  <tr
                    key={t.import_hash}
                    onClick={() => toggleRow(t.import_hash)}
                    className={clsx(
                      "cursor-pointer transition-colors",
                      selected.has(t.import_hash)
                        ? "bg-blue-500/5 hover:bg-blue-500/10"
                        : "opacity-50 hover:opacity-70",
                    )}
                  >
                    <td className="px-3 py-2">
                      <input
                        type="checkbox"
                        checked={selected.has(t.import_hash)}
                        onChange={() => toggleRow(t.import_hash)}
                        onClick={(e) => e.stopPropagation()}
                        className="accent-blue-500"
                      />
                    </td>
                    <td className="px-3 py-2 text-gray-400 whitespace-nowrap text-xs">
                      {t.executed_at ? formatDate(t.executed_at) : "—"}
                    </td>
                    <td className="px-3 py-2">
                      <span
                        className={clsx(
                          "text-xs font-medium px-1.5 py-0.5 rounded",
                          t.transaction_type === "BUY"
                            ? "bg-green-500/10 text-green-400"
                            : "bg-red-500/10 text-red-400",
                        )}
                      >
                        {t.transaction_type}
                      </span>
                    </td>
                    <td className="px-3 py-2 font-mono text-xs text-gray-400">{t.isin}</td>
                    <td className="px-3 py-2 text-gray-200 max-w-xs truncate">
                      {t.description}
                      {t.duplicate && (
                        <span className="ml-2 text-xs text-yellow-400">dup</span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-xs">
                      {t.quantity.toLocaleString("en-US")}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-xs">
                      {t.price_per_unit !== null
                        ? formatCurrency(t.price_per_unit, false, "EUR")
                        : "—"}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-xs">
                      {formatCurrency(t.fees, false, "EUR")}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-xs">
                      {formatCurrency(t.net_amount, false, "EUR")}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-xs">
                      {t.net_amount_aud !== null ? formatAUD(t.net_amount_aud) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="flex items-center justify-between">
            <p className="text-xs text-gray-500">
              <span className="text-gray-200 font-medium">{selected.size}</span> of{" "}
              {preview.trades.length} trades selected
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
              Import trades
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
            Trades imported:{" "}
            <span className="text-green-400 font-medium">{confirmed.saved}</span> saved
            {confirmed.skipped_duplicates > 0 && (
              <span className="text-gray-500">
                · {confirmed.skipped_duplicates} duplicates skipped
              </span>
            )}
          </p>
          <button
            onClick={() => {
              setPreview(null);
              setConfirmed(null);
              if (fileRef.current) fileRef.current.value = "";
            }}
            className="btn-secondary text-sm mt-2"
          >
            Import another PDF
          </button>
        </div>
      )}
    </div>
  );
}
