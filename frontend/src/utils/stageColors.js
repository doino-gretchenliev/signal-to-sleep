/**
 * Canonical sleep-stage color palette.
 * Import from here instead of hard-coding hex values in each component.
 */

// Solid hex colors
export const STAGE_COLORS = {
  awake: '#f87171',
  light: '#2dd4bf',
  deep:  '#3b82f6',
  rem:   '#e879f9',
}

// Semi-transparent backgrounds (for chart band overlays)
export const STAGE_BG = {
  awake: 'rgba(248,113,113,0.15)',
  light: 'rgba(45,212,191,0.15)',
  deep:  'rgba(59,130,246,0.18)',
  rem:   'rgba(232,121,249,0.15)',
}

// Stage metadata used by bar / donut components
export const STAGES = [
  { key: 'awake', label: 'Awake', field: 'awake_min', color: STAGE_COLORS.awake },
  { key: 'light', label: 'Light', field: 'light_sleep_min', color: STAGE_COLORS.light },
  { key: 'deep',  label: 'Deep',  field: 'deep_sleep_min',  color: STAGE_COLORS.deep },
  { key: 'rem',   label: 'REM',   field: 'rem_sleep_min',   color: STAGE_COLORS.rem },
]

// D3-friendly arrays (matching domain order: deep, light, rem, awake)
export const STAGE_DOMAIN = ['deep', 'light', 'rem', 'awake']
export const STAGE_RANGE  = [STAGE_COLORS.deep, STAGE_COLORS.light, STAGE_COLORS.rem, STAGE_COLORS.awake]
