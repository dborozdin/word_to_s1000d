/**
 * layout.js — Scroll synchronization and panel divider resizing.
 *
 * Handles proportional bidirectional scroll sync between left and right panels,
 * and the draggable divider for panel width adjustment.
 */

import { dom } from './state.js';
import * as state from './state.js';

/** Proportional scroll sync: scrolls target to same % as source */
function syncScroll(source, target) {
    if (!dom.syncCheckbox || !dom.syncCheckbox.checked || state.isSyncing() || state.isManualNavActive()) return;
    state.setSyncing(true);

    var maxScroll = source.scrollHeight - source.clientHeight;
    if (maxScroll <= 0) {
        state.setSyncing(false);
        return;
    }

    var scrollPercent = source.scrollTop / maxScroll;
    var targetMaxScroll = target.scrollHeight - target.clientHeight;
    target.scrollTop = scrollPercent * targetMaxScroll;

    requestAnimationFrame(function () {
        state.setSyncing(false);
    });
}

/** Initialize scroll sync and divider drag handlers */
export function initLayout() {
    if (!dom.docxPanel || !dom.s1000dPanel) return;

    // Bidirectional scroll sync
    dom.docxPanel.addEventListener('scroll', function () {
        syncScroll(dom.docxPanel, dom.s1000dPanel);
    });

    dom.s1000dPanel.addEventListener('scroll', function () {
        syncScroll(dom.s1000dPanel, dom.docxPanel);
    });

    // Draggable divider
    if (dom.divider) {
        dom.divider.addEventListener('mousedown', function (e) {
            state.setDragging(true);
            state.setStartX(e.clientX);
            state.setStartLeftWidth(dom.leftPanel.getBoundingClientRect().width);
            dom.divider.classList.add('active');
            document.body.style.cursor = 'col-resize';
            document.body.style.userSelect = 'none';
            e.preventDefault();
        });

        document.addEventListener('mousemove', function (e) {
            if (!state.isDragging()) return;

            var container = dom.leftPanel.parentElement;
            var containerWidth = container.getBoundingClientRect().width;
            var dividerWidth = dom.divider.getBoundingClientRect().width;
            var dx = e.clientX - state.getStartX();
            var newLeftWidth = state.getStartLeftWidth() + dx;

            var minWidth = 200;
            var maxWidth = containerWidth - dividerWidth - minWidth;

            if (newLeftWidth >= minWidth && newLeftWidth <= maxWidth) {
                var leftPercent = (newLeftWidth / containerWidth) * 100;
                var rightPercent = ((containerWidth - newLeftWidth - dividerWidth) / containerWidth) * 100;
                dom.leftPanel.style.flex = 'none';
                dom.rightPanel.style.flex = 'none';
                dom.leftPanel.style.width = leftPercent + '%';
                dom.rightPanel.style.width = rightPercent + '%';
            }
        });

        document.addEventListener('mouseup', function () {
            if (state.isDragging()) {
                state.setDragging(false);
                dom.divider.classList.remove('active');
                document.body.style.cursor = '';
                document.body.style.userSelect = '';
            }
        });
    }

    // Frame checkbox toggle
    if (dom.frameCheckbox) {
        if (dom.frameCheckbox.checked) {
            document.body.classList.add('show-anno-frame');
        }
        dom.frameCheckbox.addEventListener('change', function () {
            document.body.classList.toggle('show-anno-frame', this.checked);
        });
    }
}
