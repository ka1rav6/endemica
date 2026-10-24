import { describe, expect, it } from 'vitest';
import { RISK_COLOR_STOPS, riskColor, riskFillExpression } from '@/lib/riskColor';

describe('riskColor', () => {
  it('matches the documented stops', () => {
    for (const [score, color] of RISK_COLOR_STOPS) {
      expect(riskColor(score)).toBe(color);
    }
  });

  it('clamps scores outside 0–10', () => {
    expect(riskColor(-4)).toBe(riskColor(0));
    expect(riskColor(12)).toBe(riskColor(10));
    expect(riskColor(Number.NaN)).toBe(riskColor(0));
  });

  it('interpolates between stops instead of snapping to five bands', () => {
    const between = riskColor(1);
    expect(between).not.toBe(riskColor(0));
    expect(between).not.toBe(riskColor(2));
    expect(riskColor(0)).not.toBe(riskColor(10));
  });

  it('builds a MapLibre expression from the same stops', () => {
    const expression = riskFillExpression(['get', 'score']);
    expect(expression.slice(0, 3)).toEqual(['interpolate', ['linear'], ['get', 'score']]);
    expect(expression).toContain(0);
    expect(expression).toContain('#1e9d55');
    expect(expression).toContain(10);
    expect(expression).toContain('#c41919');
  });
});
