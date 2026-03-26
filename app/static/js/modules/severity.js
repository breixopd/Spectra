/**
 * Severity utilities — single source of truth for severity colors, backgrounds, and icons.
 * Replaces 5+ duplicate severity→color mappings across templates.
 */

const SEVERITY_MAP = {
    critical: { color: 'text-rose-400', bg: 'bg-rose-500/15', icon: '◆', label: 'Critical' },
    high:     { color: 'text-amber-400', bg: 'bg-amber-500/15', icon: '▲', label: 'High' },
    medium:   { color: 'text-yellow-400', bg: 'bg-yellow-500/15', icon: '●', label: 'Medium' },
    low:      { color: 'text-emerald-400', bg: 'bg-emerald-500/15', icon: '▼', label: 'Low' },
    info:     { color: 'text-blue-400', bg: 'bg-blue-500/15', icon: 'ℹ', label: 'Info' },
};

/**
 * Get Tailwind text color class for a severity level.
 * @param {string} severity
 * @returns {string}
 */
export function getSeverityColor(severity) {
    return SEVERITY_MAP[severity?.toLowerCase()]?.color || 'text-slate-400';
}

/**
 * Get Tailwind background class for a severity level.
 * @param {string} severity
 * @returns {string}
 */
export function getSeverityBg(severity) {
    return SEVERITY_MAP[severity?.toLowerCase()]?.bg || 'bg-slate-500/15';
}

/**
 * Get icon character for a severity level.
 * @param {string} severity
 * @returns {string}
 */
export function getSeverityIcon(severity) {
    return SEVERITY_MAP[severity?.toLowerCase()]?.icon || '○';
}

/**
 * Get display label for a severity level.
 * @param {string} severity
 * @returns {string}
 */
export function getSeverityLabel(severity) {
    return SEVERITY_MAP[severity?.toLowerCase()]?.label || severity || 'Unknown';
}

/**
 * Get all severity info for a level.
 * @param {string} severity
 * @returns {{ color: string, bg: string, icon: string, label: string }}
 */
export function getSeverityInfo(severity) {
    return SEVERITY_MAP[severity?.toLowerCase()] || SEVERITY_MAP.info;
}

// Expose globally for non-module contexts
window.getSeverityColor = getSeverityColor;
window.getSeverityBg = getSeverityBg;
