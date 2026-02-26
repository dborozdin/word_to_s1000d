/**
 * logger.js — Structured logging for the comparison module.
 *
 * Usage:
 *   import { log, logGroup, logGroupEnd } from './logger.js';
 *   log('pdf-sync', 'claimed marker', { page: 3, score: 0.95 });
 *   logGroup('edit', 'Create element');
 *   logGroupEnd('edit');
 *
 * Enable via URL: ?log=debug  (or localStorage.setItem('compLog', 'debug'))
 * Areas: pdf-sync, html-sync, xml-sync, edit, badges, verify, nav, overlay
 */

const LOG_LEVELS = { debug: 0, info: 1, warn: 2, error: 3, off: 4 };

let _level = LOG_LEVELS.warn; // default: only warnings and errors
let _enabledAreas = null;     // null = all areas, Set = only listed areas

// Initialize from URL params or localStorage
(function _initLogger() {
    var params = new URLSearchParams(window.location.search);
    var urlLevel = params.get('log');
    var stored = localStorage.getItem('compLog');
    var levelStr = urlLevel || stored || 'warn';

    if (LOG_LEVELS[levelStr] !== undefined) {
        _level = LOG_LEVELS[levelStr];
    }

    // Optional area filter: ?logArea=pdf-sync,edit
    var areaStr = params.get('logArea') || localStorage.getItem('compLogArea');
    if (areaStr) {
        _enabledAreas = new Set(areaStr.split(',').map(function(s) { return s.trim(); }));
    }

    if (_level <= LOG_LEVELS.info) {
        console.log('[comp] Logger initialized: level=' + levelStr +
            (_enabledAreas ? ', areas=' + Array.from(_enabledAreas).join(',') : ', areas=ALL'));
    }
})();

function _isEnabled(area, msgLevel) {
    if (msgLevel < _level) return false;
    if (_enabledAreas && !_enabledAreas.has(area)) return false;
    return true;
}

/** Log a debug message */
export function log(area, ...args) {
    if (!_isEnabled(area, LOG_LEVELS.debug)) return;
    console.log('[' + area + ']', ...args);
}

/** Log an info message */
export function logInfo(area, ...args) {
    if (!_isEnabled(area, LOG_LEVELS.info)) return;
    console.info('[' + area + ']', ...args);
}

/** Log a warning */
export function logWarn(area, ...args) {
    if (!_isEnabled(area, LOG_LEVELS.warn)) return;
    console.warn('[' + area + ']', ...args);
}

/** Log an error */
export function logError(area, ...args) {
    if (!_isEnabled(area, LOG_LEVELS.error)) return;
    console.error('[' + area + ']', ...args);
}

/** Start a collapsed console group */
export function logGroup(area, label) {
    if (!_isEnabled(area, LOG_LEVELS.debug)) return;
    console.groupCollapsed('[' + area + '] ' + label);
}

/** End a console group */
export function logGroupEnd(area) {
    if (!_isEnabled(area, LOG_LEVELS.debug)) return;
    console.groupEnd();
}

/** Time a block: returns a function to call when done */
export function logTime(area, label) {
    if (!_isEnabled(area, LOG_LEVELS.debug)) return function() {};
    var start = performance.now();
    return function() {
        var ms = (performance.now() - start).toFixed(1);
        console.log('[' + area + '] ' + label + ': ' + ms + 'ms');
    };
}
