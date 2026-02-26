/**
 * comparison.js — Entry point for the comparison module.
 *
 * Imports all sub-modules, initializes state/DOM, and sets up
 * the application lifecycle. Each module is responsible for its
 * own initialization via initXxx() functions.
 *
 * Module structure (modules/):
 *   config.js      — constants, type labels, color palette
 *   state.js       — centralized shared state + DOM refs
 *   logger.js      — structured logging (?log=debug)
 *   utils.js       — pure utility functions
 *   layout.js      — scroll sync, divider resize
 *   badges.js      — badge injection, rebuild lifecycle
 *   pdf-sync.js    — PDF marker ↔ reference synchronization
 *   html-sync.js   — HTML element ↔ reference synchronization
 *   xml-sync.js    — S1000D panel 3-phase element matching
 *   pdf-overlay.js — PDF page overlay creation
 *   navigation.js  — annotation navigation, keyboard shortcuts
 *   mismatch.js    — mismatch detection, issue navigation, LCS
 *   verification.js— verify loop, XSD issues, panel refresh
 *   edit-mode.js   — context menu, CRUD, merge/split/delete/create
 */

import { initState } from './modules/state.js';
import { initLayout } from './modules/layout.js';
import { injectBadges, recalcMaxIdx, updatePosition, _rebuildHooks } from './modules/badges.js';
import { syncPdfMarkers } from './modules/pdf-sync.js';
import { syncHtmlElements } from './modules/html-sync.js';
import { initNavigation } from './modules/navigation.js';
import { initMismatch, detectMismatchFn } from './modules/mismatch.js';
import { initVerification } from './modules/verification.js';
import { initEditMode, autoLoadReference } from './modules/edit-mode.js';
import { createPdfOverlay } from './modules/pdf-overlay.js';
import { dom } from './modules/state.js';

// ── Expose functions needed by inline scripts and PDF rendering ──
window.createPdfOverlay = createPdfOverlay;
window.detectMismatch = function () { detectMismatchFn(); };

// ── Register sync hooks (badges.js calls these during rebuild) ──
_rebuildHooks.syncPdfMarkers = syncPdfMarkers;
_rebuildHooks.syncHtmlElements = syncHtmlElements;

// ── Initialize ──────────────────────────────────────────────────
// ES modules are deferred, so DOM is ready by the time this runs.
// But use DOMContentLoaded for safety with older browsers.
document.addEventListener('DOMContentLoaded', function () {
    initState();
    initLayout();

    // Initial annotation setup (inject badges into both panels)
    injectBadges(dom.docxPanel);
    injectBadges(dom.s1000dPanel);
    recalcMaxIdx();
    updatePosition();

    initNavigation();
    initMismatch();
    initVerification();
    initEditMode();

    // Auto-load reference if one already exists for this DMC
    autoLoadReference();
});
