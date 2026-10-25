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
import { selectAirports, type AirportCollection } from '@/lib/airports';
import { formatCount, formatPassengers } from '@/lib/format';
import { greatCircleLine, type Point } from '@/lib/geo';
import { landAnchor } from '@/lib/landmass';
import { RISK_COLOR_STOPS, riskColor, riskFillExpression } from '@/lib/riskColor';
import { MAX_DISEASE_LOAD, type MapSpreadEntry } from '@/lib/spread';
import { arcsToCollection, spreadArcs, type SpreadArc } from '@/lib/spreadFlow';
import type { Country, OriginContribution, Route } from '@/types/api';

const API_BOUNDARIES_URL = '/data/country_boundaries.geojson';
const BUNDLED_BOUNDARIES_URL = '/boundaries/countries.geojson';
const AIRPORTS_URL = '/data/airports.geojson';

// Below this the whole country is a few pixels wide, so its airports would all
// land on the same spot.
const AIRPORT_MIN_ZOOM = 2.6;
// How many airports fit depends on the zoom, so the dots are re-chosen as it
// changes. Rounding to half a level keeps that to a few recalculations per
// flight rather than one per frame.
const ZOOM_STEP = 2;
const HOME_VIEW = { center: [12, 22] as [number, number], zoom: 1.5 };

const C = {
  water: '#060910',
  graticule: '#15202c',
  land: '#1e2a36',
  landQuiet: '#263442',
  outline: '#2f3f4f',
  outlineHover: '#dbe6f0',
  selected: '#2ee6c0',
  arcObserved: '#2ee6c0',
  arcEstimated: '#58a6ff',
} as const;

interface Props {
  countries: Country[];
  selectedIso3: string | null;
  comparisonIso3: string | null;
  /** ``null`` clears the selection, which the ocean click does. */
  onSelect: (iso3: string | null, additive: boolean) => void;
  spread: MapSpreadEntry[];
  diseaseName: string | null;
  activeMode?: boolean;
  yearCeiling: number | null;
  origins: OriginContribution[];
  routes: Route[];
  showFlows: boolean;
  forecast?: { iso3: string; probability: number }[];
  /** Full outbreak span, so a year early in the timeline stays green. */
  spreadSpan?: { first: number; last: number } | null;
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
        disease: contribution?.disease_name ?? null,
        // A corridor that no reporting country feeds is drawn thin and faint:
        // it is travel volume only, not a route anything is arriving on.
        carries: contribution ? 1 : 0,
        width: contribution ? 1.4 + share * 4.2 : 0.9,
      },
      geometry: {
        type: 'LineString',
        coordinates: greatCircleLine({ lat: oLat, lon: oLon }, { lat: dLat, lon: dLon }),
      },
    });
  }
  return { type: 'FeatureCollection', features };
}

function pointFor(country: Country | undefined, centre: Point | null): FeatureCollection<GeoPoint> {
  if (!country || !centre) return { type: 'FeatureCollection', features: [] };
  return {
    type: 'FeatureCollection',
    features: [
      {
        type: 'Feature',
        properties: { iso3: country.iso3 },
        geometry: { type: 'Point', coordinates: [centre.lon, centre.lat] },
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

let airportRequest: Promise<AirportCollection> | null = null;

/** Fetched once per session, then shared: the file is the same for every country. */
function loadAirports(): Promise<AirportCollection> {
  airportRequest ??= fetch(AIRPORTS_URL).then(async (response) => {
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return (await response.json()) as AirportCollection;
  });
  return airportRequest;
}

/**
 * Where to draw a country on the map: a point on its own main landmass, not
 * the stored centroid, which averages in distant territory and can land in
 * the sea. See `landAnchor`.
 */
function anchorFor(
  boundaries: BoundaryCollection | null,
  country: Country | undefined,
): Point | null {
  if (!country || country.centroid_lat === null || country.centroid_lon === null) return null;
  const fallback: Point = { lat: country.centroid_lat, lon: country.centroid_lon };
  const feature = boundaries?.features.find(
    (candidate) => candidate.properties['iso3'] === country.iso3,
  );
  return feature ? landAnchor(feature.geometry, fallback) : fallback;
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
  );
  const disease = properties['disease'];
  root.append(
    node(
      'div',
      typeof disease === 'string' && disease
        ? `carries ${disease} risk`
        : 'travel volume only — no reported outbreak at this origin',
      {
        color: Number(properties['carries']) === 1 ? '#2ee6c0' : '#74889e',
        fontSize: '10.5px',
        marginTop: '2px',
      },
    ),
    node(`div`, `source: ${String(properties['source'])}`, {
      color: '#4f6377',
      fontSize: '10px',
    }),
  );
  return root;
}

// Selection is deliberately absent from this list. Clicking a country must not
// repaint it: what it is shaded for — when it reported, how much it is carrying,
// how likely it is to be reached — does not change because someone looked at it.
// The outline and the pin are what mark the selection.
const fillColour = [
  'case',
  ['boolean', ['feature-state', 'affected'], false],
  riskFillExpression(['*', ['coalesce', ['feature-state', 'order'], 0], 10]),
  ['boolean', ['feature-state', 'forecast'], false],
  riskFillExpression(['*', ['coalesce', ['feature-state', 'probability'], 0], 10]),
  ['boolean', ['feature-state', 'hasAnyReport'], false],
  C.landQuiet,
  C.land,
] as unknown as ExpressionSpecification;

const EMPTY_FLOWS: FeatureCollection<LineString> = { type: 'FeatureCollection', features: [] };

interface FlowAnim {
  start: number;
  duration: number;
}

export function WorldMap({
  countries,
  selectedIso3,
  comparisonIso3,
  onSelect,
  spread,
  diseaseName,
  activeMode = false,
  yearCeiling,
  origins,
  routes,
  showFlows,
  forecast = [],
  spreadSpan = null,
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const flewTo = useRef<string | null>(null);
  const [ready, setReady] = useState(false);
  const [boundaryError, setBoundaryError] = useState<string | null>(null);
  const [boundaries, setBoundaries] = useState<BoundaryCollection | null>(null);
  const [zoom, setZoom] = useState(HOME_VIEW.zoom);
  const [airports, setAirports] = useState<AirportCollection | null>(null);
  const selectRef = useRef(onSelect);
  selectRef.current = onSelect;
  const flowLinesRef = useRef<SpreadArc[]>([]);
  const flowAnimRef = useRef<FlowAnim | null>(null);

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
      center: HOME_VIEW.center,
      zoom: HOME_VIEW.zoom,
      minZoom: 0.9,
      maxZoom: 7,
      attributionControl: false,
      // MapLibre's box zoom owns shift-drag, and it swallows the click that
      // ends it. Comparing two countries with shift-click matters more here
      // than a rubber-band zoom the scroll wheel already does.
      boxZoom: false,
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
      const flow = flowAnimRef.current;
      if (flow && map.getLayer('spread-flow')) {
        const raw = Math.min(1, (now - flow.start) / flow.duration);
        const eased = 1 - (1 - raw) ** 3;
        const source = map.getSource('spread-flow');
        // MapLibre 6 has no line-trim-offset, so the arc is drawn on by
        // revealing the great-circle vertices. Same idea as stroke-dashoffset.
        if (source instanceof GeoJSONSource) {
          void source.setData(arcsToCollection(flowLinesRef.current, eased));
        }
        if (raw >= 1) flowAnimRef.current = null;
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
          setBoundaries(data);

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
              'fill-color-transition': { duration: reducedMotion ? 0 : 320, delay: 0 },
              'fill-opacity': [
                'case',
                ['boolean', ['feature-state', 'hover'], false],
                1,
                ['boolean', ['feature-state', 'affected'], false],
                0.92,
                0.78,
              ] as ExpressionSpecification,
              'fill-opacity-transition': { duration: reducedMotion ? 0 : 280, delay: 0 },
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
              'line-color-transition': { duration: reducedMotion ? 0 : 320, delay: 0 },
              'line-width-transition': { duration: reducedMotion ? 0 : 320, delay: 0 },
            },
          });

          map.addSource('spread-flow', {
            type: 'geojson',
            lineMetrics: true,
            data: EMPTY_FLOWS,
          });
          map.addLayer({
            id: 'spread-flow',
            type: 'line',
            source: 'spread-flow',
            layout: { 'line-cap': 'round', 'line-join': 'round' },
            paint: {
              'line-color': ['get', 'color'] as ExpressionSpecification,
              'line-width': 2.4,
              'line-opacity': 0.92,
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
              'line-opacity': [
                'case',
                ['==', ['get', 'carries'], 1],
                0.24,
                0,
              ] as ExpressionSpecification,
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
              'line-opacity': [
                'case',
                ['==', ['get', 'carries'], 1],
                0.92,
                0.32,
              ] as ExpressionSpecification,
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
              'line-opacity': [
                'case',
                ['==', ['get', 'carries'], 1],
                0.85,
                0.3,
              ] as ExpressionSpecification,
              'line-dasharray': [0.6, 1.2],
            },
          });

          map.addSource('airports', {
            type: 'geojson',
            data: { type: 'FeatureCollection', features: [] },
          });
          map.addLayer({
            id: 'airport-dot',
            type: 'circle',
            source: 'airports',
            minzoom: AIRPORT_MIN_ZOOM,
            paint: {
              // `weight` is already the square root of the airport's share of
              // the country's routes, so a linear ramp here makes the dot's
              // area, not its radius, stand for the traffic.
              'circle-radius': [
                'interpolate',
                ['linear'],
                ['get', 'weight'],
                0,
                2.6,
                1,
                8,
              ] as ExpressionSpecification,
              'circle-color': riskFillExpression([
                'coalesce',
                ['get', 'distance'],
                0,
              ]) as unknown as ExpressionSpecification,
              'circle-opacity': 0.95,
              'circle-stroke-width': 1.6,
              'circle-stroke-color': '#06101a',
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
                  entry.diseaseNames
                    ? entry.diseaseNames.join(', ')
                    : `${diseaseRef.current ?? 'Reported'} · arrived ${entry.firstYear ?? 'unknown'} (#${entry.arrivalOrder})`,
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

          // One handler for the whole canvas rather than a layer-scoped one, so
          // a click on open water is a real event: it clears the selection and
          // returns the map to the overview.
          map.on('click', (event: MapLayerMouseEvent) => {
            const hit = map.queryRenderedFeatures(event.point, { layers: ['country-fill'] });
            const additive = event.originalEvent.shiftKey || event.originalEvent.metaKey;
            const properties: unknown = hit[0]?.properties;
            const iso3 =
              typeof properties === 'object' && properties !== null
                ? (properties as Record<string, unknown>)['iso3']
                : null;
            if (typeof iso3 === 'string' && iso3) {
              selectRef.current(iso3, additive);
              return;
            }
            if (additive) return;
            popup.remove();
            selectRef.current(null, false);
          });

          const showArc = (event: MapLayerMouseEvent) => {
            const properties = event.features?.[0]?.properties;
            if (!properties) return;
            map.getCanvas().style.cursor = 'pointer';
            popup.setLngLat(event.lngLat).setDOMContent(routePopup(properties)).addTo(map);
          };
          map.on('mousemove', 'airport-dot', (event: MapLayerMouseEvent) => {
            const properties = event.features?.[0]?.properties;
            if (!properties) return;
            map.getCanvas().style.cursor = 'pointer';
            const root = document.createElement('div');
            root.append(
              node('strong', `${String(properties['name'])} (${String(properties['iata'])})`),
              node('div', `${formatCount(Number(properties['routes']))} scheduled routes`, {
                color: '#a8bacd',
                fontSize: '10.5px',
                marginTop: '2px',
              }),
              node('div', `${formatCount(Number(properties['km']))} km from the reported centre`, {
                color: riskColor(Number(properties['distance'])),
                fontSize: '11px',
              }),
            );
            popup.setLngLat(event.lngLat).setDOMContent(root).addTo(map);
          });
          map.on('mouseleave', 'airport-dot', () => {
            popup.remove();
            map.getCanvas().style.cursor = '';
          });

          map.on('mousemove', 'arc-observed', showArc);
          map.on('mousemove', 'arc-modelled', showArc);
          map.on('mousemove', 'spread-flow', (event: MapLayerMouseEvent) => {
            const properties = event.features?.[0]?.properties;
            if (!properties) return;
            map.getCanvas().style.cursor = 'pointer';
            const root = document.createElement('div');
            root.append(
              node('strong', `${String(properties['fromName'])} → ${String(properties['toName'])}`),
              node('div', `Newly reached in ${String(properties['year'])}`, {
                color: String(properties['color'] ?? '#e6b325'),
                fontSize: '11px',
                marginTop: '2px',
              }),
            );
            popup.setLngLat(event.lngLat).setDOMContent(root).addTo(map);
          });
          map.on('mouseleave', 'spread-flow', () => {
            popup.remove();
            map.getCanvas().style.cursor = '';
          });

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

    // Half-level steps, so the airport dots are re-chosen a handful of times
    // during a flight instead of on every frame. React drops the repeats.
    map.on('zoom', () => {
      setZoom(Math.round(map.getZoom() * ZOOM_STEP) / ZOOM_STEP);
    });

    // Whichever arrives first wins; `start` is guarded against running twice.
    // `isStyleLoaded` alone is not enough, because that flag only flips during
    // a draw and a hidden page draws nothing.
    if (map.isStyleLoaded()) start();
    else {
      map.once('style.load', start);
      map.once('load', start);
      map.on('styledata', start);
    }

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
      // Green is the low end of the one ramp either way: early arrival when a
      // single disease is shown, fewest diseases in the combined view. The
      // combined view's scale is fixed (see MAX_DISEASE_LOAD), so a country's
      // shade does not move when some other country's disease count does.
      map.setFeatureState(
        { source: 'countries', id: entry.iso3 },
        { affected: true, order: entry.arrivalShare },
      );
    }
    for (const entry of forecast) {
      map.setFeatureState(
        { source: 'countries', id: entry.iso3 },
        { forecast: true, probability: entry.probability },
      );
    }
    if (comparisonIso3) {
      map.setFeatureState({ source: 'countries', id: comparisonIso3 }, { compared: true });
    }
    if (selectedIso3) {
      map.setFeatureState({ source: 'countries', id: selectedIso3 }, { selected: true });
    }
  }, [ready, countries, spread, forecast, selectedIso3, comparisonIso3, activeMode]);

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
    const source = map.getSource('spread-flow');
    if (!(source instanceof GeoJSONSource)) return;

    const clear = () => {
      flowLinesRef.current = [];
      flowAnimRef.current = null;
      void source.setData(EMPTY_FLOWS);
    };
    if (activeMode || yearCeiling === null) {
      clear();
      return;
    }

    const arcs = spreadArcs(countries, spread, yearCeiling, spreadSpan);
    flowLinesRef.current = arcs;
    if (arcs.length === 0) {
      clear();
      return;
    }

    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    void source.setData(arcsToCollection(arcs, reduced ? 1 : 0));
    flowAnimRef.current = reduced ? null : { start: performance.now(), duration: 680 };
  }, [ready, countries, spread, yearCeiling, spreadSpan, activeMode]);

  // The point this country is drawn at: its own main landmass, not the stored
  // centroid, which for a country with distant territory can sit in the sea.
  const anchor = useMemo(() => anchorFor(boundaries, selected), [boundaries, selected]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const pin = map.getSource('pin');
    if (pin instanceof GeoJSONSource) void pin.setData(pointFor(selected, anchor));
  }, [ready, selected, anchor]);

  // Fetched the first time a country is opened, not on load: nothing is drawn
  // from it until then, and the file is the largest the map pulls.
  useEffect(() => {
    if (!selected || airports) return;
    let cancelled = false;
    loadAirports()
      .then((data) => {
        if (!cancelled) setAirports(data);
      })
      .catch(() => {
        // Built by `just data-build`. Without it the map simply draws no
        // airports, which is better than an error over a working map.
      });
    return () => {
      cancelled = true;
    };
  }, [selected, airports]);

  const countryAirports = useMemo(
    () => selectAirports(airports, selected?.iso3, anchor, zoom),
    [airports, selected, anchor, zoom],
  );

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const source = map.getSource('airports');
    if (source instanceof GeoJSONSource) void source.setData(countryAirports);
  }, [ready, countryAirports]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !selected || !anchor || flewTo.current === selected.iso3) return;
    flewTo.current = selected.iso3;
    // Close enough that the country's airports come in, which is the point of
    // opening one: the dots and the pin together show where its traffic sits
    // relative to where the outbreak is reported.
    const camera = {
      center: [anchor.lon, anchor.lat] as [number, number],
      zoom: Math.max(map.getZoom(), 3.1),
      essential: true,
    };
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) map.jumpTo(camera);
    else map.easeTo({ ...camera, duration: 950 });
  }, [ready, selected, anchor]);

  const resetView = () => {
    const map = mapRef.current;
    if (!map) return;
    // Clearing this lets the same country fly in again when it is next picked.
    flewTo.current = null;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) map.jumpTo(HOME_VIEW);
    else map.easeTo({ ...HOME_VIEW, duration: 700, essential: true });
  };

  const firstYear = spread.reduce<number | null>(
    (min, entry) =>
      entry.firstYear !== null && (min === null || entry.firstYear < min) ? entry.firstYear : min,
    null,
  );

  return (
    <div className="map">
      <div className="map__canvas" ref={containerRef} data-testid="map-canvas" />

      <button type="button" className="map__reset" onClick={resetView} title="Reset the view">
        Reset view
      </button>

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
                <span
                  className={activeMode ? 'dot dot--pulse' : 'dot'}
                  style={{ color: activeMode ? 'var(--hot)' : 'var(--accent)' }}
                  aria-hidden="true"
                />
                {activeMode ? 'Currently reported' : 'Spread of'}
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
                <dt>{activeMode ? 'Reports' : 'First seen'}</dt>
                <dd className="num">
                  {activeMode
                    ? spread.reduce((total, entry) => total + entry.reportCount, 0)
                    : (firstYear ?? '—')}
                </dd>
              </div>
              {!activeMode && (
                <div className="hud__stat">
                  <dt>Showing</dt>
                  <dd className="num">
                    {yearCeiling === null ? 'all years' : <>up to {yearCeiling}</>}
                  </dd>
                </div>
              )}
            </dl>
          )}
        </div>

        {spread.length > 0 && (
          <div className="hud legend">
            <span className="legend__title">
              {activeMode ? 'Diseases reported' : 'When it arrived'}
            </span>
            <span className="legend__ramp" aria-hidden="true">
              {RISK_COLOR_STOPS.map(([stop, colour]) => (
                <i key={stop} style={{ background: colour }} />
              ))}
            </span>
            <span className="legend__scale">
              <span>{activeMode ? '1 disease' : 'earlier'}</span>
              <span>{activeMode ? `${MAX_DISEASE_LOAD}+` : 'later'}</span>
            </span>
            {!activeMode && yearCeiling !== null && (
              <span className="legend__row">
                <span className="swatch swatch--line" style={{ background: riskColor(7) }} />
                Growth into {yearCeiling}
              </span>
            )}
            {countryAirports.features.length > 0 && (
              <>
                <span className="legend__row">
                  <span className="swatch" style={{ background: riskColor(0) }} />
                  Airport nearest the reported centre
                </span>
                <span className="legend__row">
                  <span className="swatch" style={{ background: riskColor(10) }} />
                  Farthest · dot size is scheduled routes
                </span>
              </>
            )}
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
                <span className="legend__row">
                  <span
                    className="swatch swatch--line"
                    style={{ background: C.arcEstimated, opacity: 0.3 }}
                  />
                  Travel only, no outbreak
                </span>
              </>
            )}
          </div>
        )}
      </div>

      <div className="hud map__hint">
        {activeMode
          ? 'Every country with a report in the last 90 days, shaded by how many diseases — not by the travel-risk index. Click one for its record, shift-click a second to compare, click the sea to clear.'
          : spread.length > 0
            ? 'Shaded by when each country first reported this disease — not by the travel-risk index. Click one for its record, shift-click a second to compare, click the sea to clear.'
            : 'Pick a disease on the left to shade the map. Click any country for its record, shift-click a second one to compare.'}
      </div>
    </div>
  );
}
