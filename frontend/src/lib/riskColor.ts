/**
 * The one green → red ramp. Every shaded map and panel reads off this list,
 * so the same colour means the same intensity wherever it appears.
 *
 * 0–2 green, 3–4 yellow-green, 5–6 amber, 7–8 orange, 9–10 red.
 * Values between the stops are interpolated in sRGB, which is the same
 * interpolation MapLibre applies to a linear color expression built from
 * these stops. Map fills and panels must both use this list.
 */
export const RISK_COLOR_STOPS: readonly (readonly [number, string])[] = [
  [0, '#1e9d55'],
  [2, '#3cba5a'],
  [3, '#8dce3a'],
  [4, '#c6d43a'],
  [5, '#e6b325'],
  [6, '#f0a020'],
  [7, '#f07818'],
  [8, '#e85d24'],
  [9, '#e23b32'],
  [10, '#c41919'],
];

function channel(hex: string, index: number): number {
  return Number.parseInt(hex.slice(1 + index * 2, 3 + index * 2), 16);
}

function mixHex(from: string, to: string, fraction: number): string {
  const mix = (start: number, end: number) => Math.round(start + (end - start) * fraction);
  const red = mix(channel(from, 0), channel(to, 0));
  const green = mix(channel(from, 1), channel(to, 1));
  const blue = mix(channel(from, 2), channel(to, 2));
  return `#${[red, green, blue].map((value) => value.toString(16).padStart(2, '0')).join('')}`;
}

function colorFromStops(stops: readonly (readonly [number, string])[], score: number): string {
  const first = stops[0];
  const last = stops[stops.length - 1];
  if (!first || !last || !Number.isFinite(score)) return first?.[1] ?? '#1e9d55';
  const value = Math.min(last[0], Math.max(first[0], score));
  if (value <= first[0]) return first[1];
  for (let index = 1; index < stops.length; index += 1) {
    const upper = stops[index];
    const lower = stops[index - 1];
    if (!upper || !lower) continue;
    if (value <= upper[0]) {
      const span = upper[0] - lower[0];
      return mixHex(lower[1], upper[1], span === 0 ? 0 : (value - lower[0]) / span);
    }
  }
  return last[1];
}

/** Colour for a 0–10 risk score. Out-of-range values are clamped. */
export function riskColor(score: number): string {
  return colorFromStops(RISK_COLOR_STOPS, score);
}

/**
 * MapLibre interpolate expression over `stops`.
 * `input` is a numeric expression already on the 0–10 scale.
 */
export function rampExpression(
  stops: readonly (readonly [number, string])[],
  input: unknown[],
): unknown[] {
  const expression: unknown[] = ['interpolate', ['linear'], input];
  for (const [stop, color] of stops) {
    expression.push(stop, color);
  }
  return expression;
}

/** Same stops as {@link riskColor}. */
export function riskFillExpression(input: unknown[]): unknown[] {
  return rampExpression(RISK_COLOR_STOPS, input);
}
