import { useEffect, useMemo, useRef, useState } from 'react';
import {
  AttributionControl,
  GeoJSONSource,
  Map as MapLibreMap,
  NavigationControl,
  Popup,
  setWorkerUrl,
  type ExpressionSpecification,
  type MapLayerMouseEvent,
} from 'maplibre-gl';
import maplibreWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker?url';
import 'maplibre-gl/dist/maplibre-gl.css';

setWorkerUrl(maplibreWorkerUrl);
import type { Feature, FeatureCollection, LineString, Point as GeoPoint } from 'geojson';
import type { Country, OriginContribution, Route } from '@/types/api';
import type { MapSpreadEntry } from '@/lib/spread';
import { greatCircleLine } from '@/lib/geo';
import { formatCount, formatPassengers } from '@/lib/format';

const API_BOUNDARIES_URL = '/data/country_boundaries.geojson';
const BUNDLED_BOUNDARIES_URL = '/boundaries/countries.geojson';

const C = {
  water: '#060910',
  graticule: '#15202c',
  land: '#1e2a36',
  landQuiet: '#263442',
  outline: '#2f3f4f',
  outlineHover: '#dbe6f0',
  selected: '#2ee6c0',
  /** Earliest to latest arrival. Reads as a time ramp, not a severity ramp. */
  ramp: ['#ff6b7a', '#ff9f6b', '#ffd166', '#8fd98a', '#58a6ff', '#9f86ff'],
  arcObserved: '#2ee6c0',
  arcEstimated: '#58a6ff',
} as const;

interface Props {
  countries: Country[];
  selectedIso3: string | null;
  comparisonIso3: string | null;
  onSelect: (iso3: string, additive: boolean) => void;
  spread: MapSpreadEntry[];
  diseaseName: string | null;
  yearCeiling: number | null;
  origins: OriginContribution[];
  routes: Route[];
  showFlows: boolean;
}

interface BoundaryCollection {
  type: 'FeatureCollection';
  features: {
    type: 'Feature';
    id?: string;
    properties: Record<string, unknown>;
    geometry: unknown;
  }[];
}

function arcFeatures(
  routes: Route[],
  origins: OriginContribution[],
): FeatureCollection<LineString> {
  const rateByOrigin = new Map(origins.map((origin) => [origin.origin_iso3, origin]));
  const maxRate = Math.max(...origins.map((origin) => origin.arrival_rate_per_day), Number.EPSILON);

  const features: Feature<LineString>[] = [];
  for (const route of routes) {
    const { origin_lat: oLat, origin_lon: oLon, dest_lat: dLat, dest_lon: dLon } = route;
    if (oLat === null || oLon === null || dLat === null || dLon === null) continue;
    const contribution = rateByOrigin.get(route.origin_iso3);
    const share = contribution ? contribution.arrival_rate_per_day / maxRate : 0;
    features.push({
      type: 'Feature',
      properties: {
        originName: route.origin_name,
        destName: route.dest_name,
        passengers: route.passengers_per_day,
        valueType: route.value_type,
        source: route.source,
        width: 1.1 + share * 4.2,
      },
      geometry: {
        type: 'LineString',
        coordinates: greatCircleLine({ lat: oLat, lon: oLon }, { lat: dLat, lon: dLon }),
      },
    });
  }
  return { type: 'FeatureCollection', features };
}

function markerFeatures(
  countries: Country[],
  entries: MapSpreadEntry[],
  limit: number,
): FeatureCollection<GeoPoint> {
  const byIso3 = new Map(countries.map((country) => [country.iso3, country]));
  const features: Feature<GeoPoint>[] = [];
  for (const entry of entries.slice(0, limit)) {
    const country = byIso3.get(entry.iso3);
    if (!country || country.centroid_lat === null || country.centroid_lon === null) continue;
    features.push({
      type: 'Feature',
      properties: { label: String(entry.arrivalOrder), iso3: entry.iso3 },
      geometry: { type: 'Point', coordinates: [country.centroid_lon, country.centroid_lat] },
    });
  }
  return { type: 'FeatureCollection', features };
}

function pointFor(country: Country | undefined): FeatureCollection<GeoPoint> {
  if (!country || country.centroid_lat === null || country.centroid_lon === null) {
    return { type: 'FeatureCollection', features: [] };
  }
  return {
    type: 'FeatureCollection',
    features: [
      {
        type: 'Feature',
        properties: { iso3: country.iso3 },
        geometry: { type: 'Point', coordinates: [country.centroid_lon, country.centroid_lat] },
      },
    ],
  };
}

function graticule(): FeatureCollection<LineString> {
  const features: Feature<LineString>[] = [];
  for (let lon = -180; lon <= 180; lon += 20) {
    const coordinates: [number, number][] = [];
    for (let lat = -84; lat <= 84; lat += 6) coordinates.push([lon, lat]);
    features.push({
      type: 'Feature',
      properties: {},
      geometry: { type: 'LineString', coordinates },
    });
  }
  for (let lat = -60; lat <= 60; lat += 20) {
    features.push({
      type: 'Feature',
      properties: {},
      geometry: {
        type: 'LineString',
        coordinates: [
          [-180, lat],
          [0, lat],
          [180, lat],
        ],
      },
    });
  }
  return { type: 'FeatureCollection', features };
}

async function loadBoundaries(): Promise<BoundaryCollection> {
  try {
    const response = await fetch(API_BOUNDARIES_URL, { signal: AbortSignal.timeout(5000) });
    if (response.ok) {
      const data = (await response.json()) as BoundaryCollection;
      if (Array.isArray(data.features) && data.features.length > 0) return data;
    }
  } catch {
    // Processed boundaries are optional; the bundled Natural Earth layer still draws.
  }
  const response = await fetch(BUNDLED_BOUNDARIES_URL);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const data = (await response.json()) as BoundaryCollection;
  if (!Array.isArray(data.features) || data.features.length === 0) {
    throw new Error('boundary file was empty');
  }
  return data;
}

function node(tag: string, text: string, style?: Partial<CSSStyleDeclaration>): HTMLElement {
  const element = document.createElement(tag);
  element.textContent = text;
  if (style) Object.assign(element.style, style);
  return element;
}

function routePopup(properties: Record<string, unknown>): HTMLElement {
  const root = document.createElement('div');
  root.append(
    node('strong', `${String(properties['originName'])} → ${String(properties['destName'])}`),
    node(
      'div',
      `${formatPassengers(Number(properties['passengers']))} · ${String(properties['valueType'])}`,
    ),
    node('div', `source: ${String(properties['source'])}`, {
      color: '#74889e',
      fontSize: '10.5px',
    }),
  );
  return root;
}

const fillColour: ExpressionSpecification = [
  'case',
  ['boolean', ['feature-state', 'selected'], false],
  C.selected,
  ['boolean', ['feature-state', 'affected'], false],
  [
    'interpolate',
    ['linear'],
    ['coalesce', ['feature-state', 'order'], 0],
    0,
    C.ramp[0],
    0.2,
    C.ramp[1],
    0.4,
    C.ramp[2],
    0.6,
    C.ramp[3],
    0.8,
    C.ramp[4],
    1,
    C.ramp[5],
  ],
  ['boolean', ['feature-state', 'hasAnyReport'], false],
  C.landQuiet,
  C.land,
];

export function WorldMap({
  countries,
  selectedIso3,
  comparisonIso3,
  onSelect,
  spread,
  diseaseName,
  yearCeiling,
  origins,
  routes,
  showFlows,
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const flewTo = useRef<string | null>(null);
  const [ready, setReady] = useState(false);
  const [boundaryError, setBoundaryError] = useState<string | null>(null);
  const selectRef = useRef(onSelect);
  selectRef.current = onSelect;

  const byIso3 = useMemo(() => new Map(countries.map((c) => [c.iso3, c])), [countries]);
  const spreadByIso3 = useMemo(() => new Map(spread.map((e) => [e.iso3, e])), [spread]);
  const selected = selectedIso3 ? byIso3.get(selectedIso3) : undefined;
  const spreadRef = useRef(spreadByIso3);
  spreadRef.current = spreadByIso3;
  const diseaseRef = useRef(diseaseName);
  diseaseRef.current = diseaseName;

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const container = containerRef.current;
    let cancelled = false;

    const map = new MapLibreMap({
      container,
      style: {
        version: 8,
        sources: {},
        layers: [{ id: 'bg', type: 'background', paint: { 'background-color': C.water } }],
      },
      center: [12, 22],
      zoom: 1.5,
      minZoom: 0.9,
      maxZoom: 7,
      attributionControl: false,
      renderWorldCopies: true,
      fadeDuration: 0,
      canvasContextAttributes: { antialias: true },
    });
    mapRef.current = map;

    map.addControl(
      new NavigationControl({ showCompass: false, visualizePitch: false }),
      'top-right',
    );
    map.addControl(
      new AttributionControl({
        compact: true,
        customAttribution:
          'Boundaries © Natural Earth · Reports © WHO Disease Outbreak News · Arcs are great circles between centroids.',
      }),
      'bottom-right',
    );

    const popup = new Popup({
      closeButton: false,
      closeOnClick: false,
      offset: 11,
      maxWidth: '260px',
    });
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    let raf = 0;

    const observer = new ResizeObserver(() => {
      map.resize();
    });
    observer.observe(container);

    // A hidden tab or panel stops the render loop, and the canvas can come
    // back empty. Re-measure and force one frame when the page is shown again.
    const onVisible = () => {
      if (document.visibilityState !== 'visible') return;
      map.resize();
      map.triggerRepaint();
    };
    document.addEventListener('visibilitychange', onVisible);

    const animate = (now: number) => {
      if (cancelled) return;
      if (map.getLayer('arc-modelled')) {
        const phase = (now / 950) % 1;
        map.setPaintProperty('arc-modelled', 'line-dasharray', [
          0.25 + phase,
          1.15,
          1.35 - phase,
          1.15,
        ]);
      }
      if (map.getLayer('pin-halo')) {
        const wave = (Math.sin(now / 760) + 1) / 2;
        map.setPaintProperty('pin-halo', 'circle-radius', 8 + wave * 15);
        map.setPaintProperty('pin-halo', 'circle-opacity', 0.3 * (1 - wave * 0.75));
      }
      raf = requestAnimationFrame(animate);
    };

    let started = false;
    const start = () => {
      if (started || cancelled) return;
      started = true;
      void (async () => {
        try {
          const data = await loadBoundaries();
          if (cancelled) return;

          map.addSource('graticule', { type: 'geojson', data: graticule() });
          map.addLayer({
            id: 'graticule-lines',
            type: 'line',
            source: 'graticule',
            paint: { 'line-color': C.graticule, 'line-width': 0.6, 'line-opacity': 0.8 },
          });

          map.addSource('countries', { type: 'geojson', data: data as never, promoteId: 'iso3' });
          map.addLayer({
            id: 'country-fill',
            type: 'fill',
            source: 'countries',
            paint: {
              'fill-color': fillColour,
              'fill-opacity': [
                'case',
                ['boolean', ['feature-state', 'hover'], false],
                1,
                ['boolean', ['feature-state', 'affected'], false],
                0.92,
                0.78,
              ] as ExpressionSpecification,
            },
          });
          map.addLayer({
            id: 'country-outline',
            type: 'line',
            source: 'countries',
            paint: {
              'line-color': [
                'case',
                ['boolean', ['feature-state', 'selected'], false],
                '#d6fff6',
                ['boolean', ['feature-state', 'compared'], false],
                '#ffd166',
                ['boolean', ['feature-state', 'hover'], false],
                C.outlineHover,
                C.outline,
              ] as ExpressionSpecification,
              'line-width': [
                'case',
                ['boolean', ['feature-state', 'selected'], false],
                2.1,
                ['boolean', ['feature-state', 'compared'], false],
                1.9,
                ['boolean', ['feature-state', 'hover'], false],
                1.2,
                0.45,
              ] as ExpressionSpecification,
            },
          });

          map.addSource('arcs', {
            type: 'geojson',
            data: { type: 'FeatureCollection', features: [] },
          });
          map.addLayer({
            id: 'arc-glow',
            type: 'line',
            source: 'arcs',
            layout: { 'line-cap': 'round', 'line-join': 'round' },
            paint: {
              'line-color': [
                'match',
                ['get', 'valueType'],
                'observed',
                C.arcObserved,
                C.arcEstimated,
              ] as ExpressionSpecification,
              'line-width': ['*', ['get', 'width'], 3.2] as ExpressionSpecification,
              'line-opacity': 0.22,
              'line-blur': 5,
            },
          });
          map.addLayer({
            id: 'arc-observed',
            type: 'line',
            source: 'arcs',
            filter: ['==', ['get', 'valueType'], 'observed'],
            layout: { 'line-cap': 'round', 'line-join': 'round' },
            paint: {
              'line-color': C.arcObserved,
              'line-width': ['get', 'width'] as ExpressionSpecification,
              'line-opacity': 0.9,
            },
          });
          map.addLayer({
            id: 'arc-modelled',
            type: 'line',
            source: 'arcs',
            filter: ['!=', ['get', 'valueType'], 'observed'],
            layout: { 'line-cap': 'round', 'line-join': 'round' },
            paint: {
              'line-color': C.arcEstimated,
              'line-width': ['get', 'width'] as ExpressionSpecification,
              'line-opacity': 0.82,
              'line-dasharray': [0.6, 1.2],
            },
          });

          map.addSource('pin', {
            type: 'geojson',
            data: { type: 'FeatureCollection', features: [] },
          });
          map.addLayer({
            id: 'pin-halo',
            type: 'circle',
            source: 'pin',
            paint: {
              'circle-radius': 11,
              'circle-color': C.selected,
              'circle-opacity': 0.26,
              'circle-blur': 0.4,
            },
          });
          map.addLayer({
            id: 'pin-core',
            type: 'circle',
            source: 'pin',
            paint: {
              'circle-radius': 4.5,
              'circle-color': '#eafff9',
              'circle-stroke-width': 2,
              'circle-stroke-color': C.selected,
            },
          });

          map.addSource('order', {
            type: 'geojson',
            data: { type: 'FeatureCollection', features: [] },
          });
          map.addLayer({
            id: 'order-labels',
            type: 'symbol',
            source: 'order',
            layout: {
              'text-field': ['get', 'label'],
              'text-size': 10,
              'text-allow-overlap': false,
              'text-font': ['Noto Sans Regular'],
            },
            paint: {
              'text-color': '#06121a',
              'text-halo-color': '#f4fffc',
              'text-halo-width': 1.6,
            },
          });

          let hoveredId: string | null = null;
          const clearHover = () => {
            if (hoveredId) {
              map.setFeatureState({ source: 'countries', id: hoveredId }, { hover: false });
              hoveredId = null;
            }
            popup.remove();
            map.getCanvas().style.cursor = '';
          };

          map.on('mousemove', 'country-fill', (event: MapLayerMouseEvent) => {
            const properties: unknown = event.features?.[0]?.properties;
            if (typeof properties !== 'object' || properties === null) return;
            const record = properties as Record<string, unknown>;
            const iso3 = record['iso3'];
            if (typeof iso3 !== 'string' || !iso3) return;
            if (hoveredId && hoveredId !== iso3) {
              map.setFeatureState({ source: 'countries', id: hoveredId }, { hover: false });
            }
            hoveredId = iso3;
            map.setFeatureState({ source: 'countries', id: iso3 }, { hover: true });
            map.getCanvas().style.cursor = 'pointer';

            const name =
              typeof record['name'] === 'string' && record['name'] ? record['name'] : iso3;
            const entry = spreadRef.current.get(iso3);
            const root = document.createElement('div');
            root.append(node('strong', name));
            if (entry) {
              root.append(
                node(
                  'div',
                  `${diseaseRef.current ?? 'Reported'} · arrived ${entry.firstYear ?? 'unknown'} (#${entry.arrivalOrder})`,
                  { color: '#2ee6c0', fontSize: '11px', marginTop: '2px' },
                ),
                node(
                  'div',
                  `${formatCount(entry.cases)} cases · ${formatCount(entry.deaths)} deaths · ${entry.reportCount} report${entry.reportCount === 1 ? '' : 's'}`,
                  { color: '#a8bacd', fontSize: '10.5px' },
                ),
              );
            } else {
              root.append(
                node('div', `No ${diseaseRef.current ?? 'outbreak'} report on file`, {
                  color: '#74889e',
                  fontSize: '10.5px',
                  marginTop: '2px',
                }),
              );
            }
            root.append(
              node('div', 'Click to open its full record', {
                color: '#4f6377',
                fontSize: '10px',
                marginTop: '3px',
              }),
            );
            popup.setLngLat(event.lngLat).setDOMContent(root).addTo(map);
          });
          map.on('mouseleave', 'country-fill', clearHover);
          map.on('click', 'country-fill', (event: MapLayerMouseEvent) => {
            const properties: unknown = event.features?.[0]?.properties;
            if (typeof properties !== 'object' || properties === null) return;
            const iso3 = (properties as Record<string, unknown>)['iso3'];
            if (typeof iso3 !== 'string' || !iso3) return;
            // Shift-click adds the second side of the comparison.
            const additive = event.originalEvent.shiftKey || event.originalEvent.metaKey;
            selectRef.current(iso3, additive);
          });

          const showArc = (event: MapLayerMouseEvent) => {
            const properties = event.features?.[0]?.properties;
            if (!properties) return;
            map.getCanvas().style.cursor = 'pointer';
            popup.setLngLat(event.lngLat).setDOMContent(routePopup(properties)).addTo(map);
          };
          map.on('mousemove', 'arc-observed', showArc);
          map.on('mousemove', 'arc-modelled', showArc);

          if (!reducedMotion) raf = requestAnimationFrame(animate);
          map.resize();
          setReady(true);
        } catch (cause) {
          if (cancelled) return;
          setBoundaryError(
            cause instanceof Error
              ? `Country boundaries could not be loaded (${cause.message}).`
              : 'Country boundaries could not be loaded.',
          );
        }
      })();
    };

    const boot = () => {
      if (cancelled || started) return;
      if (map.isStyleLoaded()) start();
      else map.once('styledata', boot);
    };
    boot();

    return () => {
      cancelled = true;
      cancelAnimationFrame(raf);
      document.removeEventListener('visibilitychange', onVisible);
      observer.disconnect();
      popup.remove();
      map.remove();
      mapRef.current = null;
      setReady(false);
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !map.getSource('countries')) return;
    map.removeFeatureState({ source: 'countries' });
    for (const country of countries) {
      if (country.has_reported_outbreak || (country.diseases?.length ?? 0) > 0) {
        map.setFeatureState({ source: 'countries', id: country.iso3 }, { hasAnyReport: true });
      }
    }
    for (const entry of spread) {
      map.setFeatureState(
        { source: 'countries', id: entry.iso3 },
        { affected: true, order: entry.arrivalShare },
      );
    }
    if (comparisonIso3) {
      map.setFeatureState({ source: 'countries', id: comparisonIso3 }, { compared: true });
    }
    if (selectedIso3) {
      map.setFeatureState({ source: 'countries', id: selectedIso3 }, { selected: true });
    }
  }, [ready, countries, spread, selectedIso3, comparisonIso3]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const source = map.getSource('arcs');
    if (source instanceof GeoJSONSource) {
      void source.setData(
        showFlows ? arcFeatures(routes, origins) : { type: 'FeatureCollection', features: [] },
      );
    }
  }, [ready, routes, origins, showFlows]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const pin = map.getSource('pin');
    if (pin instanceof GeoJSONSource) void pin.setData(pointFor(selected));
    const order = map.getSource('order');
    if (order instanceof GeoJSONSource) void order.setData(markerFeatures(countries, spread, 25));
  }, [ready, countries, spread, selected]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !selected || flewTo.current === selected.iso3) return;
    const { centroid_lat: lat, centroid_lon: lon } = selected;
    if (lat === null || lon === null) return;
    flewTo.current = selected.iso3;
    const camera = {
      center: [lon, lat] as [number, number],
      zoom: Math.max(map.getZoom(), 2.3),
      essential: true,
    };
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) map.jumpTo(camera);
    else map.easeTo({ ...camera, duration: 950 });
  }, [ready, selected]);

  const firstYear = spread.reduce<number | null>(
    (min, entry) =>
      entry.firstYear !== null && (min === null || entry.firstYear < min) ? entry.firstYear : min,
    null,
  );

  return (
    <div className="map">
      <div className="map__canvas" ref={containerRef} data-testid="map-canvas" />

      {boundaryError && (
        <div className="map__status">
          <div>
            <p style={{ maxWidth: 420 }}>{boundaryError}</p>
            <p style={{ color: 'var(--ink-4)', fontSize: 12 }}>
              The disease list, country records and every estimate still work without the map.
            </p>
          </div>
        </div>
      )}

      <div className="map__hud">
        <div className="hud hud--title">
          <span className="hud__kicker">
            {diseaseName ? (
              <>
                <span className="dot" style={{ color: 'var(--accent)' }} aria-hidden="true" />
                Spread of
              </>
            ) : (
              'No disease selected'
            )}
          </span>
          <h2 className="hud__name">{diseaseName ?? 'Pick a disease'}</h2>
          {diseaseName && (
            <dl className="hud__stats">
              <div className="hud__stat">
                <dt>Countries</dt>
                <dd className="num">{spread.length}</dd>
              </div>
              <div className="hud__stat">
                <dt>First seen</dt>
                <dd className="num">{firstYear ?? '—'}</dd>
              </div>
              <div className="hud__stat">
                <dt>Showing</dt>
                <dd className="num">
                  {yearCeiling === null ? 'all years' : <>up to {yearCeiling}</>}
                </dd>
              </div>
            </dl>
          )}
        </div>

        {spread.length > 0 && (
          <div className="hud legend">
            <span className="legend__title">Order of arrival</span>
            <span className="legend__ramp" aria-hidden="true">
              {C.ramp.map((colour) => (
                <i key={colour} style={{ background: colour }} />
              ))}
            </span>
            <span className="legend__scale">
              <span>first</span>
              <span>latest</span>
            </span>
            {showFlows && (
              <>
                <span className="legend__row">
                  <span className="swatch swatch--line" style={{ background: C.arcObserved }} />
                  Observed flow
                </span>
                <span className="legend__row">
                  <span className="swatch swatch--line" style={{ background: C.arcEstimated }} />
                  Modelled flow
                </span>
              </>
            )}
          </div>
        )}
      </div>

      <div className="hud map__hint">
        {spread.length > 0
          ? 'Numbers mark the order countries first reported this disease. Click a country for its record, shift-click to compare two.'
          : 'Click any country to see every disease ever reported there. Shift-click a second one to compare.'}
      </div>
    </div>
  );
}
