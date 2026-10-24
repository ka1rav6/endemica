import { useCallback, useEffect, useMemo, useState } from 'react';
import { ErrorNotice } from '@/components/ErrorNotice';
import { ComparePanel } from '@/features/ComparePanel';
import { CountryPanel } from '@/features/CountryPanel';
import { DiseaseRail } from '@/features/DiseaseRail';
import { ReportsPanel } from '@/features/ReportsPanel';
import { RiskPanel } from '@/features/RiskPanel';
import { ScenarioControls } from '@/features/ScenarioControls';
import { SourcesPanel } from '@/features/SourcesPanel';
import { SpreadPanel } from '@/features/SpreadPanel';
import { Timeline } from '@/features/Timeline';
import { TopBar } from '@/features/TopBar';
import { WorldMap } from '@/features/WorldMap';
import { useAsync, useDebounced } from '@/hooks/useAsync';
import { formatCount, isStale, relativeAge } from '@/lib/format';
import { DEFAULT_SCENARIO, type ScenarioState, toRiskParams } from '@/lib/scenario';
import { activeCountryEntries, spreadEntries } from '@/lib/spread';
import {
  getCountries,
  getActiveSummary,
  getCountryProfile,
  getDiseaseHistory,
  getDiseaseSpread,
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

type Tab = 'country' | 'spread' | 'risk' | 'compare' | 'assumptions' | 'reports' | 'sources';

const TABS: { id: Tab; label: string }[] = [
  { id: 'country', label: 'Country' },
  { id: 'spread', label: 'Spread' },
  { id: 'risk', label: 'Risk' },
  { id: 'compare', label: 'Compare' },
  { id: 'assumptions', label: 'Assumptions' },
  { id: 'reports', label: 'Reports' },
  { id: 'sources', label: 'Sources' },
];

const MAX_DATA_AGE_DAYS = 7;
const ACTIVE_WINDOW_DAYS = 90;

export default function App() {
  const [selectedIso3, setSelectedIso3] = useState<string | null>(null);
  const [comparisonIso3, setComparisonIso3] = useState<string | null>(null);
  const [diseaseKey, setDiseaseKey] = useState<string | null>(null);
  const [activeMode, setActiveMode] = useState(false);
  const [yearCeiling, setYearCeiling] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const [showFlows, setShowFlows] = useState(false);
  const [scenario, setScenario] = useState<ScenarioState>(DEFAULT_SCENARIO);
  const [tab, setTab] = useState<Tab>('country');
  const [ingesting, setIngesting] = useState(false);
  const [ingestMessage, setIngestMessage] = useState<string | null>(null);
  const [dataNonce, setDataNonce] = useState(0);

  const debouncedScenario = useDebounced(scenario, 250);

  const health = useAsync((signal) => getHealth(signal), []);
  const countries = useAsync((signal) => getCountries(signal), [dataNonce]);
  const diseases = useAsync((signal) => getDiseaseHistory(signal), [dataNonce]);
  const outbreaks = useAsync((signal) => getOutbreaks({ limit: 60 }, signal), [dataNonce]);
  const pathogens = useAsync((signal) => getPathogens(signal), []);
  const gravity = useAsync((signal) => getGravityModel(signal).catch(() => null), [dataNonce]);
  const runs = useAsync((signal) => getRuns(10, signal), [dataNonce]);
  const sources = useAsync((signal) => getSources(signal), [dataNonce]);
  const active = useAsync((signal) => getActiveSummary(signal), [dataNonce]);

  const spread = useAsync(
    (signal) => (diseaseKey ? getDiseaseSpread(diseaseKey, signal) : Promise.resolve(null)),
    [diseaseKey, dataNonce],
  );

  const profile = useAsync(
    (signal) => (selectedIso3 ? getCountryProfile(selectedIso3, signal) : Promise.resolve(null)),
    [selectedIso3, dataNonce],
  );

  const comparisonProfile = useAsync(
    (signal) =>
      comparisonIso3 ? getCountryProfile(comparisonIso3, signal) : Promise.resolve(null),
    [comparisonIso3, dataNonce],
  );

  const riskParams = useMemo(
    () =>
      activeMode
        ? { ...toRiskParams(debouncedScenario), scope: 'active' }
        : { ...toRiskParams(debouncedScenario), disease_key: diseaseKey ?? undefined },
    [debouncedScenario, diseaseKey, activeMode],
  );

  const risk = useAsync(
    (signal) => (selectedIso3 ? getRisk(selectedIso3, riskParams, signal) : Promise.resolve(null)),
    [selectedIso3, riskParams, dataNonce],
  );

  const comparisonRisk = useAsync(
    (signal) =>
      comparisonIso3 ? getRisk(comparisonIso3, riskParams, signal) : Promise.resolve(null),
    [comparisonIso3, riskParams, dataNonce],
  );

  const routes = useAsync(
    (signal) =>
      selectedIso3 && showFlows
        ? getRoutes({ dest: selectedIso3, limit: 40 }, signal)
        : Promise.resolve(null),
    [selectedIso3, showFlows, dataNonce],
  );

  const countryList = useMemo(() => countries.data?.items ?? [], [countries.data]);
  const diseaseList = useMemo(() => diseases.data ?? [], [diseases.data]);

  // Open on the country named by the newest report, so the first screen shows
  // a live outbreak rather than whichever country sorts first alphabetically.
  useEffect(() => {
    if (selectedIso3 !== null || countryList.length === 0) return;
    // Wait for the report list, otherwise the country table lands first and
    // the pick falls back to whichever country sorts first alphabetically.
    if (outbreaks.loading && outbreaks.error === null) return;
    const newest = (outbreaks.data?.items ?? []).find((report) => report.countries.length > 0);
    const known = newest?.countries.find((iso3) =>
      countryList.some((country) => country.iso3 === iso3),
    );
    const withOutbreak = countryList.find((country) => country.has_reported_outbreak);
    setSelectedIso3(known ?? withOutbreak?.iso3 ?? countryList[0]?.iso3 ?? null);
  }, [countryList, outbreaks.data, outbreaks.loading, outbreaks.error, selectedIso3]);

  const activeRisk =
    risk.data && selectedIso3 && risk.data.destination_iso3 === selectedIso3 ? risk.data : null;

  // With no disease chosen, follow the one the selected country actually
  // reports, so the map and the panels never disagree about the subject.
  const effectiveDiseaseKey = diseaseKey ?? activeRisk?.pathogen.disease_key ?? null;
  const effectiveDiseaseName =
    spread.data?.disease_name ??
    diseaseList.find((entry) => entry.disease_key === effectiveDiseaseKey)?.disease_name ??
    activeRisk?.pathogen.disease_name ??
    null;

  const followed = useAsync(
    (signal) =>
      !diseaseKey && effectiveDiseaseKey
        ? getDiseaseSpread(effectiveDiseaseKey, signal)
        : Promise.resolve(null),
    [diseaseKey, effectiveDiseaseKey, dataNonce],
  );

  const activeSpread = diseaseKey ? spread.data : followed.data;
  const timelinePoints = activeMode ? [] : (activeSpread?.timeline ?? []);

  useEffect(() => {
    setYearCeiling(null);
    setPlaying(false);
  }, [effectiveDiseaseKey]);

  const activeKeys = useMemo(
    () => new Set((active.data?.diseases ?? []).map((disease) => disease.disease_key)),
    [active.data],
  );

  const activeEntries = useMemo(
    () => activeCountryEntries(active.data?.countries ?? []),
    [active.data],
  );

  const mapSpread = useMemo(
    () => (activeMode ? activeEntries : spreadEntries(activeSpread?.countries ?? [], yearCeiling)),
    [activeMode, activeEntries, activeSpread, yearCeiling],
  );

  const originIso3 = useMemo(
    () => new Set((activeRisk?.importation.top_origins ?? []).map((origin) => origin.origin_iso3)),
    [activeRisk],
  );

  // Corridors that carry risk are the point, but a destination with no usable
  // origin would otherwise draw nothing at all, so fall back to its busiest
  // inbound routes. The map marks which ones currently carry a disease.
  const relevantRoutes = useMemo(() => {
    const inbound = (routes.data?.items ?? []).filter((route) => route.dest_iso3 === selectedIso3);
    const carrying = inbound.filter((route) => originIso3.has(route.origin_iso3));
    return carrying.length > 0 ? carrying : inbound.slice(0, 12);
  }, [routes.data, originIso3, selectedIso3]);

  const handleCountryClick = useCallback((iso3: string, additive: boolean) => {
    if (additive) {
      setComparisonIso3((current) => (current === iso3 ? null : iso3));
      setTab('compare');
      return;
    }
    setSelectedIso3(iso3);
  }, []);

  const handleIngest = useCallback(() => {
    setIngesting(true);
    setIngestMessage(null);
    triggerIngest(40, false)
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

  const staleSources = (activeRisk?.data ?? []).filter((entry) =>
    isStale(entry.retrieved_at, MAX_DATA_AGE_DAYS),
  );

  const establishmentEstimable = activeRisk?.pathogen.establishment_estimable ?? true;
  const selectedCountry = countryList.find((country) => country.iso3 === selectedIso3);

  return (
    <div className="app">
      <TopBar
        countries={countryList}
        selectedIso3={selectedIso3}
        onSelect={setSelectedIso3}
        diseases={diseaseList}
        selectedDiseaseKey={diseaseKey}
        onSelectDisease={setDiseaseKey}
        health={health.data}
        showFlows={showFlows}
        onToggleFlows={() => {
          setShowFlows((value) => !value);
        }}
        onIngest={handleIngest}
        ingesting={ingesting}
      />

      <div className="app__body">
        <DiseaseRail
          diseases={diseaseList}
          selectedKey={effectiveDiseaseKey}
          onSelect={(key) => {
            setActiveMode(false);
            setDiseaseKey(key === diseaseKey ? null : key);
          }}
          loading={diseases.loading}
          activeWindowDays={active.data?.window_days ?? ACTIVE_WINDOW_DAYS}
          activeMode={activeMode}
          onActiveMode={(on) => {
            setActiveMode(on);
            if (on) setDiseaseKey(null);
          }}
          activeKeys={activeKeys}
        />

        <div className="app__stage">
          <WorldMap
            countries={countryList}
            selectedIso3={selectedIso3}
            comparisonIso3={comparisonIso3}
            onSelect={handleCountryClick}
            spread={mapSpread}
            diseaseName={
              activeMode
                ? `${active.data?.disease_count ?? 0} active diseases`
                : effectiveDiseaseName
            }
            activeMode={activeMode}
            yearCeiling={activeMode ? null : yearCeiling}
            origins={activeRisk?.importation.top_origins ?? []}
            routes={relevantRoutes}
            showFlows={showFlows}
          />
          <Timeline
            points={timelinePoints}
            year={yearCeiling}
            onYearChange={setYearCeiling}
            playing={playing}
            onPlayingChange={setPlaying}
            diseaseName={effectiveDiseaseName}
          />
        </div>

        <div className="panel">
          <div className="panel__head">
            <span className="panel__crumb">
              {selectedCountry?.region ?? 'Destination'}
              {comparisonIso3 && <span className="chip chip--accent">comparing 2</span>}
            </span>
            <h1 className="panel__name">
              {selectedCountry?.name ?? 'Select a country'}
              {(selectedCountry?.diseases?.length ?? 0) > 0 && (
                <span className="chip chip--live">
                  <span className="dot dot--pulse" aria-hidden="true" />
                  {selectedCountry?.diseases?.length} on record
                </span>
              )}
            </h1>
            <p className="panel__sub">
              {effectiveDiseaseName ? (
                <>
                  Focused on{' '}
                  <strong style={{ color: 'var(--accent)' }}>{effectiveDiseaseName}</strong>
                  {activeRisk?.pathogen.disease_source === 'destination_record' && !diseaseKey
                    ? ' — the most recent disease reported here.'
                    : '.'}
                </>
              ) : (
                'Pick a disease to focus the map and the estimates.'
              )}
            </p>
          </div>

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

          <div className="panel__scroll">
            {countries.error !== null && (
              <div className="sec">
                <ErrorNotice
                  error={countries.error}
                  onRetry={countries.reload}
                  context="Loading countries"
                />
              </div>
            )}

            {ingestMessage && (
              <div className="sec">
                <div className="warn warn--info">
                  <span>{ingestMessage}</span>
                  <button
                    type="button"
                    className="btn btn--sm btn--ghost"
                    style={{ marginLeft: 'auto' }}
                    onClick={() => {
                      setIngestMessage(null);
                    }}
                  >
                    Dismiss
                  </button>
                </div>
              </div>
            )}

            {staleSources.length > 0 && tab === 'risk' && (
              <div className="sec">
                <div className="warn warn--caution">
                  Showing data older than {MAX_DATA_AGE_DAYS} days:{' '}
                  {staleSources
                    .map((entry) => `${entry.source} (${relativeAge(entry.retrieved_at)})`)
                    .join(', ')}
                  . Refresh with <code>just data-refresh</code>.
                </div>
              </div>
            )}

            {tab === 'country' && (
              <>
                {profile.error !== null && (
                  <div className="sec">
                    <ErrorNotice
                      error={profile.error}
                      onRetry={profile.reload}
                      context="Loading the country record"
                    />
                  </div>
                )}
                <CountryPanel
                  profile={profile.data}
                  loading={profile.loading}
                  focusDiseaseKey={effectiveDiseaseKey}
                  onSelectDisease={setDiseaseKey}
                />
              </>
            )}

            {tab === 'spread' && (
              <>
                {spread.error !== null && (
                  <div className="sec">
                    <ErrorNotice
                      error={spread.error}
                      onRetry={spread.reload}
                      context="Loading the spread history"
                    />
                  </div>
                )}
                <SpreadPanel
                  spread={activeSpread}
                  loading={spread.loading || followed.loading}
                  yearCeiling={yearCeiling}
                  selectedIso3={selectedIso3}
                  onSelectCountry={setSelectedIso3}
                />
              </>
            )}

            {tab === 'risk' && (
              <>
                {risk.loading && !activeRisk && (
                  <div className="sec" style={{ display: 'flex', gap: 9, alignItems: 'center' }}>
                    <span className="spinner" />
                    <span style={{ color: 'var(--ink-3)' }}>Computing risk…</span>
                  </div>
                )}
                {risk.error !== null && !activeRisk && (
                  <div className="sec">
                    <ErrorNotice
                      error={risk.error}
                      onRetry={risk.reload}
                      context="Computing risk"
                    />
                  </div>
                )}
                {activeRisk && <RiskPanel risk={activeRisk} />}
                {!risk.loading && !activeRisk && risk.error === null && (
                  <p className="empty">Choose a destination to see its risk breakdown.</p>
                )}
              </>
            )}

            {tab === 'compare' && (
              <ComparePanel
                a={{ profile: profile.data, risk: activeRisk }}
                b={{ profile: comparisonProfile.data, risk: comparisonRisk.data }}
                countries={countryList}
                onPick={setComparisonIso3}
                onClear={() => {
                  setComparisonIso3(null);
                }}
              />
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
                  <div className="sec">
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
              <>
                <div className="sec">
                  <div className="stats">
                    <div className="stat">
                      <span className="stat__label">Diseases</span>
                      <span className="stat__value num">{diseaseList.length}</span>
                    </div>
                    <div className="stat">
                      <span className="stat__label">Reports</span>
                      <span className="stat__value num">
                        {formatCount(
                          diseaseList.reduce((total, entry) => total + entry.report_count, 0),
                        )}
                      </span>
                    </div>
                    <div className="stat">
                      <span className="stat__label">Countries</span>
                      <span className="stat__value num">{countryList.length}</span>
                    </div>
                  </div>
                </div>
                <SourcesPanel
                  sources={sources.data?.items ?? []}
                  gravity={gravity.data}
                  runs={runs.data ?? []}
                />
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
