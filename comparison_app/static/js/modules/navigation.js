/**
 * navigation.js — Annotation navigation and keyboard controls.
 *
 * Handles navigating between annotation indices, scrolling to annotations,
 * highlighting, and keyboard shortcuts.
 */

import { dom } from './state.js';
import * as state from './state.js';
import { updatePosition, _rebuildHooks } from './badges.js';

/** Hook registry for issue navigation (set by mismatch module) */
export const _navHooks = {
    navigateToNextIssue: null,
    navigateToPrevIssue: null
};

/** Create a click handler that navigates to the given annotation index */
export function makeNavHandler(idx) {
    return function (e) {
        e.stopPropagation();
        navigateTo(idx);
    };
}

/** Toggle annotations visibility */
export function toggleAnnotations() {
    state.setAnnotationsVisible(!state.isAnnotationsVisible());
    document.body.classList.toggle('show-annotations', state.isAnnotationsVisible());
    if (dom.toggleBtn) {
        // Support both button (.active class) and checkbox (.checked)
        if (dom.toggleBtn.type === 'checkbox') {
            dom.toggleBtn.checked = state.isAnnotationsVisible();
        } else {
            dom.toggleBtn.classList.toggle('active', state.isAnnotationsVisible());
        }
    }
}

/** Navigate to a specific annotation index */
export function navigateTo(idx) {
    if (idx < 1) idx = 1;
    if (idx > state.getMaxIdx()) idx = state.getMaxIdx();
    state.setCurrentIdx(idx);

    state.setManualNavActive(true);

    scrollToAnno(dom.docxPanel, idx);
    scrollToAnno(dom.s1000dPanel, idx);
    highlightAnno(idx);
    updatePosition();

    setTimeout(function () {
        state.setManualNavActive(false);
    }, 300);
}

/** Scroll a panel to show the element with the given annotation index */
export function scrollToAnno(panel, idx) {
    var candidates = panel.querySelectorAll('[data-anno-idx="' + idx + '"]');
    var el = null;
    for (var i = 0; i < candidates.length; i++) {
        if (candidates[i].style.display !== 'none') { el = candidates[i]; break; }
    }
    if (!el) return;

    var panelRect = panel.getBoundingClientRect();
    var elRect = el.getBoundingClientRect();
    var offset = elRect.top - panelRect.top + panel.scrollTop;

    panel.scrollTop = offset - 8;
}

/** Highlight all elements with the given annotation index */
function highlightAnno(idx) {
    var prev = document.querySelectorAll('.anno-highlight');
    for (var i = 0; i < prev.length; i++) {
        prev[i].classList.remove('anno-highlight');
    }

    var els = document.querySelectorAll('[data-anno-idx="' + idx + '"]');
    for (var i = 0; i < els.length; i++) {
        els[i].classList.add('anno-highlight');
    }
}

/** Determine the annotation index closest to the top of the viewport */
export function getVisibleIdx() {
    var panel = dom.s1000dPanel;
    var elements = panel.querySelectorAll('[data-anno-idx]');
    if (elements.length === 0) return 1;

    var panelTop = panel.getBoundingClientRect().top;
    var closest = 1;
    var closestDist = Infinity;

    for (var i = 0; i < elements.length; i++) {
        var rect = elements[i].getBoundingClientRect();
        var dist = Math.abs(rect.top - panelTop);
        if (dist < closestDist) {
            closestDist = dist;
            closest = parseInt(elements[i].getAttribute('data-anno-idx'), 10);
        }
    }
    return closest;
}

/** Initialize navigation event listeners */
export function initNavigation() {
    // Register hook for badges module
    _rebuildHooks.makeNavHandler = makeNavHandler;

    if (dom.toggleBtn) {
        dom.toggleBtn.addEventListener(
            dom.toggleBtn.type === 'checkbox' ? 'change' : 'click',
            toggleAnnotations
        );
    }

    if (dom.prevBtn) {
        dom.prevBtn.addEventListener('click', function () {
            if (state.getNavMode() === 'issues') {
                if (_navHooks.navigateToPrevIssue) _navHooks.navigateToPrevIssue();
            } else {
                if (state.getCurrentIdx() <= 0) state.setCurrentIdx(getVisibleIdx());
                navigateTo(state.getCurrentIdx() - 1);
            }
        });
    }

    if (dom.nextBtn) {
        dom.nextBtn.addEventListener('click', function () {
            if (state.getNavMode() === 'issues') {
                if (_navHooks.navigateToNextIssue) _navHooks.navigateToNextIssue();
            } else {
                if (state.getCurrentIdx() <= 0) state.setCurrentIdx(getVisibleIdx());
                navigateTo(state.getCurrentIdx() + 1);
            }
        });
    }

    // Keyboard navigation (when annotations are visible)
    document.addEventListener('keydown', function (e) {
        if (!state.isAnnotationsVisible()) return;
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') return;

        if (e.key === 'ArrowDown' || e.key === 'j') {
            e.preventDefault();
            if (state.getNavMode() === 'issues') {
                if (_navHooks.navigateToNextIssue) _navHooks.navigateToNextIssue();
            } else {
                if (state.getCurrentIdx() <= 0) state.setCurrentIdx(getVisibleIdx());
                navigateTo(state.getCurrentIdx() + 1);
            }
        } else if (e.key === 'ArrowUp' || e.key === 'k') {
            e.preventDefault();
            if (state.getNavMode() === 'issues') {
                if (_navHooks.navigateToPrevIssue) _navHooks.navigateToPrevIssue();
            } else {
                if (state.getCurrentIdx() <= 0) state.setCurrentIdx(getVisibleIdx());
                navigateTo(state.getCurrentIdx() - 1);
            }
        }
    });
}
