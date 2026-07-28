"use client";

/**
 * Superadmin configuration of AI providers, routing and spend.
 *
 * Three sections, in the order the decisions are actually made: what endpoints
 * exist, which feature uses which, and what that has cost.
 *
 * No field on this page accepts an API key, and none can display one. The form
 * collects the *name* of an environment variable; the value is read at the moment
 * of use and never travels to the browser. `key_present` is a boolean, which is
 * how the page can show that a provider is usable without being able to reveal
 * why.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState, type FormEvent } from "react";

import { api, ApiError, type Response } from "@/lib/api";
import { formatNumber } from "@/lib/format";

type Provider = Response<"/admin/ai/providers", "get">[number];
type Route = Response<"/admin/ai/routing", "get">[number];
type Usage = Response<"/admin/ai/usage", "get">[number];
type TestResult = Response<"/admin/ai/providers/{provider_id}/test", "post">;

const FEATURES = ["ask", "insight", "command", "import"] as const;
const EFFORTS = ["low", "medium", "high", "xhigh", "max"] as const;

export function AiView({ locale }: { locale: string }) {
  const t = useTranslations("admin.ai");

  return (
    <div className="space-y-12">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-text">{t("title")}</h1>
        <p className="mt-1 text-sm text-muted">{t("intro")}</p>
      </div>

      <Providers />
      <Routing />
      <UsageTable locale={locale} />
    </div>
  );
}

// ── Providers ───────────────────────────────────────────────────────────────

function Providers() {
  const t = useTranslations("admin.ai");
  const tError = useTranslations("error");
  const tAction = useTranslations("action");
  const tStats = useTranslations("stats");
  const queryClient = useQueryClient();
  const [adding, setAdding] = useState(false);
  const [code, setCode] = useState<string | null>(null);

  const providers = useQuery({
    queryKey: ["admin", "ai", "providers"],
    queryFn: () => api<Provider[]>("/admin/ai/providers"),
  });

  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: ["admin", "ai"] });

  const create = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api("/admin/ai/providers", { method: "POST", body }),
    onSuccess: () => {
      setAdding(false);
      setCode(null);
      void refresh();
    },
    onError: (error) => setCode(error instanceof ApiError ? error.code : "NETWORK_ERROR"),
  });

  const toggle = useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) =>
      api(`/admin/ai/providers/${id}`, { method: "PATCH", body: { is_enabled: enabled } }),
    onSuccess: refresh,
  });

  const remove = useMutation({
    mutationFn: (id: number) => api(`/admin/ai/providers/${id}`, { method: "DELETE" }),
    onSuccess: refresh,
  });

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setCode(null);
    create.mutate({
      name: String(data.get("name") ?? ""),
      kind: String(data.get("kind") ?? "openai_compatible"),
      default_model: String(data.get("default_model") ?? ""),
      // Empty means "the vendor default", which the API stores as null. Sending
      // "" would be stored as a URL and produce a confusing relative-path error.
      base_url: String(data.get("base_url") ?? "") || null,
      api_key_env: String(data.get("api_key_env") ?? ""),
      is_third_party_pool: data.get("is_third_party_pool") === "on",
    });
  }

  const rows = providers.data ?? [];

  return (
    <section>
      <div className="flex items-center justify-between gap-4">
        <h2 className="text-lg font-medium text-text">{t("providers")}</h2>
        <button
          type="button"
          onClick={() => setAdding((current) => !current)}
          className="rounded-lg border border-line px-3 py-1.5 text-sm text-muted transition-colors hover:text-text"
        >
          {adding ? tAction("cancel") : t("addProvider")}
        </button>
      </div>

      {adding && (
        <form
          onSubmit={onSubmit}
          className="mt-4 grid gap-4 rounded-xl border border-line bg-surface p-6 sm:grid-cols-2"
        >
          <Text name="name" label={t("name")} placeholder="openrouter" />
          <label className="block">
            <span className="block text-sm text-muted">{t("kind")}</span>
            <select
              name="kind"
              defaultValue="openai_compatible"
              className="mt-1.5 w-full rounded-lg border border-line bg-bg px-3 py-2 text-sm text-text outline-none focus-visible:border-brand"
            >
              <option value="openai_compatible">OpenAI-compatible</option>
              <option value="anthropic">Anthropic</option>
            </select>
          </label>
          <Text name="default_model" label={t("defaultModel")} placeholder="claude-opus-5" />
          <Text
            name="base_url"
            label={t("baseUrl")}
            placeholder="https://openrouter.ai/api/v1"
            required={false}
          />
          <div className="sm:col-span-2">
            <Text
              name="api_key_env"
              label={t("keyEnv")}
              placeholder="OPENROUTER_API_KEY"
              required={false}
              hint={t("keyEnvHint")}
            />
          </div>

          <label className="flex items-center gap-2 text-sm text-muted sm:col-span-2">
            <input type="checkbox" name="is_third_party_pool" className="accent-[var(--brand-primary)]" />
            {t("thirdParty")}
          </label>

          {code && (
            <p role="alert" className="rounded-lg bg-fail-bg px-3 py-2 text-sm text-fail sm:col-span-2">
              {tError(code as "unknown")}
            </p>
          )}

          <div className="sm:col-span-2">
            <button
              type="submit"
              disabled={create.isPending}
              className="rounded-lg bg-brand px-4 py-2 text-sm font-medium text-brand-contrast transition-opacity hover:opacity-90 disabled:opacity-60"
            >
              {tAction("save")}
            </button>
          </div>
        </form>
      )}

      <ul className="mt-4 space-y-3">
        {rows.map((provider) => (
          <ProviderCard
            key={provider.id}
            provider={provider}
            onToggle={(enabled) => toggle.mutate({ id: provider.id, enabled })}
            onDelete={() => remove.mutate(provider.id)}
          />
        ))}
        {providers.isPending && <li className="text-sm text-subtle">…</li>}
        {!providers.isPending && rows.length === 0 && (
          <li className="rounded-xl border border-dashed border-line px-6 py-8 text-center text-sm text-subtle">
            {tStats("noData")}
          </li>
        )}
      </ul>
    </section>
  );
}

function ProviderCard({
  provider,
  onToggle,
  onDelete,
}: {
  provider: Provider;
  onToggle: (enabled: boolean) => void;
  onDelete: () => void;
}) {
  const t = useTranslations("admin.ai");
  const tError = useTranslations("error");
  const tAction = useTranslations("action");
  const [result, setResult] = useState<TestResult | null>(null);

  const test = useMutation({
    mutationFn: () => api<TestResult>(`/admin/ai/providers/${provider.id}/test`, { method: "POST" }),
    onSuccess: setResult,
  });

  return (
    <li className="rounded-xl border border-line bg-surface p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="flex items-center gap-2 text-base font-medium text-text">
            {provider.name}
            <span className="rounded bg-bg-subtle px-1.5 py-0.5 text-xs font-normal text-subtle">
              {provider.kind}
            </span>
          </h3>
          <p className="numeric mt-1 truncate text-xs text-subtle">
            {provider.default_model}
            {provider.base_url && ` · ${provider.base_url}`}
          </p>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <button
            type="button"
            onClick={() => test.mutate()}
            disabled={test.isPending}
            className="rounded-lg border border-line px-3 py-1.5 text-sm text-muted transition-colors hover:text-text disabled:opacity-60"
          >
            {test.isPending ? t("testing") : t("test")}
          </button>
          <button
            type="button"
            onClick={() => onToggle(!provider.is_enabled)}
            className={`rounded-lg px-3 py-1.5 text-sm transition-colors ${
              provider.is_enabled
                ? "bg-pass-bg text-pass"
                : "border border-line text-subtle hover:text-text"
            }`}
          >
            {provider.is_enabled ? t("enabled") : t("disabled")}
          </button>
          <button
            type="button"
            onClick={onDelete}
            aria-label={tAction("delete")}
            className="rounded-lg px-2 py-1.5 text-sm text-subtle transition-colors hover:text-fail"
          >
            ×
          </button>
        </div>
      </div>

      <p className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
        <span className="numeric text-subtle">{provider.api_key_env || "—"}</span>
        {/* A boolean, not a value. The page can say a key exists; it has no way to
            show one, because the server never sends it. */}
        <span className={provider.key_present ? "text-pass" : "text-warn"}>
          {provider.key_present ? t("keyPresent") : t("keyMissing")}
        </span>
      </p>

      {provider.is_third_party_pool && (
        // Not a footnote. This provider forwards student records to parties whose
        // retention terms nobody has read.
        <p
          role="note"
          className="mt-3 rounded-lg border border-warn/40 bg-warn-bg px-3 py-2 text-xs leading-relaxed text-warn"
        >
          {t("thirdPartyWarning")}
        </p>
      )}

      {result && (
        <p
          role="status"
          className={`mt-3 rounded-lg px-3 py-2 text-xs ${
            result.ok ? "bg-pass-bg text-pass" : "bg-fail-bg text-fail"
          }`}
        >
          {tError(result.code as "unknown")}
          {result.ok && ` (${result.detail})`}
        </p>
      )}
    </li>
  );
}

// ── Routing ─────────────────────────────────────────────────────────────────

function Routing() {
  const t = useTranslations("admin.ai");
  const queryClient = useQueryClient();

  const providers = useQuery({
    queryKey: ["admin", "ai", "providers"],
    queryFn: () => api<Provider[]>("/admin/ai/providers"),
  });

  const routing = useQuery({
    queryKey: ["admin", "ai", "routing"],
    queryFn: () => api<Route[]>("/admin/ai/routing"),
  });

  const save = useMutation({
    mutationFn: ({ feature, body }: { feature: string; body: Record<string, unknown> }) =>
      api(`/admin/ai/routing/${feature}`, { method: "PUT", body }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin", "ai", "routing"] }),
  });

  const byFeature = new Map((routing.data ?? []).map((route) => [route.feature, route]));
  const usable = (providers.data ?? []).filter((provider) => provider.is_enabled);

  return (
    <section>
      <h2 className="text-lg font-medium text-text">{t("routing")}</h2>
      <p className="mt-1 text-sm text-muted">{t("routingIntro")}</p>

      <div className="mt-4 space-y-3">
        {FEATURES.map((feature) => {
          const current = byFeature.get(feature);
          return (
            <div
              key={feature}
              className="grid gap-3 rounded-xl border border-line bg-surface p-4 sm:grid-cols-[1fr_1fr_1fr_auto] sm:items-end"
            >
              <p className="text-sm font-medium text-text sm:self-center">
                {t(`feature.${feature}`)}
              </p>

              <label className="block">
                <span className="block text-xs text-subtle">{t("providers")}</span>
                <select
                  value={current?.provider_id ?? ""}
                  onChange={(event) =>
                    save.mutate({
                      feature,
                      body: {
                        provider_id: Number(event.target.value),
                        model: current?.model ?? "",
                        effort: current?.effort ?? "medium",
                      },
                    })
                  }
                  className="mt-1 w-full rounded-lg border border-line bg-bg px-2 py-1.5 text-sm text-text outline-none focus-visible:border-brand"
                >
                  <option value="">—</option>
                  {usable.map((provider) => (
                    <option key={provider.id} value={provider.id}>
                      {provider.name}
                    </option>
                  ))}
                </select>
              </label>

              <label className="block">
                <span className="block text-xs text-subtle">{t("model")}</span>
                <input
                  defaultValue={current?.model ?? ""}
                  placeholder={t("modelDefault")}
                  disabled={!current}
                  onBlur={(event) =>
                    current &&
                    event.target.value !== current.model &&
                    save.mutate({
                      feature,
                      body: {
                        provider_id: current.provider_id,
                        model: event.target.value,
                        effort: current.effort,
                      },
                    })
                  }
                  className="numeric mt-1 w-full rounded-lg border border-line bg-bg px-2 py-1.5 text-sm text-text outline-none focus-visible:border-brand disabled:opacity-50"
                />
              </label>

              <label className="block">
                <span className="block text-xs text-subtle">{t("effort")}</span>
                <select
                  value={current?.effort ?? "medium"}
                  disabled={!current}
                  onChange={(event) =>
                    current &&
                    save.mutate({
                      feature,
                      body: {
                        provider_id: current.provider_id,
                        model: current.model,
                        effort: event.target.value,
                      },
                    })
                  }
                  className="mt-1 w-full rounded-lg border border-line bg-bg px-2 py-1.5 text-sm text-text outline-none focus-visible:border-brand disabled:opacity-50"
                >
                  {EFFORTS.map((effort) => (
                    <option key={effort} value={effort}>
                      {effort}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          );
        })}
      </div>
    </section>
  );
}

// ── Usage ───────────────────────────────────────────────────────────────────

function UsageTable({ locale }: { locale: string }) {
  const t = useTranslations("admin.ai");
  const tStats = useTranslations("stats");

  const usage = useQuery({
    queryKey: ["admin", "ai", "usage"],
    queryFn: () => api<Usage[]>("/admin/ai/usage", { query: { days: 30 } }),
  });

  const rows = usage.data ?? [];

  return (
    <section>
      <h2 className="text-lg font-medium text-text">{t("usage")}</h2>
      <p className="mt-1 text-sm text-muted">{t("usageIntro")}</p>

      <div className="mt-4 overflow-x-auto rounded-xl border border-line bg-surface">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-subtle">
              <th scope="col" className="px-4 py-2.5 font-medium">{t("day")}</th>
              <th scope="col" className="px-4 py-2.5 font-medium">{t("featureLabel")}</th>
              <th scope="col" className="px-4 py-2.5 font-medium">{t("model")}</th>
              <th scope="col" className="px-4 py-2.5 text-end font-medium">{t("calls")}</th>
              <th scope="col" className="px-4 py-2.5 text-end font-medium">{t("tokensIn")}</th>
              <th scope="col" className="px-4 py-2.5 text-end font-medium">{t("tokensOut")}</th>
              <th scope="col" className="px-4 py-2.5 text-end font-medium">{t("cost")}</th>
              <th scope="col" className="px-4 py-2.5 text-end font-medium">{t("errors")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={`${row.day}-${row.feature}-${row.model}`} className="border-b border-line last:border-0">
                <td className="numeric px-4 py-2.5 text-muted">{row.day}</td>
                <td className="px-4 py-2.5 text-text">
                  {t(`feature.${row.feature}` as "feature.ask")}
                </td>
                <td className="numeric px-4 py-2.5 text-muted">{row.model}</td>
                <td className="numeric px-4 py-2.5 text-end text-text">
                  {formatNumber(row.calls, locale)}
                </td>
                <td className="numeric px-4 py-2.5 text-end text-muted">
                  {formatNumber(row.input_tokens, locale)}
                </td>
                <td className="numeric px-4 py-2.5 text-end text-muted">
                  {formatNumber(row.output_tokens, locale)}
                </td>
                <td className="numeric px-4 py-2.5 text-end text-muted">
                  ${row.cost_estimate.toFixed(2)}
                </td>
                <td
                  className={`numeric px-4 py-2.5 text-end ${
                    row.errors > 0 ? "text-fail" : "text-subtle"
                  }`}
                >
                  {formatNumber(row.errors, locale)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {!usage.isPending && rows.length === 0 && (
          <p className="px-4 py-8 text-center text-sm text-subtle">{tStats("noData")}</p>
        )}
      </div>
    </section>
  );
}

function Text({
  name,
  label,
  placeholder,
  required = true,
  hint,
}: {
  name: string;
  label: string;
  placeholder?: string;
  required?: boolean;
  hint?: string;
}) {
  return (
    <label className="block">
      <span className="block text-sm text-muted">{label}</span>
      <input
        name={name}
        placeholder={placeholder}
        required={required}
        className="numeric mt-1.5 w-full rounded-lg border border-line bg-bg px-3 py-2 text-sm text-text outline-none focus-visible:border-brand focus-visible:ring-2 focus-visible:ring-brand/30"
      />
      {hint && <span className="mt-1 block text-xs text-subtle">{hint}</span>}
    </label>
  );
}
