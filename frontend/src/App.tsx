import { useCallback, useEffect, useMemo, useState } from 'react';
import { ErrorNotice } from '@/components/ErrorNotice';
import { ReportsPanel } from '@/features/ReportsPanel';
import { RiskPanel } from '@/features/RiskPanel';
import { ScenarioControls } from '@/features/ScenarioControls';
import { DEFAULT_SCENARIO, type ScenarioState, toRiskParams } from '@/lib/scenario';
import { SourcesPanel } from '@/features/SourcesPanel';
import { TopBar } from '@/features/TopBar';
import { WorldMap } from '@/features/WorldMap';
import { useAsync, useDebounced } from '@/hooks/useAsync';
import { isStale, relativeAge } from '@/lib/format';
import {
  getCountries,
  getGravityModel,
  getHealth,
  getOutbreaks,
  getPathogens,
  getRisk,
  getRoutes,
  getRuns,
  getSources,
  triggerIngest,
} from '@/services/epiroute';

type Tab = 'risk' | 'assumptions' | 'reports' | 'sources';

const TABS: { id: Tab; label: string }[] = [
  { id: 'risk', label: 'Risk' },
  { id: 'assumptions', label: 'Assumptions' },
  { id: 'reports', label: 'Reports' },
  { id: 'sources', label: 'Sources' },
];

const MAX_DATA_AGE_DAYS = 7;

export default function App() {
  const [selectedIso3, setSelectedIso3] = useState<string | null>(null);
  const [scenario, setScenario] = useState<ScenarioState>(DEFAULT_SCENARIO);
  const [tab, setTab] = useState<Tab>('risk');
  const [ingesting, setIngesting] = useState(false);
  const [ingestMessage, setIngestMessage] = useState<string | null>(null);
  const [dataNonce, setDataNonce] = useState(0);

  const debouncedScenario = useDebounced(scenario, 250);

  const health = useAsync((signal) => getHealth(signal), []);
  const countries = useAsync((signal) => getCountries(signal), [dataNonce]);
  const outbreaks = useAsync((signal) => getOutbreaks({ limit: 50 }, signal), [dataNonce]);
  const pathogens = useAsync((signal) => getPathogens(signal), []);
  const gravity = useAsync((signal) => getGravityModel(signal).catch(() => null), [dataNonce]);
  const runs = useAsync((signal) => getRuns(10, signal), [dataNonce]);
  const sources = useAsync((signal) => getSources(signal), [dataNonce]);

  const risk = useAsync(
    (signal) =>
      selectedIso3
        ? getRisk(selectedIso3, toRiskParams(debouncedScenario), signal)
        : Promise.resolve(null),
    [selectedIso3, debouncedScenario, dataNonce],
  );

  const routes = useAsync(
    (signal) =>
      selectedIso3 ? getRoutes({ dest: selectedIso3, limit: 40 }, signal) : Promise.resolve(null),
    [selectedIso3, dataNonce],
  );

  const countryList = useMemo(() => countries.data?.items ?? [], [countries.data]);

  useEffect(() => {
    if (selectedIso3 !== null || countryList.length === 0) return;
    const withOutbreak = countryList.find((country) => country.has_reported_outbreak);
    setSelectedIso3(withOutbreak?.iso3 ?? countryList[0]?.iso3 ?? null);
  }, [countryList, selectedIso3]);

  const originIso3 = useMemo(
    () => new Set((risk.data?.importation.top_origins ?? []).map((origin) => origin.origin_iso3)),
    [risk.data],
  );

  const relevantRoutes = useMemo(
    () => (routes.data?.items ?? []).filter((route) => originIso3.has(route.origin_iso3)),
    [routes.data, originIso3],
  );

  const handleIngest = useCallback(() => {
    setIngesting(true);
    setIngestMessage(null);
    triggerIngest(20, false)
      .then((result) => {
        setIngestMessage(
          `Run ${result.status}: ${result.records_created} new and ${result.records_updated} updated report(s), ` +
            `${result.observations_created} grounded observation(s) stored via ${result.mode}.`,
        );
        setDataNonce((value) => value + 1);
      })
      .catch((cause: unknown) => {
        setIngestMessage(
          cause instanceof Error
            ? `Ingestion failed: ${cause.message}. Previously stored records are unaffected.`
            : 'Ingestion failed. Previously stored records are unaffected.',
        );
      })
      .finally(() => {
        setIngesting(false);
      });
  }, []);

  const staleSources = (risk.data?.data ?? []).filter((entry) =>
    isStale(entry.retrieved_at, MAX_DATA_AGE_DAYS),
  );

  const establishmentEstimable = risk.data?.pathogen.establishment_estimable ?? true;

  return (
    <div className="app">
      <TopBar
        countries={countryList}
        selectedIso3={selectedIso3}
        onSelect={setSelectedIso3}
        health={health.data}
        onIngest={handleIngest}
        ingesting={ingesting}
      />

      {staleSources.length > 0 && (
        <div className="stalebar" role="status">
          <span>⚠</span>
          <span>
            Showing data older than {MAX_DATA_AGE_DAYS} days:{' '}
            {staleSources
              .map((entry) => `${entry.source} (${relativeAge(entry.retrieved_at)})`)
              .join(', ')}
            . Refresh with <code>just data-refresh</code> and <code>just data-ingest</code>.
          </span>
        </div>
      )}

      {ingestMessage && (
        <div className="stalebar" role="status" style={{ background: 'var(--bg-raised)' }}>
          <span>{ingestMessage}</span>
          <button
            type="button"
            className="button"
            style={{ marginLeft: 'auto', padding: '2px 8px' }}
            onClick={() => {
              setIngestMessage(null);
            }}
          >
            Dismiss
          </button>
        </div>
      )}

      <div className="app__body">
        <WorldMap
          countries={countryList}
          selectedIso3={selectedIso3}
          onSelect={setSelectedIso3}
          origins={risk.data?.importation.top_origins ?? []}
          routes={relevantRoutes}
        />

        <div className="panel">
          <div className="tabs" role="tablist" aria-label="Detail panels">
            {TABS.map((entry) => (
              <button
                key={entry.id}
                type="button"
                role="tab"
                className="tab"
                aria-selected={tab === entry.id}
                onClick={() => {
                  setTab(entry.id);
                }}
              >
                {entry.label}
              </button>
            ))}
          </div>

          {countries.error !== null && (
            <div className="panel__section">
              <ErrorNotice
                error={countries.error}
                onRetry={countries.reload}
                context="Loading countries"
              />
            </div>
          )}

          {tab === 'risk' && (
            <>
              {risk.loading && !risk.data && (
                <div className="panel__section" style={{ display: 'flex', gap: 8 }}>
                  <div className="spinner" />
                  <span style={{ color: 'var(--text-muted)' }}>Computing risk…</span>
                </div>
              )}
              {risk.error !== null && (
                <div className="panel__section">
                  <ErrorNotice error={risk.error} onRetry={risk.reload} context="Computing risk" />
                </div>
              )}
              {risk.data && <RiskPanel risk={risk.data} />}
              {!risk.loading && !risk.data && risk.error === null && (
                <div className="panel__section">
                  <p className="empty">Choose a destination to see its risk breakdown.</p>
                </div>
              )}
            </>
          )}

          {tab === 'assumptions' && (
            <ScenarioControls
              state={scenario}
              onChange={setScenario}
              pathogens={pathogens.data ?? []}
              establishmentEstimable={establishmentEstimable}
            />
          )}

          {tab === 'reports' && (
            <>
              {outbreaks.error !== null && (
                <div className="panel__section">
                  <ErrorNotice
                    error={outbreaks.error}
                    onRetry={outbreaks.reload}
                    context="Loading reports"
                  />
                </div>
              )}
              <ReportsPanel
                reports={outbreaks.data?.items ?? []}
                onCountrySelect={setSelectedIso3}
              />
            </>
          )}

          {tab === 'sources' && (
            <SourcesPanel
              sources={sources.data?.items ?? []}
              gravity={gravity.data}
              runs={runs.data ?? []}
            />
          )}
        </div>
      </div>
    </div>
  );
}
