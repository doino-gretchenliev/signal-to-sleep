/**
 * Format duration in minutes to human-readable string
 * @param minutes Duration in minutes
 * @returns Formatted string like "7h 30m" or "45m"
 */
export function fmtDuration(minutes) {
  if (!Number.isFinite(minutes)) return '0m';

  const hours = Math.floor(minutes / 60);
  const mins = Math.round(minutes % 60);

  if (hours === 0) return `${mins}m`;
  if (mins === 0) return `${hours}h`;
  return `${hours}h ${mins}m`;
}

/**
 * Get CSS color variable based on score
 * @param score Percentage score (0-100)
 * @returns CSS variable string
 */
export function scoreColor(score) {
  if (score >= 80) return 'var(--color-success)';
  if (score >= 50) return 'var(--color-warning)';
  return 'var(--color-danger)';
}

/**
 * Calculate average of array of numbers
 * @param arr Array of numbers
 * @returns Mean value, or 0 if array is empty
 */
export function avg(arr) {
  if (!arr || arr.length === 0) return 0;
  return arr.reduce((sum, val) => sum + val, 0) / arr.length;
}

/**
 * Format date to "MMM D" format
 * @param date Date object or timestamp
 * @returns Formatted date string
 */
export function fmtDate(date) {
  const d = date instanceof Date ? date : new Date(date);
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  return `${months[d.getMonth()]} ${d.getDate()}`;
}

/**
 * Format time to "HH:mm" format
 * @param date Date object or timestamp
 * @returns Formatted time string
 */
export function fmtTime(date) {
  const d = date instanceof Date ? date : new Date(date);
  const hours = String(d.getHours()).padStart(2, '0');
  const mins = String(d.getMinutes()).padStart(2, '0');
  return `${hours}:${mins}`;
}
