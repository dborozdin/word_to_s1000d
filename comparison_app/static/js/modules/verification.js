/**
 * verification.js — Verification loop, XSD issues panel, S1000D panel refresh.
 *
 * Handles running comparison verification, the verify loop (convert→compare→XSD),
 * rendering XSD validation issues, and refreshing the right panel after changes.
 */

import { dom } from './state.js';
import * as state from './state.js';
import { injectBadges, recalcMaxIdx, updatePosition } from './badges.js';
import { syncS1000dElements } from './xml-sync.js';
import { detectMismatchFn, buildIssuesList } from './mismatch.js';
import { navigateTo } from './navigation.js';

/** Run single verification */
export function runVerification() {
    if (!window.DMC_STRING) return;
    if (dom.verifyScore) {
        dom.verifyScore.style.display = 'inline-block';
        dom.verifyScore.className = 'mismatch-badge';
        dom.verifyScore.textContent = '...';
    }

    fetch('/api/verify/' + window.DMC_STRING, { method: 'POST' })
        .then(function (r) { return r.json(); })
        .then(function (data) {
            if (data.report && dom.verifyScore) {
                var score = data.report.score;
                var matched = data.report.matched_pairs ? data.report.matched_pairs.length : 0;
                var total = Math.max(data.report.left_count, data.report.right_count);
                dom.verifyScore.className = score >= 0.95 ? 'mismatch-badge ok' : 'mismatch-badge warn';
                dom.verifyScore.textContent = (score * 100).toFixed(0) + '% (' + matched + '/' + total + ')';

                // Build issues list and auto-switch to issues mode if any
                state.setLastReport(data.report);
                buildIssuesList(data.report);
                if (state.getIssuesList().length > 0 && dom.navModeSelect) {
                    state.setNavMode('issues');
                    dom.navModeSelect.value = 'issues';
                }
            } else if (data.error && dom.verifyScore) {
                dom.verifyScore.className = 'mismatch-badge warn';
                dom.verifyScore.textContent = data.error;
            }
        });
}

/** Run full verify loop (convert → compare → XSD) */
export function runVerifyLoop() {
    if (!window.DMC_STRING) return;

    var progressEl = document.getElementById('loop-progress');
    var progressBar = document.getElementById('loop-progress-bar');
    var progressText = document.getElementById('loop-progress-text');

    // Show progress bar, disable button
    if (progressEl) progressEl.style.display = 'inline-flex';
    if (dom.loopBtn) {
        dom.loopBtn.disabled = true;
        dom.loopBtn.textContent = '\u0412\u044B\u043F\u043E\u043B\u043D\u044F\u0435\u0442\u0441\u044F...';  // Выполняется...
    }
    if (dom.verifyScore) {
        dom.verifyScore.style.display = 'inline-block';
        dom.verifyScore.className = 'mismatch-badge';
        dom.verifyScore.textContent = '\u0426\u0438\u043A\u043B...';  // Цикл...
    }

    // Start the loop request
    var loopDone = false;
    var loopPromise = fetch('/api/verify-loop/' + window.DMC_STRING, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({})
    }).then(function (r) { return r.json(); });

    // Poll for progress
    var statusLabels = {
        'starting': '\u0441\u0442\u0430\u0440\u0442',
        'converting': '\u043A\u043E\u043D\u0432\u0435\u0440\u0442.',
        'comparing': '\u0441\u0440\u0430\u0432\u043D\u0435\u043D.'
    };
    var pollInterval = setInterval(function () {
        if (loopDone) { clearInterval(pollInterval); return; }
        fetch('/api/verify-loop-progress/' + window.DMC_STRING)
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.running && progressBar && progressText) {
                    var pct = Math.round((data.cycle / data.max_cycles) * 100);
                    progressBar.style.setProperty('--progress', pct + '%');
                    var label = statusLabels[data.status] || data.status;
                    progressText.textContent = data.cycle + '/' + data.max_cycles + ' ' + label;
                }
            })
            .catch(function () {});
    }, 1000);

    function onFinish() {
        loopDone = true;
        clearInterval(pollInterval);
        if (dom.loopBtn) {
            dom.loopBtn.disabled = false;
            dom.loopBtn.textContent = '\u0424\u043E\u0440\u043C\u0430\u0442\u0438\u0440\u043E\u0432\u0430\u0442\u044C \u0441\u043E\u0433\u043B\u0430\u0441\u043D\u043E \u044D\u0442\u0430\u043B\u043E\u043D\u0443';
        }
        if (progressEl) progressEl.style.display = 'none';
    }

    // Handle completion
    loopPromise.then(function (data) {
        onFinish();

        if (data.results && data.results.length > 0 && dom.verifyScore) {
            var last = data.results[data.results.length - 1];
            if (last.error) {
                dom.verifyScore.className = 'mismatch-badge warn';
                dom.verifyScore.textContent = last.error;
            } else {
                var finalScore = last.score;
                var label = (finalScore * 100).toFixed(0) + '%';
                if (!last.xsd_valid) {
                    var issueCount = (last.xsd_element_issues || []).length;
                    label += ' (XSD: ' + issueCount + ' \u043E\u0448.)';
                }
                dom.verifyScore.className = finalScore >= 0.95 ? 'mismatch-badge ok' : 'mismatch-badge warn';
                dom.verifyScore.textContent = label;

                // Build issues from the last cycle's report
                if (last.report) {
                    state.setLastReport(last.report);
                    buildIssuesList(last.report);
                    if (state.getIssuesList().length > 0 && dom.navModeSelect) {
                        state.setNavMode('issues');
                        dom.navModeSelect.value = 'issues';
                    }
                }

                // Show XSD issues panel if there are element-mapped errors
                var xsdIssues = last.xsd_element_issues || [];
                if (xsdIssues.length > 0) {
                    renderXsdIssues(xsdIssues);
                } else {
                    hideXsdIssues();
                }
            }
            refreshS1000dPanel();
        } else if (data.error && dom.verifyScore) {
            dom.verifyScore.className = 'mismatch-badge warn';
            dom.verifyScore.textContent = data.error;
        }
    }).catch(function () {
        onFinish();
        if (dom.verifyScore) {
            dom.verifyScore.className = 'mismatch-badge warn';
            dom.verifyScore.textContent = '\u041E\u0448\u0438\u0431\u043A\u0430';
        }
    });
}

// ── XSD Issues Panel ──

function renderXsdIssues(issues) {
    var panel = document.getElementById('xsd-issues-panel');
    var list = document.getElementById('xsd-issues-list');
    if (!panel || !list) return;

    list.innerHTML = '';
    panel.style.display = 'block';

    var typeLabels = {
        'heading': '\u0437\u0430\u0433\u043E\u043B.',
        'para': '\u043F\u0430\u0440.',
        'numbered_list': '\u043D\u0443\u043C.\u0441\u043F.',
        'unnumbered_list': '\u0441\u043F\u0438\u0441.',
        'table': '\u0442\u0430\u0431\u043B.',
        'figure': '\u0440\u0438\u0441.',
        'warning': '\u043F\u0440\u0435\u0434\u0443\u043F\u0440.',
        'caution': '\u0432\u043D\u0438\u043C.',
        'note': '\u043F\u0440\u0438\u043C.',
    };

    for (var i = 0; i < issues.length; i++) {
        var issue = issues[i];
        var item = document.createElement('div');
        item.className = 'xsd-issue-item';
        item.className += issue.is_user_annotated ? ' xsd-issue-user' : ' xsd-issue-auto';

        var typeStr = issue.user_type
            ? (typeLabels[issue.user_type] || issue.user_type)
            : (issue.element_tag || '?');
        var textStr = (issue.text_preview || '').substring(0, 50);
        var errorStr = (issue.xsd_error || '').substring(0, 120);
        var annotation = issue.is_user_annotated
            ? ' <small style="color:#e74c3c">(\u043F\u043E\u043B\u044C\u0437. \u0440\u0430\u0437\u043C\u0435\u0442\u043A\u0430)</small>'
            : '';

        // Show xpath for location context when available
        var locationStr = '';
        if (issue.xpath) {
            var parts = issue.xpath.split('/');
            var shortPath = parts.slice(Math.max(0, parts.length - 3)).join('/');
            locationStr = '<div class="xsd-issue-location">' + shortPath + '</div>';
        }

        item.innerHTML =
            '<span class="xsd-issue-type">' + typeStr + '</span>' + annotation +
            ' <span class="xsd-issue-text">\u00AB' + textStr + '\u00BB</span>' +
            locationStr +
            '<div class="xsd-issue-error">' + errorStr + '</div>';

        // Click to navigate to element
        if (issue.ref_idx) {
            item.style.cursor = 'pointer';
            (function (idx) {
                item.addEventListener('click', function () {
                    navigateTo(idx);
                });
            })(issue.ref_idx);
        }

        list.appendChild(item);
    }
}

function hideXsdIssues() {
    var panel = document.getElementById('xsd-issues-panel');
    if (panel) panel.style.display = 'none';
}

/** Refresh the S1000D panel content from the server */
export function refreshS1000dPanel() {
    var dmc = window.DMC_STRING;
    if (!dmc) return;

    fetch('/api/s1000d-html/' + dmc)
        .then(function (r) { return r.json(); })
        .then(function (data) {
            if (data.html) {
                dom.s1000dPanel.innerHTML = data.html;
                // Sync right panel indices to match reference, then inject badges
                syncS1000dElements();
                injectBadges(dom.s1000dPanel);
                recalcMaxIdx();
                updatePosition();
                detectMismatchFn();
            }
        })
        .catch(function () {
            // Fallback: full page reload
            window.location.reload();
        });
}

/** Initialize verification-related event listeners */
export function initVerification() {
    // Close button for XSD issues panel
    var xsdCloseBtn = document.getElementById('xsd-issues-close');
    if (xsdCloseBtn) {
        xsdCloseBtn.addEventListener('click', hideXsdIssues);
    }

    // Click on score badge → switch to issues mode and navigate to first issue
    if (dom.verifyScore) {
        dom.verifyScore.style.cursor = 'pointer';
        dom.verifyScore.addEventListener('click', function () {
            var issuesList = state.getIssuesList();
            if (issuesList.length > 0) {
                state.setNavMode('issues');
                if (dom.navModeSelect) dom.navModeSelect.value = 'issues';
                state.setCurrentIssuePos(0);
                navigateTo(issuesList[0].idx);
            }
        });
    }

    // Reset XML button
    var resetXmlBtn = document.getElementById('reset-xml-btn');
    var regenModal = document.getElementById('regen-modal');
    var regenConfirm = document.getElementById('regen-confirm');
    var regenCancel = document.getElementById('regen-cancel');
    var regenResetRef = document.getElementById('regen-reset-ref');

    if (resetXmlBtn && regenModal) {
        resetXmlBtn.addEventListener('click', function () {
            if (regenResetRef) regenResetRef.checked = false;
            regenModal.style.display = 'flex';
        });
    }

    if (regenCancel) {
        regenCancel.addEventListener('click', function () {
            regenModal.style.display = 'none';
        });
    }

    if (regenConfirm) {
        regenConfirm.addEventListener('click', function () {
            regenModal.style.display = 'none';
            var resetRef = regenResetRef && regenResetRef.checked;
            var dmc = window.DMC_STRING;
            if (!dmc) return;

            // Splash helpers
            var splash = document.getElementById('regen-splash');
            var splashText = document.getElementById('regen-splash-text');
            var splashResult = document.getElementById('regen-splash-result');
            var splashSpinner = splash ? splash.querySelector('.regen-splash-spinner') : null;
            var splashClose = document.getElementById('regen-splash-close');

            function showSplash(msg) {
                if (!splash) return;
                splashText.textContent = msg;
                splashResult.style.display = 'none';
                splashResult.className = 'regen-splash-result';
                splashResult.textContent = '';
                if (splashSpinner) splashSpinner.className = 'regen-splash-spinner';
                if (splashClose) splashClose.style.display = 'none';
                splash.style.display = 'flex';
            }

            function setSplashPhase(msg) {
                if (splashText) splashText.textContent = msg;
            }

            function finishSplash(lines, isError) {
                if (!splash) return;
                if (splashSpinner) {
                    splashSpinner.className = 'regen-splash-spinner ' + (isError ? 'error' : 'done');
                }
                splashText.textContent = isError ? '\u041F\u0440\u043E\u0438\u0437\u043E\u0448\u043B\u0430 \u043E\u0448\u0438\u0431\u043A\u0430' : '\u0413\u043E\u0442\u043E\u0432\u043E';
                splashResult.className = 'regen-splash-result' + (isError ? ' error' : '');
                splashResult.textContent = lines.join('\n');
                splashResult.style.display = 'block';
                if (splashClose) splashClose.style.display = 'inline-block';
            }

            if (splashClose) {
                splashClose.onclick = function () {
                    if (splash) splash.style.display = 'none';
                };
            }

            showSplash('\u0413\u0435\u043D\u0435\u0440\u0430\u0446\u0438\u044F XML \u0438\u0437 DOCX\u2026');

            var done = [];

            fetch('/api/regenerate/' + dmc, { method: 'POST' })
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    if (data.error) throw new Error(data.error);
                    done.push('\u2713 XML \u043F\u0435\u0440\u0435\u0433\u0435\u043D\u0435\u0440\u0438\u0440\u043E\u0432\u0430\u043D');
                    if (!resetRef) return Promise.resolve();
                    setSplashPhase('\u0421\u0431\u0440\u043E\u0441 \u044D\u0442\u0430\u043B\u043E\u043D\u0430\u2026');
                    return fetch('/api/reference/' + dmc, { method: 'DELETE' })
                        .then(function () {
                            done.push('\u2713 \u0421\u0442\u0430\u0440\u044B\u0439 \u044D\u0442\u0430\u043B\u043E\u043D \u0443\u0434\u0430\u043B\u0451\u043D');
                            setSplashPhase('\u0418\u043D\u0438\u0446\u0438\u0430\u043B\u0438\u0437\u0430\u0446\u0438\u044F \u044D\u0442\u0430\u043B\u043E\u043D\u0430 \u0438\u0437 XML\u2026');
                            return fetch('/api/reference/' + dmc + '/init', { method: 'POST' });
                        })
                        .then(function (r) { return r.json(); })
                        .then(function (d) {
                            if (d.error) throw new Error(d.error);
                            done.push('\u2713 \u042D\u0442\u0430\u043B\u043E\u043D \u0438\u043D\u0438\u0446\u0438\u0430\u043B\u0438\u0437\u0438\u0440\u043E\u0432\u0430\u043D \u043F\u043E XML');
                        });
                })
                .then(function () {
                    done.push('\u0421\u0442\u0440\u0430\u043D\u0438\u0446\u0430 \u043E\u0431\u043D\u043E\u0432\u0438\u0442\u0441\u044F \u0447\u0435\u0440\u0435\u0437 2 \u0441\u0435\u043A\u0443\u043D\u0434\u044B\u2026');
                    finishSplash(done, false);
                    setTimeout(function () { location.reload(); }, 2000);
                })
                .catch(function (err) {
                    finishSplash([err.message], true);
                });
        });
    }
}
