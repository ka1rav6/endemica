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
import { greatCircleLine } from '@/lib/geo';
import { formatPassengers } from '@/lib/format';

const API_BOUNDARIES_URL = '/data/country_boundaries.geojson';
const BUNDLED_BOUNDARIES_URL = '/boundaries/countries.geojson';

const COLOURS = {
  land: '#8ea4b8',
  landOrigin: '#38bdf8',
  landOutbreak: '#fb7185',
  landSelected: '#14b8a6',
  outline: '#4d6478',
  outlineHover: '#f8fafc',
  outlineSelected: '#ccfbf1',
  arcObserved: '#2dd4bf',
  arcEstimated: '#7dd3fc',
  water: '#07131c',
  graticule: '#1a3d56',
} as const;

interface Props {
  countries: Country[];
  selectedIso3: string | null;
  onSelect: (iso3: string) => void;
  origins: OriginContribution[];
  routes: Route[];
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

interface HoveredCountry {
  iso3: string;
  name: string;
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
        origin: route.origin_iso3,
        originName: route.origin_name,
        dest: route.dest_iso3,
        destName: route.dest_name,
        passengers: route.passengers_per_day,
        valueType: route.value_type,
        source: route.source,
        width: 1.2 + share * 4.5,
      },
      geometry: {
        type: 'LineString',
        coordinates: greatCircleLine({ lat: oLat, lon: oLon }, { lat: dLat, lon: dLon }),
      },
    });
  }

  return { type: 'FeatureCollection', features };
}

function pointFeatures(
  countries: Country[],
  include: (country: Country) => boolean,
): FeatureCollection<GeoPoint> {
  const features: Feature<GeoPoint>[] = [];
  for (const country of countries) {
    const { centroid_lat: lat, centroid_lon: lon } = country;
    if (!include(country) || lat === null || lon === null) continue;
    features.push({
      type: 'Feature',
      properties: { iso3: country.iso3, name: country.name },
      geometry: { type: 'Point', coordinates: [lon, lat] },
    });
  }
  return { type: 'FeatureCollection', features };
}

function graticule(): FeatureCollection<LineString> {
  const features: Feature<LineString>[] = [];
  for (let lon = -180; lon <= 180; lon += 30) {
    const coordinates: [number, number][] = [];
    for (let lat = -80; lat <= 80; lat += 8) coordinates.push([lon, lat]);
    features.push({
      type: 'Feature',
      properties: {},
      geometry: { type: 'LineString', coordinates },
    });
  }
  for (let lat = -60; lat <= 60; lat += 30) {
    features.push({
      type: 'Feature',
      properties: {},
      geometry: {
        type: 'LineString',
        coordinates: [
          [-180, lat],
          [180, lat],
        ],
      },
    });
  }
  return { type: 'FeatureCollection', features };
}

async function loadBoundaries(): Promise<BoundaryCollection> {
  try {
    const response = await fetch(API_BOUNDARIES_URL, { signal: AbortSignal.timeout(4000) });
    if (response.ok) {
      const data = (await response.json()) as BoundaryCollection;
      if (Array.isArray(data.features) && data.features.length > 0) return data;
    }
  } catch {
    // Processed boundaries are optional. The bundled Natural Earth layer still draws.
  }
  const response = await fetch(BUNDLED_BOUNDARIES_URL);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const data = (await response.json()) as BoundaryCollection;
  if (!Array.isArray(data.features) || data.features.length === 0) {
    throw new Error('boundary file was empty');
  }
  return data;
}

function routePopup(properties: Record<string, unknown>): HTMLElement {
  const root = document.createElement('div');
  const title = document.createElement('strong');
  title.textContent = `${String(properties['originName'])} → ${String(properties['destName'])}`;
  const volume = document.createElement('div');
  volume.textContent = `${formatPassengers(Number(properties['passengers']))} · ${String(properties['valueType'])}`;
  const source = document.createElement('div');
  source.style.color = '#8aa0b5';
  source.textContent = `source: ${String(properties['source'])}`;
  root.append(title, volume, source);
  return root;
}

const arcColour: ExpressionSpecification = [
  'match',
  ['get', 'valueType'],
  'observed',
  COLOURS.arcObserved,
  COLOURS.arcEstimated,
];

export function WorldMap({ countries, selectedIso3, onSelect, origins, routes }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const flewTo = useRef<string | null>(null);
  const [ready, setReady] = useState(false);
  const [boundaryError, setBoundaryError] = useState<string | null>(null);
  const [hover, setHover] = useState<HoveredCountry | null>(null);
  const selectRef = useRef(onSelect);
  selectRef.current = onSelect;

  const selected = useMemo(
    () => countries.find((country) => country.iso3 === selectedIso3) ?? null,
    [countries, selectedIso3],
  );

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const container = containerRef.current;
    let cancelled = false;

    const map = new MapLibreMap({
      container,
      style: {
        version: 8,
        sources: {},
        layers: [
          { id: 'background', type: 'background', paint: { 'background-color': COLOURS.water } },
        ],
      },
      center: [18, 16],
      zoom: 1.35,
      minZoom: 0.8,
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
        customAttribution: 'Boundaries © Natural Earth. Arcs are great circles between centroids.',
      }),
      'bottom-right',
    );

    const popup = new Popup({
      closeButton: false,
      closeOnClick: false,
      offset: 12,
      maxWidth: '240px',
    });
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    let raf = 0;

    const resize = () => {
      map.resize();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(container);

    const animate = (now: number) => {
      if (cancelled) return;
      if (map.getLayer('arc-modelled')) {
        const phase = (now / 900) % 1;
        map.setPaintProperty('arc-modelled', 'line-dasharray', [
          0.25 + phase,
          1.15,
          1.35 - phase,
          1.15,
        ]);
      }
      if (map.getLayer('outbreak-halo')) {
        const wave = (Math.sin(now / 680) + 1) / 2;
        map.setPaintProperty('outbreak-halo', 'circle-radius', 9 + wave * 18);
        map.setPaintProperty('outbreak-halo', 'circle-opacity', 0.34 * (1 - wave * 0.72));
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
            paint: { 'line-color': COLOURS.graticule, 'line-width': 0.7, 'line-opacity': 0.85 },
          });

          map.addSource('countries', { type: 'geojson', data: data as never, promoteId: 'iso3' });
          map.addLayer({
            id: 'country-fill',
            type: 'fill',
            source: 'countries',
            paint: {
              'fill-color': [
                'case',
                ['boolean', ['feature-state', 'selected'], false],
                COLOURS.landSelected,
                ['boolean', ['feature-state', 'outbreak'], false],
                COLOURS.landOutbreak,
                ['>', ['coalesce', ['feature-state', 'share'], 0], 0],
                [
                  'interpolate',
                  ['linear'],
                  ['coalesce', ['feature-state', 'share'], 0],
                  0,
                  '#6f8ea8',
                  0.2,
                  '#3b82c4',
                  1,
                  COLOURS.landOrigin,
                ],
                COLOURS.land,
              ] as ExpressionSpecification,
              'fill-opacity': [
                'case',
                ['boolean', ['feature-state', 'hover'], false],
                1,
                ['boolean', ['feature-state', 'selected'], false],
                0.96,
                0.9,
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
                COLOURS.outlineSelected,
                ['boolean', ['feature-state', 'hover'], false],
                COLOURS.outlineHover,
                COLOURS.outline,
              ] as ExpressionSpecification,
              'line-width': [
                'case',
                ['boolean', ['feature-state', 'selected'], false],
                2.2,
                ['boolean', ['feature-state', 'hover'], false],
                1.25,
                0.55,
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
              'line-color': arcColour,
              'line-width': ['*', ['get', 'width'], 3.4] as ExpressionSpecification,
              'line-opacity': 0.28,
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
              'line-color': COLOURS.arcObserved,
              'line-width': ['get', 'width'] as ExpressionSpecification,
              'line-opacity': 0.95,
            },
          });
          map.addLayer({
            id: 'arc-modelled',
            type: 'line',
            source: 'arcs',
            filter: ['!=', ['get', 'valueType'], 'observed'],
            layout: { 'line-cap': 'round', 'line-join': 'round' },
            paint: {
              'line-color': COLOURS.arcEstimated,
              'line-width': ['get', 'width'] as ExpressionSpecification,
              'line-opacity': 0.9,
              'line-dasharray': [0.6, 1.2],
            },
          });

          map.addSource('outbreaks', {
            type: 'geojson',
            data: { type: 'FeatureCollection', features: [] },
          });
          map.addLayer({
            id: 'outbreak-halo',
            type: 'circle',
            source: 'outbreaks',
            paint: {
              'circle-radius': 12,
              'circle-color': COLOURS.landOutbreak,
              'circle-opacity': 0.28,
              'circle-blur': 0.45,
            },
          });
          map.addLayer({
            id: 'outbreak-points',
            type: 'circle',
            source: 'outbreaks',
            paint: {
              'circle-radius': 4.5,
              'circle-color': '#fecdd3',
              'circle-stroke-width': 2,
              'circle-stroke-color': COLOURS.landOutbreak,
            },
          });

          map.addSource('destination', {
            type: 'geojson',
            data: { type: 'FeatureCollection', features: [] },
          });
          map.addLayer({
            id: 'destination-point',
            type: 'circle',
            source: 'destination',
            paint: {
              'circle-radius': 6,
              'circle-color': '#f4fffb',
              'circle-stroke-width': 3,
              'circle-stroke-color': COLOURS.outlineSelected,
            },
          });

          const readCountry = (event: MapLayerMouseEvent): HoveredCountry | null => {
            const properties: unknown = event.features?.[0]?.properties;
            if (typeof properties !== 'object' || properties === null) return null;
            const record = properties as Record<string, unknown>;
            const iso3 = record['iso3'];
            const name = record['name'];
            if (typeof iso3 !== 'string' || !iso3) return null;
            return { iso3, name: typeof name === 'string' && name ? name : iso3 };
          };

          let hoveredId: string | null = null;
          const clearHover = () => {
            if (hoveredId) {
              map.setFeatureState({ source: 'countries', id: hoveredId }, { hover: false });
              hoveredId = null;
            }
            setHover(null);
            map.getCanvas().style.cursor = '';
          };

          map.on('mousemove', 'country-fill', (event: MapLayerMouseEvent) => {
            const country = readCountry(event);
            if (!country) return;
            if (hoveredId && hoveredId !== country.iso3) {
              map.setFeatureState({ source: 'countries', id: hoveredId }, { hover: false });
            }
            hoveredId = country.iso3;
            map.setFeatureState({ source: 'countries', id: country.iso3 }, { hover: true });
            map.getCanvas().style.cursor = 'pointer';
            setHover(country);
          });
          map.on('mouseleave', 'country-fill', clearHover);
          map.on('click', 'country-fill', (event: MapLayerMouseEvent) => {
            const country = readCountry(event);
            if (country) selectRef.current(country.iso3);
          });

          const showArc = (event: MapLayerMouseEvent) => {
            const properties = event.features?.[0]?.properties;
            if (!properties) return;
            map.getCanvas().style.cursor = 'pointer';
            popup.setLngLat(event.lngLat).setDOMContent(routePopup(properties)).addTo(map);
          };
          map.on('mousemove', 'arc-observed', showArc);
          map.on('mousemove', 'arc-modelled', showArc);
          map.on('mouseleave', 'arc-observed', () => {
            popup.remove();
          });
          map.on('mouseleave', 'arc-modelled', () => {
            popup.remove();
          });

          if (!reducedMotion) raf = requestAnimationFrame(animate);
          resize();
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
      if (!country.has_reported_outbreak) continue;
      map.setFeatureState({ source: 'countries', id: country.iso3 }, { outbreak: true });
    }
    for (const origin of origins) {
      map.setFeatureState(
        { source: 'countries', id: origin.origin_iso3 },
        { share: origin.share_of_total },
      );
    }
    if (selectedIso3) {
      map.setFeatureState({ source: 'countries', id: selectedIso3 }, { selected: true });
    }
  }, [ready, countries, origins, selectedIso3]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const source = map.getSource('arcs');
    if (source instanceof GeoJSONSource) void source.setData(arcFeatures(routes, origins));
  }, [ready, routes, origins]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const outbreaks = map.getSource('outbreaks');
    if (outbreaks instanceof GeoJSONSource) {
      void outbreaks.setData(pointFeatures(countries, (country) => country.has_reported_outbreak));
    }
    const destination = map.getSource('destination');
    if (destination instanceof GeoJSONSource) {
      void destination.setData(
        pointFeatures(
          countries,
          (country) => country.iso3 === selectedIso3 && !country.has_reported_outbreak,
        ),
      );
    }
  }, [ready, countries, selectedIso3]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !selectedIso3 || !selected) return;
    const { centroid_lat: lat, centroid_lon: lon } = selected;
    if (lat === null || lon === null || flewTo.current === selectedIso3) return;
    flewTo.current = selectedIso3;
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const camera = {
      center: [lon, lat] as [number, number],
      zoom: Math.max(map.getZoom(), 2.4),
      essential: true,
    };
    if (reducedMotion) map.jumpTo(camera);
    else map.easeTo({ ...camera, duration: 1100 });
  }, [ready, selected, selectedIso3]);

  return (
    <div className="map">
      <div className="map__canvas" ref={containerRef} data-testid="map-canvas" />
      <div className="map__vignette" />
      {boundaryError && (
        <div className="map__status">
          <div>
            <p style={{ maxWidth: 420 }}>{boundaryError}</p>
            <p style={{ color: 'var(--text-faint)', fontSize: 12 }}>
              The country list and all risk estimates still work without the map.
            </p>
          </div>
        </div>
      )}
      <div className="map__overlay">
        <div className="map__hud-title">
          <span className="map__kicker">Destination</span>
          <strong>{selected?.name ?? 'Select a country'}</strong>
          {hover && hover.iso3 !== selectedIso3 && <span className="map__hover">{hover.name}</span>}
        </div>
        <div className="legend">
          <span className="legend__item">
            <span className="swatch swatch--outbreak" />
            Reported outbreak
          </span>
          <span className="legend__item">
            <span className="swatch swatch--origin" />
            Arrival share
          </span>
          <span className="legend__item">
            <span className="swatch swatch--observed" />
            Observed flow
          </span>
          <span className="legend__item">
            <span className="swatch swatch--estimated" />
            Modelled flow
          </span>
        </div>
        <p className="map__note">
          {routes.length > 0
            ? `${routes.length} corridor${routes.length === 1 ? '' : 's'} into this destination. `
            : ''}
          Arc thickness follows each origin&apos;s share of the modelled arrival rate. Paths run
          between country centroids, not along flight tracks.
        </p>
      </div>
    </div>
  );
}
