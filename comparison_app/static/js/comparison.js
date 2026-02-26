/**
 * Comparison viewer: scroll synchronization, panel resizing,
 * element annotations, element-level navigation, PDF overlays
 * and mismatch detection.
 */

(function () {
    var docxPanel = document.getElementById('content-docx');
    var s1000dPanel = document.getElementById('content-s1000d');
    var syncCheckbox = document.getElementById('sync-scroll');
    var frameCheckbox = document.getElementById('anno-frame');
    var divider = document.getElementById('divider');
    var leftPanel = document.getElementById('panel-docx');
    var rightPanel = document.getElementById('panel-s1000d');

    if (!docxPanel || !s1000dPanel) return;

    // ====================================================================
    // Scroll synchronization (proportional, bidirectional)
    // ====================================================================

    var isSyncing = false;
    var manualNavActive = false; // suppresses proportional sync during element nav

    function syncScroll(source, target) {
        if (!syncCheckbox || !syncCheckbox.checked || isSyncing || manualNavActive) return;
        isSyncing = true;

        var maxScroll = source.scrollHeight - source.clientHeight;
        if (maxScroll <= 0) {
            isSyncing = false;
            return;
        }

        var scrollPercent = source.scrollTop / maxScroll;
        var targetMaxScroll = target.scrollHeight - target.clientHeight;
        target.scrollTop = scrollPercent * targetMaxScroll;

        requestAnimationFrame(function () {
            isSyncing = false;
        });
    }

    docxPanel.addEventListener('scroll', function () {
        syncScroll(docxPanel, s1000dPanel);
    });

    s1000dPanel.addEventListener('scroll', function () {
        syncScroll(s1000dPanel, docxPanel);
    });

    // ====================================================================
    // Draggable divider for panel resizing
    // ====================================================================

    var isDragging = false;
    var startX = 0;
    var startLeftWidth = 0;

    divider.addEventListener('mousedown', function (e) {
        isDragging = true;
        startX = e.clientX;
        startLeftWidth = leftPanel.getBoundingClientRect().width;
        divider.classList.add('active');
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
        e.preventDefault();
    });

    document.addEventListener('mousemove', function (e) {
        if (!isDragging) return;

        var container = leftPanel.parentElement;
        var containerWidth = container.getBoundingClientRect().width;
        var dividerWidth = divider.getBoundingClientRect().width;
        var dx = e.clientX - startX;
        var newLeftWidth = startLeftWidth + dx;

        var minWidth = 200;
        var maxWidth = containerWidth - dividerWidth - minWidth;

        if (newLeftWidth >= minWidth && newLeftWidth <= maxWidth) {
            var leftPercent = (newLeftWidth / containerWidth) * 100;
            var rightPercent = ((containerWidth - newLeftWidth - dividerWidth) / containerWidth) * 100;
            leftPanel.style.flex = 'none';
            rightPanel.style.flex = 'none';
            leftPanel.style.width = leftPercent + '%';
            rightPanel.style.width = rightPercent + '%';
        }
    });

    document.addEventListener('mouseup', function () {
        if (isDragging) {
            isDragging = false;
            divider.classList.remove('active');
            document.body.style.cursor = '';
            document.body.style.userSelect = '';
        }
    });

    // ====================================================================
    // Element annotations and navigation
    // ====================================================================

    var ANNO_TYPE_LABELS = {
        para: '\u043F\u0430\u0440.',       // пар.
        numbered_list: '\u043D\u0443\u043C.\u0441\u043F.',  // нум.сп.
        unnumbered_list: '\u0441\u043F\u0438\u0441.',  // спис.
        nested_unnumbered_list: '\u0432\u043B.\u0441\u043F.', // вл.сп.
        nested_numbered_list: '\u0432\u043B.\u043D.\u0441\u043F.', // вл.н.сп.
        list: '\u0441\u043F\u0438\u0441.',  // спис. (backward compat)
        table: '\u0442\u0430\u0431\u043B.', // табл.
        figure: '\u0440\u0438\u0441.',      // рис.
        heading: '\u0437\u0430\u0433\u043E\u043B.', // загол.
        warning: '\u043F\u0440\u0435\u0434\u0443\u043F\u0440.', // предупр.
        caution: '\u0432\u043D\u0438\u043C\u0430\u043D.', // вниман.
        note: '\u043F\u0440\u0438\u043C.',  // прим.
        _extra_pdf: '?PDF',      // PDF-блок без XML-соответствия
        _unmatched_xml: '?XML'   // XML-элемент без PDF-позиции
    };

    // Types that represent nested lists (merged into parent list during XML generation,
    // no separate annotation on right panel)
    var NESTED_LIST_TYPES = {
        nested_unnumbered_list: 'unnumbered_list',
        nested_numbered_list: 'numbered_list'
    };

    // Normalize type aliases so "paragraph"↔"para", "illustration"↔"figure" etc.
    // are counted as the same type for composite numbering and sync.
    function normType(t) {
        if (t === 'paragraph' || t === 'para') return 'para';
        if (t === 'illustration' || t === 'figure') return 'figure';
        return t;
    }

    // Coarser normalization for order comparison: also collapses list variants
    // (numbered_list ↔ unnumbered_list, nested variants) since S1000D uses
    // <randomList> for all list types.
    function normTypeForOrder(t) {
        var nt = normType(t);
        if (nt === 'numbered_list' || nt === 'unnumbered_list') return 'list';
        if (nt === 'nested_numbered_list' || nt === 'nested_unnumbered_list') return 'nested_list';
        return nt;
    }

    var ANNO_COLORS = [
        '#e74c3c', '#3498db', '#27ae60', '#f39c12', '#9b59b6',
        '#1abc9c', '#e67e22', '#2980b9', '#c0392b', '#16a085'
    ];

    var toggleBtn = document.getElementById('toggle-anno');
    var prevBtn = document.getElementById('anno-prev');
    var nextBtn = document.getElementById('anno-next');
    var positionSpan = document.getElementById('anno-position');
    var mismatchBadge = document.getElementById('mismatch-badge');

    var currentIdx = 0;
    var maxLeftIdx = 0;
    var maxRightIdx = 0;
    var maxIdx = 0;
    var annotationsVisible = false;

    // --- Issue navigation state ---
    var navMode = 'all';            // 'all' | 'issues'
    var issuesList = [];            // [{idx, side, category, explanation}, ...]
    var currentIssuePos = -1;
    var lastReport = null;          // last ComparisonReport from /api/verify
    var navModeSelect = document.getElementById('nav-mode');
    var issueTooltip = document.getElementById('issue-tooltip');

    function getAnnoColor(idx) {
        return ANNO_COLORS[(idx - 1) % ANNO_COLORS.length];
    }

    function initAnnotations() {
        // For non-PDF modes, inject badges into the left (docx) panel HTML
        if (window.RENDER_MODE !== 'pdf') {
            injectBadges(docxPanel);
        }
        // Sync right panel indices to match reference, then inject badges
        _syncS1000dElements();
        injectBadges(s1000dPanel);

        recalcMaxIdx();
        updatePosition();

        // Detect mismatches for non-PDF modes
        if (window.RENDER_MODE !== 'pdf') {
            detectMismatch();
        }
    }

    function recalcMaxIdx() {
        maxLeftIdx = getMaxIdx(docxPanel);
        maxRightIdx = getMaxIdx(s1000dPanel);
        maxIdx = Math.max(maxLeftIdx, maxRightIdx);
    }

    function getMaxIdx(panel) {
        var elements = panel.querySelectorAll('[data-anno-idx]');
        var max = 0;
        for (var i = 0; i < elements.length; i++) {
            if (elements[i].style.display === 'none') continue;
            if (elements[i].classList.contains('anno-marker-unassigned')) continue;
            var idx = parseInt(elements[i].getAttribute('data-anno-idx'), 10);
            if (idx > max) max = idx;
        }
        return max;
    }

    function injectBadges(panel) {
        var elements = panel.querySelectorAll('[data-anno-idx]');
        // Collect badge-eligible elements and sort by idx for per-type counting
        var eligible = [];
        for (var i = 0; i < elements.length; i++) {
            var el = elements[i];
            if (el.classList.contains('anno-marker')) continue;
            if (el.hasAttribute('data-anno-cont')) continue;
            if (el.querySelector('.anno-badge')) continue;
            eligible.push(el);
        }
        eligible.sort(function(a, b) {
            return parseInt(a.getAttribute('data-anno-idx'), 10) -
                   parseInt(b.getAttribute('data-anno-idx'), 10);
        });

        var typeCounts = {};
        for (var i = 0; i < eligible.length; i++) {
            var el = eligible[i];
            var idx = parseInt(el.getAttribute('data-anno-idx'), 10);
            var type = normType(el.getAttribute('data-anno-type') || 'para');
            typeCounts[type] = (typeCounts[type] || 0) + 1;
            var typeNum = typeCounts[type];
            var typeLabel = ANNO_TYPE_LABELS[type] || type;
            var label = typeLabel + typeNum + ' [' + idx + ']';
            var color = getAnnoColor(idx);

            // Ensure element has relative positioning for badge
            var pos = window.getComputedStyle(el).position;
            if (pos === 'static') {
                el.style.position = 'relative';
            }

            // Start badge
            var badge = document.createElement('span');
            badge.className = 'anno-badge anno-badge-start';
            badge.textContent = label;
            badge.style.setProperty('--anno-clr', color);
            badge.setAttribute('data-badge-idx', String(idx));
            var annoSource = el.getAttribute('data-anno-source');
            if (annoSource) badge.setAttribute('data-anno-source', annoSource);
            el.insertBefore(badge, el.firstChild);

            // End marker
            var endMarker = document.createElement('span');
            endMarker.className = 'anno-badge anno-badge-end';
            endMarker.textContent = '/' + idx;
            endMarker.style.setProperty('--anno-clr', color);
            endMarker.setAttribute('data-badge-idx', String(idx));
            el.appendChild(endMarker);

            // Left border color
            el.style.setProperty('--anno-clr', color);

            // Click handlers
            badge.addEventListener('click', makeNavHandler(idx));
            endMarker.addEventListener('click', makeNavHandler(idx));
        }
    }

    function rebuildBadges(panel) {
        // 1. Remove all existing badges from the panel
        var oldBadges = panel.querySelectorAll('.anno-badge');
        for (var i = oldBadges.length - 1; i >= 0; i--) {
            oldBadges[i].parentNode.removeChild(oldBadges[i]);
        }

        // 2. Sync DOM elements with referenceData (if in edit mode)
        if (referenceData && referenceData.elements && panel === docxPanel) {
            // Collect all annotated elements, separated by type
            var pdfMarkers = panel.querySelectorAll('.anno-marker');
            var allAnno = panel.querySelectorAll('[data-anno-idx]');

            if (pdfMarkers.length > 0) {
                // PDF mode: sync all markers by position
                _syncPdfMarkers(pdfMarkers);
            } else {
                // HTML mode: sync block elements by position
                // Include cleared blocks in the query so they can be re-assigned
                var allBlocks = panel.querySelectorAll('[data-anno-idx], [data-anno-idx-cleared]');
                _syncHtmlElements(allBlocks, panel);
            }
        }

        // 3. Re-inject badges (only for HTML block elements, skips .anno-marker)
        injectBadges(panel);

        // 4. Recalculate navigation and mismatch
        recalcMaxIdx();
        updatePosition();
        detectMismatchFn();
    }

    // Helper: filter to top-level annotated elements only (skip nested)
    function _filterTopLevel(nodeList, panel) {
        var result = [];
        for (var k = 0; k < nodeList.length; k++) {
            var parent = nodeList[k].parentElement;
            var nested = false;
            while (parent && parent !== panel) {
                if (parent.hasAttribute &&
                    (parent.hasAttribute('data-anno-idx') || parent.hasAttribute('data-anno-idx-cleared'))) {
                    nested = true;
                    break;
                }
                parent = parent.parentElement;
            }
            if (!nested) result.push(nodeList[k]);
        }
        return result;
    }

    // Helper: get clean text from element (strip badges)
    function _getCleanText(el) {
        var clone = el.cloneNode(true);
        var badges = clone.querySelectorAll('.anno-badge');
        for (var i = badges.length - 1; i >= 0; i--) badges[i].parentNode.removeChild(badges[i]);
        return (clone.textContent || '').trim().substring(0, 80);
    }

    function _getMarkerOverlay(marker) {
        // marker → .pdf-overlay → .pdf-page-wrapper
        return marker.parentNode;
    }

    /** Determine page number (1-based) of an .anno-marker by its DOM position */
    function _getMarkerPage(marker) {
        var overlay = _getMarkerOverlay(marker);
        if (!overlay) return 1;
        var wrapper = overlay.parentElement;
        var allWrappers = docxPanel.querySelectorAll('.pdf-page-wrapper');
        for (var _wi = 0; _wi < allWrappers.length; _wi++) {
            if (allWrappers[_wi] === wrapper) return _wi + 1;
        }
        return 1;
    }

    /** True when the loaded reference was created by the XML-first algorithm */
    function _isXmlDerivedRef() {
        if (!referenceData || !referenceData.elements) return false;
        if (referenceData.source === 'auto_xml_derived') return true;
        return referenceData.elements.some(function (e) { return e.type_source === 'xml_derived'; });
    }

    /**
     * Normalize text for prefix-match comparison (mirrors Python _normalize_for_match).
     * Strips leading bullets/numbers, lowercases, collapses whitespace, takes first 80 chars.
     */
    function _normForMatch(text) {
        return (text || '').toLowerCase()
            .replace(/^[\-\u2013\u2014\u2022]+\s*/, '')   // bullets: –, —, •
            .replace(/^\d+[\.\)]\s+/, '')                   // "1. " / "1) "
            .replace(/^\d+(?:\.\d+)*\s+/, '')               // "3.1.2 "
            .replace(/\s+/g, ' ').trim()
            .slice(0, 80);
    }

    /**
     * Render bracket-markers for all .anno-marker elements on the PDF panel.
     * For XML-derived references: uses bbox-based positional matching so that
     * warnings/notes on page 10 don't get mapped to page-1 markers.
     * For old references: keeps the original sequential span-based mapping.
     */
    function _syncPdfMarkers(markers) {
        // Convert NodeList to array (DOM order is page-by-page top-to-bottom)
        var sorted = [];
        for (var i = 0; i < markers.length; i++) sorted.push(markers[i]);

        if (_isXmlDerivedRef()) {
            _syncPdfMarkersBbox(sorted);
        } else {
            _syncPdfMarkersSequential(sorted);
        }
    }

    /** Original sequential span-based mapping (for non-XML-derived references) */
    function _syncPdfMarkersSequential(sorted) {
        var refLen = referenceData.elements.length;
        var markerIdx = 0;
        var pdfTypeCounts = {};

        for (var r = 0; r < refLen && markerIdx < sorted.length; r++) {
            var refElem = referenceData.elements[r];
            var span = refElem.span || 1;
            var type = refElem.type;

            if (type === '_skip') {
                for (var s = 0; s < span && markerIdx < sorted.length; s++) {
                    sorted[markerIdx].style.display = 'none';
                    sorted[markerIdx].removeAttribute('data-anno-idx');
                    markerIdx++;
                }
                continue;
            }

            var idx = refElem.idx;
            var normT = normType(type);
            pdfTypeCounts[normT] = (pdfTypeCounts[normT] || 0) + 1;
            var typeNum = pdfTypeCounts[normT];
            var label = (ANNO_TYPE_LABELS[normT] || normT) + typeNum + ' [' + idx + ']';
            var color = getAnnoColor(idx);
            var pageGroups = [];
            var curGroup = null;
            var source = refElem.type_source || 'auto';

            for (var s2 = 0; s2 < span && markerIdx < sorted.length; s2++) {
                var marker = sorted[markerIdx];
                marker.setAttribute('data-anno-idx', String(idx));
                marker.setAttribute('data-anno-type', type);
                marker.setAttribute('data-anno-source', source);
                marker.style.setProperty('--anno-clr', color);
                marker.style.opacity = '';
                marker.style.borderStyle = '';
                marker.classList.remove('anno-marker-unassigned');

                var overlay = _getMarkerOverlay(marker);
                if (!curGroup || overlay !== curGroup.overlay) {
                    curGroup = {
                        overlay: overlay,
                        markers: [],
                        firstTop: parseFloat(marker.getAttribute('data-anno-top')),
                        lastBottom: parseFloat(marker.getAttribute('data-anno-bottom'))
                    };
                    pageGroups.push(curGroup);
                }
                curGroup.markers.push(marker);
                var mBottom = parseFloat(marker.getAttribute('data-anno-bottom'));
                if (mBottom > curGroup.lastBottom) curGroup.lastBottom = mBottom;
                markerIdx++;
            }

            _renderMarkerBrackets(pageGroups, label);
        }

        for (; markerIdx < sorted.length; markerIdx++) {
            _markUnassigned(sorted[markerIdx]);
        }
    }

    /**
     * Text+position-based marker mapping for XML-derived references.
     * Uses text prefix matching to find the best marker for each reference
     * element, with bbox.page as a page hint.  Falls back to position-based
     * matching when text is unavailable.  Works correctly even when markers
     * come from a different algorithm (match_pdf_to_docx) than the reference
     * (match_xml_to_pdf), because text content is the common denominator.
     */
    function _syncPdfMarkersBbox(sorted) {
        // Build flat info list with per-marker normalized text
        var allInfos = [];
        var byPage = {};

        for (var i = 0; i < sorted.length; i++) {
            var mk = sorted[i];
            var pg = _getMarkerPage(mk);
            var top = parseFloat(mk.getAttribute('data-anno-top') || '0');
            var bot = parseFloat(mk.getAttribute('data-anno-bottom') || '0');
            var rawText = mk.getAttribute('data-anno-text') || '';
            var info = {
                marker: mk, page: pg, top: top, bot: bot,
                normText: _normForMatch(rawText),
                used: false, globalIdx: i
            };
            if (!byPage[pg]) byPage[pg] = [];
            byPage[pg].push(info);
            allInfos.push(info);
        }

        var pdfTypeCounts = {};
        var refElems = referenceData.elements;

        for (var r = 0; r < refElems.length; r++) {
            var refElem = refElems[r];
            var type = refElem.type;

            if (type === '_skip') continue;
            if (type === '_unmatched_xml') continue;
            if (type === '_extra_pdf') continue;

            var refNorm = _normForMatch(refElem.text_start || '');
            var bbox = refElem.bbox;

            // Determine which markers to search: prefer same page if bbox exists
            var candidates;
            if (bbox && bbox.page) {
                candidates = (byPage[bbox.page] || []).slice();
                // Also include adjacent pages in case of cross-page elements
                var prev = byPage[bbox.page - 1] || [];
                var next = byPage[bbox.page + 1] || [];
                candidates = candidates.concat(prev, next);
            } else {
                // No bbox (e.g. newly created element) → search all markers
                candidates = allInfos;
            }

            // Find best matching unused marker by text prefix
            var bestInfo = null;
            var bestScore = -1;

            if (refNorm.length > 0) {
                for (var mi = 0; mi < candidates.length; mi++) {
                    if (candidates[mi].used) continue;
                    var cNorm = candidates[mi].normText;
                    if (!cNorm) continue;
                    // Prefix overlap score
                    var mLen = Math.min(refNorm.length, cNorm.length);
                    if (mLen === 0) continue;
                    var common = 0;
                    for (var ci = 0; ci < mLen; ci++) {
                        if (refNorm[ci] === cNorm[ci]) common++; else break;
                    }
                    var score = common / Math.max(refNorm.length, 1);
                    if (score > bestScore) { bestScore = score; bestInfo = candidates[mi]; }
                }
            }

            // Fallback: position-based matching if text match is poor
            if ((!bestInfo || bestScore < 0.3) && bbox && bbox.page) {
                var pageData = window._serverPdfBlocks
                    ? window._serverPdfBlocks[bbox.page - 1] : null;
                var pageHeight = pageData ? pageData.height : 792;
                var yTarget = (bbox.y0 / pageHeight) * 100;
                var pageMarkers = byPage[bbox.page] || [];
                var posBest = null;
                var posDist = Infinity;
                for (var pi = 0; pi < pageMarkers.length; pi++) {
                    if (pageMarkers[pi].used) continue;
                    var dist = Math.abs(pageMarkers[pi].top - yTarget);
                    if (dist < posDist) { posDist = dist; posBest = pageMarkers[pi]; }
                }
                if (posBest && posDist < 5) bestInfo = posBest;
            }

            if (!bestInfo) continue;

            bestInfo.used = true;
            var span = refElem.span || 1;
            var idx = refElem.idx;
            var normT = normType(type);
            pdfTypeCounts[normT] = (pdfTypeCounts[normT] || 0) + 1;
            var typeNum = pdfTypeCounts[normT];
            var label = (ANNO_TYPE_LABELS[normT] || normT) + typeNum + ' [' + idx + ']';
            var color = getAnnoColor(idx);
            var source = refElem.type_source || 'auto';

            // Claim anchor marker
            var anchorMarker = bestInfo.marker;
            anchorMarker.setAttribute('data-anno-idx', String(idx));
            anchorMarker.setAttribute('data-anno-type', type);
            anchorMarker.setAttribute('data-anno-source', source);
            anchorMarker.style.setProperty('--anno-clr', color);
            anchorMarker.style.opacity = '';
            anchorMarker.style.borderStyle = '';
            anchorMarker.classList.remove('anno-marker-unassigned');

            var pageGroups = [];
            var curGroup = {
                overlay: _getMarkerOverlay(anchorMarker),
                markers: [anchorMarker],
                firstTop: bestInfo.top,
                lastBottom: bestInfo.bot
            };
            pageGroups.push(curGroup);

            // Claim span-1 more consecutive unused markers in document order
            var claimed = 1;
            for (var si = bestInfo.globalIdx + 1;
                 si < allInfos.length && claimed < span; si++) {
                var mInfo = allInfos[si];
                if (mInfo.used) continue;
                mInfo.used = true;

                var marker = mInfo.marker;
                marker.setAttribute('data-anno-idx', String(idx));
                marker.setAttribute('data-anno-type', type);
                marker.setAttribute('data-anno-source', source);
                marker.style.setProperty('--anno-clr', color);
                marker.style.opacity = '';
                marker.style.borderStyle = '';
                marker.classList.remove('anno-marker-unassigned');

                var ov = _getMarkerOverlay(marker);
                if (ov !== curGroup.overlay) {
                    curGroup = {
                        overlay: ov, markers: [],
                        firstTop: mInfo.top, lastBottom: mInfo.bot
                    };
                    pageGroups.push(curGroup);
                }
                curGroup.markers.push(marker);
                if (mInfo.bot > curGroup.lastBottom) curGroup.lastBottom = mInfo.bot;
                claimed++;
            }

            _renderMarkerBrackets(pageGroups, label);
        }

        // Remaining unused markers → unassigned (available for Create)
        for (var ui = 0; ui < allInfos.length; ui++) {
            if (!allInfos[ui].used) _markUnassigned(allInfos[ui].marker);
        }
    }

    /** Render label + bracket styling for a list of page groups (shared by both sync modes) */
    function _renderMarkerBrackets(pageGroups, label) {
        for (var g = 0; g < pageGroups.length; g++) {
            var group = pageGroups[g];
            var isLast = (g === pageGroups.length - 1);
            for (var m = 0; m < group.markers.length; m++) {
                var mk = group.markers[m];
                if (m === 0) {
                    mk.style.display = '';
                    var labelEl = mk.querySelector('.marker-label');
                    var displayLabel = (g === 0) ? label : '\u21A7 ' + label;
                    if (labelEl) labelEl.textContent = displayLabel;
                    else mk.textContent = displayLabel;
                    var top = group.firstTop;
                    var bottom = isLast ? group.lastBottom : 100;
                    mk.style.top = top + '%';
                    mk.style.height = Math.max(bottom - top, 1.5) + '%';
                } else {
                    mk.style.display = 'none';
                }
            }
        }
    }

    /** Style a single marker as "unassigned" (green dashed, available for Create) */
    function _markUnassigned(um) {
        um.style.display = '';
        um.removeAttribute('data-anno-idx');
        um.classList.add('anno-marker-unassigned');
        um.style.setProperty('--anno-clr', '#27ae60');
        um.style.opacity = '0.6';
        um.style.borderStyle = 'dashed';
        var uLabel = um.querySelector('.marker-label');
        if (uLabel) uLabel.textContent = '+';
    }

    /**
     * Annotate HTML block elements on the DOCX panel.
     * For XML-derived references: uses text prefix-matching so that elements
     * are placed at the correct DOM block regardless of XML semantic order.
     * For old references: keeps the original sequential span-based mapping.
     */
    function _syncHtmlElements(allAnno, panel) {
        var annoEls = _filterTopLevel(allAnno, panel);

        if (_isXmlDerivedRef()) {
            _syncHtmlElementsText(annoEls);
        } else {
            _syncHtmlElementsSequential(annoEls);
        }
    }

    /** Original sequential span-based mapping (for non-XML-derived references) */
    function _syncHtmlElementsSequential(annoEls) {
        var refLen = referenceData.elements.length;
        var domIdx = 0;

        for (var j = 0; j < refLen; j++) {
            var refElem = referenceData.elements[j];
            var span = refElem.span || 1;

            if (refElem.type === '_skip') {
                for (var s = 0; s < span && domIdx < annoEls.length; s++) {
                    _clearAnnoEl(annoEls[domIdx]);
                    domIdx++;
                }
                continue;
            }

            var color = getAnnoColor(refElem.idx);
            var source = refElem.type_source || 'auto';

            for (var s2 = 0; s2 < span && domIdx < annoEls.length; s2++) {
                annoEls[domIdx].setAttribute('data-anno-idx', String(refElem.idx));
                annoEls[domIdx].setAttribute('data-anno-type', refElem.type);
                annoEls[domIdx].setAttribute('data-anno-source', source);
                annoEls[domIdx].style.setProperty('--anno-clr', color);
                annoEls[domIdx].removeAttribute('data-anno-idx-cleared');
                if (s2 > 0) annoEls[domIdx].setAttribute('data-anno-cont', '1');
                else annoEls[domIdx].removeAttribute('data-anno-cont');
                domIdx++;
            }
        }

        for (; domIdx < annoEls.length; domIdx++) _clearAnnoEl(annoEls[domIdx]);
    }

    /**
     * Text-based mapping for XML-derived references.
     * For each reference element find the DOM block whose text best prefix-matches
     * ref.text_start, then claim that block plus span-1 following unused blocks.
     * _extra_pdf and _unmatched_xml have no DOCX counterpart → skipped.
     */
    function _syncHtmlElementsText(annoEls) {
        // Pre-clear all blocks
        for (var ci = 0; ci < annoEls.length; ci++) _clearAnnoEl(annoEls[ci]);

        // Pre-compute normalized texts for all DOM elements
        var domNorms = [];
        for (var di = 0; di < annoEls.length; di++) {
            domNorms.push(_normForMatch(_getCleanText(annoEls[di])));
        }

        var usedDom = [];
        for (var ui = 0; ui < annoEls.length; ui++) usedDom.push(false);

        var refElems = referenceData.elements;

        for (var r = 0; r < refElems.length; r++) {
            var refElem = refElems[r];
            var type = refElem.type;

            // Types without a real DOCX block: skip
            if (type === '_skip' || type === '_extra_pdf' || type === '_unmatched_xml') continue;

            var textStart = _normForMatch(refElem.text_start || '');
            if (!textStart) continue;

            // Find DOM element with best prefix-match to text_start
            var bestIdx = -1;
            var bestScore = 0;
            for (var di2 = 0; di2 < annoEls.length; di2++) {
                if (usedDom[di2]) continue;
                var domText = domNorms[di2];
                var len = Math.min(textStart.length, domText.length);
                var pfx = 0;
                for (var ci2 = 0; ci2 < len; ci2++) {
                    if (textStart[ci2] !== domText[ci2]) break;
                    pfx++;
                }
                var score = textStart.length > 0 ? pfx / textStart.length : 0;
                if (score > bestScore) { bestScore = score; bestIdx = di2; }
            }

            if (bestIdx < 0 || bestScore < 0.3) continue; // no acceptable match

            var span = refElem.span || 1;
            var idx = refElem.idx;
            var color = getAnnoColor(idx);
            var source = refElem.type_source || 'auto';

            // Claim span blocks: anchor + (span-1) next unused in DOM order
            var claimed = 0;
            for (var si = bestIdx; si < annoEls.length && claimed < span; si++) {
                if (usedDom[si]) continue;
                usedDom[si] = true;
                annoEls[si].setAttribute('data-anno-idx', String(idx));
                annoEls[si].setAttribute('data-anno-type', type);
                annoEls[si].setAttribute('data-anno-source', source);
                annoEls[si].style.setProperty('--anno-clr', color);
                annoEls[si].removeAttribute('data-anno-idx-cleared');
                if (claimed > 0) annoEls[si].setAttribute('data-anno-cont', '1');
                else annoEls[si].removeAttribute('data-anno-cont');
                claimed++;
            }
        }
    }

    /** Clear annotation attributes from a DOM element (mark as available for Create) */
    function _clearAnnoEl(el) {
        el.removeAttribute('data-anno-idx');
        el.removeAttribute('data-anno-type');
        el.removeAttribute('data-anno-cont');
        el.removeAttribute('data-anno-source');
        el.style.removeProperty('--anno-clr');
        el.style.borderLeft = '';
        el.setAttribute('data-anno-idx-cleared', '1');
    }

    /**
     * Sync right (S1000D) panel indices to match reference data.
     * Uses type-grouped matching: K-th caution on right matches K-th caution
     * in reference, etc. This handles XSD reordering where warnings/cautions
     * float above paragraphs within a section.
     * Does NOT overwrite data-anno-type — the renderer's type is correct.
     */
    function _syncS1000dElements() {
        if (!referenceData || !referenceData.elements) return;

        var annoEls = s1000dPanel.querySelectorAll('[data-anno-idx], [data-anno-type]');
        var filtered = _filterTopLevel(annoEls, s1000dPanel);

        // Build lookup from stable_id -> ref element for ID-based matching
        var refByStableId = {};
        for (var j = 0; j < referenceData.elements.length; j++) {
            var refElem = referenceData.elements[j];
            if (refElem.type === '_skip') continue;
            if (NESTED_LIST_TYPES[refElem.type]) continue;
            var sid = refElem.stable_id || '';
            if (sid && !refByStableId[sid]) {
                refByStableId[sid] = refElem;
            }
        }

        // Build per-type idx queues for fallback matching
        var refByType = {};
        for (var j = 0; j < referenceData.elements.length; j++) {
            var refElem = referenceData.elements[j];
            if (refElem.type === '_skip') continue;
            if (NESTED_LIST_TYPES[refElem.type]) continue;
            var nt = normType(refElem.type);
            if (!refByType[nt]) refByType[nt] = [];
            refByType[nt].push(refElem.idx);
        }

        // Phase 1: Match by stable_id (data-element-id attribute)
        var usedRefIdx = {};
        var matchedEls = new Set();
        for (var i = 0; i < filtered.length; i++) {
            var el = filtered[i];
            var eid = el.getAttribute('data-element-id') || '';
            if (eid && refByStableId[eid] && !usedRefIdx[refByStableId[eid].idx]) {
                var matched = refByStableId[eid];
                el.setAttribute('data-anno-idx', String(matched.idx));
                el.style.setProperty('--anno-clr', getAnnoColor(matched.idx));
                usedRefIdx[matched.idx] = true;
                matchedEls.add(i);
            }
        }

        // Phase 2: Text-based matching for unmatched elements.
        // Compare DOM element innerText prefix against ref text_start.
        // This is more robust than type-group counters when element counts
        // differ between reference and XML.
        var refUnused = [];
        for (var j = 0; j < referenceData.elements.length; j++) {
            var refElem = referenceData.elements[j];
            if (refElem.type === '_skip') continue;
            if (NESTED_LIST_TYPES[refElem.type]) continue;
            if (usedRefIdx[refElem.idx]) continue;
            refUnused.push(refElem);
        }

        for (var i = 0; i < filtered.length; i++) {
            if (matchedEls.has(i)) continue;
            var el = filtered[i];
            var elText = (el.innerText || el.textContent || '').trim().toLowerCase();
            if (!elText) continue;
            var elPrefix = elText.substring(0, 60);

            var bestRef = null;
            var bestScore = 0;
            for (var r = 0; r < refUnused.length; r++) {
                var cand = refUnused[r];
                if (usedRefIdx[cand.idx]) continue;
                var refText = (cand.text_start || '').trim().toLowerCase();
                if (!refText) continue;

                // Prefix match: count matching chars from start
                var cmpLen = Math.min(elPrefix.length, refText.length, 50);
                var matchChars = 0;
                for (var k = 0; k < cmpLen; k++) {
                    if (elPrefix.charCodeAt(k) === refText.charCodeAt(k)) matchChars++;
                    else break;
                }
                var score = cmpLen > 0 ? matchChars / cmpLen : 0;
                // Bonus for type match
                var nt = normType(el.getAttribute('data-anno-type') || 'para');
                if (nt === normType(cand.type)) score += 0.05;

                if (score > bestScore && score > 0.5) {
                    bestScore = score;
                    bestRef = cand;
                }
            }

            if (bestRef) {
                el.setAttribute('data-anno-idx', String(bestRef.idx));
                el.style.setProperty('--anno-clr', getAnnoColor(bestRef.idx));
                usedRefIdx[bestRef.idx] = true;
                matchedEls.add(i);
            }
        }

        // Phase 3: Fallback — type-group matching for still-unmatched elements
        var typeCounters = {};
        for (var i = 0; i < filtered.length; i++) {
            if (matchedEls.has(i)) {
                var el = filtered[i];
                var rendererType = el.getAttribute('data-anno-type') || 'para';
                var nt = normType(rendererType);
                typeCounters[nt] = (typeCounters[nt] || 0) + 1;
            }
        }
        var typeCountersFallback = {};
        for (var nt2 in typeCounters) {
            typeCountersFallback[nt2] = typeCounters[nt2];
        }
        for (var i = 0; i < filtered.length; i++) {
            if (matchedEls.has(i)) continue;
            var el = filtered[i];
            var rendererType = el.getAttribute('data-anno-type') || 'para';
            var nt = normType(rendererType);
            typeCountersFallback[nt] = typeCountersFallback[nt] || 0;

            var queue = refByType[nt];
            if (queue && typeCountersFallback[nt] < queue.length) {
                var refIdx = queue[typeCountersFallback[nt]];
                if (!usedRefIdx[refIdx]) {
                    el.setAttribute('data-anno-idx', String(refIdx));
                    el.style.setProperty('--anno-clr', getAnnoColor(refIdx));
                    usedRefIdx[refIdx] = true;
                }
            }
            typeCountersFallback[nt]++;
        }

        // Nested list pass: annotate nested list DOM elements within parent lists.
        var lastListIdx = null;
        for (var j = 0; j < referenceData.elements.length; j++) {
            var refElem = referenceData.elements[j];
            if (refElem.type === '_skip') continue;

            if (NESTED_LIST_TYPES[refElem.type]) {
                if (lastListIdx === null) continue;
                var parentEl = s1000dPanel.querySelector('[data-anno-idx="' + lastListIdx + '"]');
                if (!parentEl) continue;

                var nestedLists = parentEl.querySelectorAll(
                    'ul:not([data-anno-idx]), ol:not([data-anno-idx])'
                );
                if (nestedLists.length > 0) {
                    var nestedEl = nestedLists[0];
                    nestedEl.setAttribute('data-anno-idx', String(refElem.idx));
                    nestedEl.setAttribute('data-anno-type', refElem.type);
                    nestedEl.style.setProperty('--anno-clr', getAnnoColor(refElem.idx));
                }
            } else {
                var baseType = normType(refElem.type);
                if (baseType === 'unnumbered_list' || baseType === 'numbered_list') {
                    lastListIdx = refElem.idx;
                }
            }
        }
    }

    function makeNavHandler(idx) {
        return function (e) {
            e.stopPropagation();
            navigateTo(idx);
        };
    }

    function toggleAnnotations() {
        annotationsVisible = !annotationsVisible;
        document.body.classList.toggle('show-annotations', annotationsVisible);
        if (toggleBtn) toggleBtn.classList.toggle('active', annotationsVisible);
    }

    function navigateTo(idx) {
        if (idx < 1) idx = 1;
        if (idx > maxIdx) idx = maxIdx;
        currentIdx = idx;

        manualNavActive = true;

        scrollToAnno(docxPanel, idx);
        scrollToAnno(s1000dPanel, idx);
        highlightAnno(idx);
        updatePosition();

        setTimeout(function () {
            manualNavActive = false;
        }, 300);
    }

    function scrollToAnno(panel, idx) {
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

    function getCurrentIdx() {
        var panel = s1000dPanel;
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

    function updatePosition() {
        if (!positionSpan) return;
        if (currentIdx > 0) {
            positionSpan.textContent = currentIdx + ' / ' + maxIdx;
        } else {
            positionSpan.textContent = '\u2014 / ' + maxIdx;
        }
    }

    // Event listeners
    if (toggleBtn) {
        toggleBtn.addEventListener('click', toggleAnnotations);
    }

    if (prevBtn) {
        prevBtn.addEventListener('click', function () {
            if (navMode === 'issues') {
                navigateToPrevIssue();
            } else {
                if (currentIdx <= 0) currentIdx = getCurrentIdx();
                navigateTo(currentIdx - 1);
            }
        });
    }

    if (nextBtn) {
        nextBtn.addEventListener('click', function () {
            if (navMode === 'issues') {
                navigateToNextIssue();
            } else {
                if (currentIdx <= 0) currentIdx = getCurrentIdx();
                navigateTo(currentIdx + 1);
            }
        });
    }

    // Frame checkbox toggle
    if (frameCheckbox) {
        if (frameCheckbox.checked) {
            document.body.classList.add('show-anno-frame');
        }
        frameCheckbox.addEventListener('change', function () {
            document.body.classList.toggle('show-anno-frame', this.checked);
        });
    }

    // Keyboard navigation (when annotations are visible)
    document.addEventListener('keydown', function (e) {
        if (!annotationsVisible) return;
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') return;

        if (e.key === 'ArrowDown' || e.key === 'j') {
            e.preventDefault();
            if (navMode === 'issues') {
                navigateToNextIssue();
            } else {
                if (currentIdx <= 0) currentIdx = getCurrentIdx();
                navigateTo(currentIdx + 1);
            }
        } else if (e.key === 'ArrowUp' || e.key === 'k') {
            e.preventDefault();
            if (navMode === 'issues') {
                navigateToPrevIssue();
            } else {
                if (currentIdx <= 0) currentIdx = getCurrentIdx();
                navigateTo(currentIdx - 1);
            }
        }
    });

    // ====================================================================
    // PDF text analysis and overlay creation
    // ====================================================================

    /**
     * Analyze pdf.js textContent items and group them into logical blocks.
     * Returns array of {type, yTopPct, yBottomPct, text}.
     */
    function analyzePdfTextContent(textContent, viewport) {
        var items = textContent.items;
        if (!items || items.length === 0) return [];

        var vpHeight = viewport.height;
        var vpScale = viewport.scale;

        // 1. Extract items with coordinates (convert PDF space -> viewport pixels)
        var textItems = [];
        for (var i = 0; i < items.length; i++) {
            var item = items[i];
            if (!item.str || item.str.trim() === '') continue;

            var tx = item.transform;
            // tx = [scaleX, skewX, skewY, scaleY, translateX, translateY] in PDF user-space
            var fontSizePdf = Math.abs(tx[3]) || Math.abs(tx[0]) || 12;
            var fontSize = fontSizePdf * vpScale;

            // Convert PDF coordinates (origin bottom-left) to viewport pixels (origin top-left)
            var pt = viewport.convertToViewportPoint(tx[4], tx[5]);
            var x = pt[0];
            var y = pt[1];

            textItems.push({
                str: item.str,
                x: x,
                y: y,
                fontSize: fontSize,
                width: (item.width || 0) * vpScale
            });
        }

        if (textItems.length === 0) return [];

        // 2. Sort by Y position (top to bottom), then X (left to right)
        textItems.sort(function (a, b) {
            var dy = a.y - b.y;
            if (Math.abs(dy) > 2) return dy;
            return a.x - b.x;
        });

        // 3. Group into lines (items with similar Y)
        var lines = [];
        var currentLine = [textItems[0]];
        for (var i = 1; i < textItems.length; i++) {
            var prev = currentLine[currentLine.length - 1];
            var curr = textItems[i];
            var lineThreshold = Math.max(prev.fontSize, curr.fontSize) * 0.6;
            if (Math.abs(curr.y - prev.y) <= lineThreshold) {
                currentLine.push(curr);
            } else {
                lines.push(currentLine);
                currentLine = [curr];
            }
        }
        lines.push(currentLine);

        // 4. Compute line properties
        var lineInfos = [];
        for (var i = 0; i < lines.length; i++) {
            var line = lines[i];
            var text = '';
            var maxFontSize = 0;
            var minX = Infinity;
            var avgY = 0;
            var xPositions = [];

            for (var j = 0; j < line.length; j++) {
                text += (j > 0 ? ' ' : '') + line[j].str;
                if (line[j].fontSize > maxFontSize) maxFontSize = line[j].fontSize;
                if (line[j].x < minX) minX = line[j].x;
                avgY += line[j].y;
                xPositions.push(line[j].x);
            }
            avgY /= line.length;

            lineInfos.push({
                text: text.trim(),
                fontSize: maxFontSize,
                y: avgY,
                x: minX,
                itemCount: line.length,
                xPositions: xPositions
            });
        }

        // 5. Compute median font size for classification
        var fontSizes = lineInfos.map(function (l) { return l.fontSize; });
        fontSizes.sort(function (a, b) { return a - b; });
        var medianFontSize = fontSizes[Math.floor(fontSizes.length / 2)] || 12;

        // 6. Group lines into blocks (gap > 1.5 * avgFontSize = new block)
        var blocks = [];
        var blockLines = [lineInfos[0]];
        for (var i = 1; i < lineInfos.length; i++) {
            var prevLine = lineInfos[i - 1];
            var currLine = lineInfos[i];
            var gap = currLine.y - prevLine.y;
            var threshold = medianFontSize * 1.5;

            if (gap > threshold) {
                blocks.push(blockLines);
                blockLines = [currLine];
            } else {
                blockLines.push(currLine);
            }
        }
        blocks.push(blockLines);

        // 7. Classify each block and compute positions
        var result = [];
        var dashRe = /^[\-\u2013\u2014\u2212\u2022\u25CF\u25CB]/;
        var numRe = /^\d+[\.\)]/;

        for (var b = 0; b < blocks.length; b++) {
            var bLines = blocks[b];
            var fullText = bLines.map(function (l) { return l.text; }).join(' ');
            var firstText = bLines[0].text;
            var maxFS = 0;
            for (var k = 0; k < bLines.length; k++) {
                if (bLines[k].fontSize > maxFS) maxFS = bLines[k].fontSize;
            }

            var yTop = bLines[0].y;
            var yBottom = bLines[bLines.length - 1].y + maxFS;

            // Classify
            var type = 'para';
            if (maxFS > medianFontSize * 1.3) {
                type = 'heading';
            } else if (dashRe.test(firstText.trim()) || numRe.test(firstText.trim())) {
                type = 'list';
            } else if (bLines[0].itemCount >= 3) {
                // Heuristic: many separate text fragments on one line could be a table row
                var distinctX = [];
                for (var k = 0; k < bLines[0].xPositions.length; k++) {
                    var xp = bLines[0].xPositions[k];
                    var isNew = true;
                    for (var m = 0; m < distinctX.length; m++) {
                                if (Math.abs(xp - distinctX[m]) < medianFontSize) { isNew = false; break; }
                    }
                    if (isNew) distinctX.push(xp);
                }
                if (distinctX.length >= 3) {
                    type = 'table';
                }
            }

            result.push({
                type: type,
                yTopPct: (yTop / vpHeight) * 100,
                yBottomPct: (yBottom / vpHeight) * 100,
                text: fullText.substring(0, 80)
            });
        }

        return result;
    }

    /**
     * Build blocks array from server-side PyMuPDF data for a given page.
     * Converts PDF-coordinate bbox into viewport-percentage positions.
     */
    function _buildServerBlocks(pageIndex, viewport) {
        if (!window._serverPdfBlocks || !window._serverPdfBlocks[pageIndex]) {
            console.warn('[PDF] No server blocks for page ' + pageIndex + ', using JS fallback');
            return null;
        }
        console.log('[PDF] Using server blocks for page ' + pageIndex + ': ' +
            window._serverPdfBlocks[pageIndex].blocks.length + ' blocks');

        var pageData = window._serverPdfBlocks[pageIndex];
        var scaleX = viewport.width / pageData.width;
        var scaleY = viewport.height / pageData.height;

        // Compute median font size for type classification
        var allFonts = [];
        for (var i = 0; i < pageData.blocks.length; i++) {
            allFonts.push(pageData.blocks[i].max_font_size);
        }
        allFonts.sort(function (a, b) { return a - b; });
        var medianFont = allFonts[Math.floor(allFonts.length / 2)] || 12;

        var dashRe = /^[\-\u2013\u2014\u2212\u2022\u25CF\u25CB]/;
        var numRe = /^\d+[\.\)]/;

        var blocks = [];
        for (var i = 0; i < pageData.blocks.length; i++) {
            var b = pageData.blocks[i];
            var yTopPct = (b.y0 * scaleY / viewport.height) * 100;
            var yBottomPct = (b.y1 * scaleY / viewport.height) * 100;

            // Classify type: use hybrid pre-classified type if available,
            // otherwise fall back to font-size heuristics
            var type = 'para';
            if (b._hybrid_type) {
                type = b._hybrid_type;
            } else if (b.max_font_size > medianFont * 1.3) {
                type = 'heading';
            } else if (dashRe.test(b.text.trim()) || numRe.test(b.text.trim())) {
                type = 'list';
            }

            blocks.push({
                type: type,
                yTopPct: yTopPct,
                yBottomPct: yBottomPct,
                text: b.text || '',
                elementId: b._hybrid_element_id || null
            });
        }
        return blocks;
    }

    /**
     * Create an overlay div on a PDF page wrapper with annotation markers.
     * Returns the number of blocks (annotations) created.
     * pageIndex is 0-based page index for server block lookup.
     */
    function createPdfOverlayFn(wrapper, textContent, viewport, startIdx, pageIndex) {
        // Try server-side blocks first (PyMuPDF), fallback to JS heuristics
        var blocks = _buildServerBlocks(pageIndex, viewport);
        if (!blocks) {
            blocks = analyzePdfTextContent(textContent, viewport);
        }
        if (blocks.length === 0) return 0;

        var overlay = document.createElement('div');
        overlay.className = 'pdf-overlay';

        for (var i = 0; i < blocks.length; i++) {
            var block = blocks[i];
            var idx = startIdx + i + 1; // 1-based
            var type = normType(block.type);
            var label = ANNO_TYPE_LABELS[type] || type;
            var color = getAnnoColor(idx);

            var marker = document.createElement('div');
            marker.className = 'anno-marker';
            marker.style.top = block.yTopPct + '%';
            marker.style.height = Math.max(block.yBottomPct - block.yTopPct, 1.5) + '%';
            marker.style.setProperty('--anno-clr', color);
            marker.setAttribute('data-anno-idx', String(idx));
            marker.setAttribute('data-anno-type', type);
            marker.setAttribute('data-anno-top', String(block.yTopPct));
            marker.setAttribute('data-anno-bottom', String(block.yBottomPct));
            marker.setAttribute('data-anno-text', block.text || '');
            if (block.elementId) {
                marker.setAttribute('data-element-id', block.elementId);
            }

            var labelSpan = document.createElement('span');
            labelSpan.className = 'marker-label';
            labelSpan.textContent = label + ' ' + idx;
            marker.appendChild(labelSpan);

            marker.addEventListener('click', makeNavHandler(idx));

            overlay.appendChild(marker);
        }

        wrapper.appendChild(overlay);
        return blocks.length;
    }

    // Expose for the PDF rendering module script
    window.createPdfOverlay = function (wrapper, textContent, viewport, startIdx, pageIndex) {
        var count = createPdfOverlayFn(wrapper, textContent, viewport, startIdx, pageIndex);
        // Recalculate max indices after new PDF page annotations added
        recalcMaxIdx();
        updatePosition();

        // If reference is loaded, sync ALL markers globally (position-based mapping
        // requires global view across all pages)
        if (referenceData && referenceData.elements) {
            var allMarkers = docxPanel.querySelectorAll('.anno-marker');
            if (allMarkers.length > 0) {
                _syncPdfMarkers(allMarkers);
            }
        }

        return count;
    };

    // ====================================================================
    // Mismatch detection
    // ====================================================================

    /**
     * Collect annotation types from a panel.
     * Returns array of {idx, type} sorted by idx.
     */
    function collectAnnoTypes(panel) {
        var elements = panel.querySelectorAll('[data-anno-idx]');
        var seen = {};
        var list = [];
        for (var i = 0; i < elements.length; i++) {
            // Skip hidden markers and unassigned markers
            if (elements[i].style.display === 'none') continue;
            if (elements[i].classList.contains('anno-marker-unassigned')) continue;
            var idx = parseInt(elements[i].getAttribute('data-anno-idx'), 10);
            // Deduplicate: cross-page spans produce multiple visible markers
            // with the same data-anno-idx — count each idx only once.
            if (seen[idx]) continue;
            seen[idx] = true;
            list.push({
                idx: idx,
                type: elements[i].getAttribute('data-anno-type') || 'para'
            });
        }
        list.sort(function (a, b) { return a.idx - b.idx; });
        return list;
    }

    /**
     * Detect mismatches between left and right panel annotations.
     * Updates the mismatch badge in the header.
     */
    function detectMismatchFn() {
        if (!mismatchBadge) return;

        var leftTypes = collectAnnoTypes(docxPanel);
        var rightTypes = collectAnnoTypes(s1000dPanel);

        var leftCount = leftTypes.length;
        var rightCount = rightTypes.length;

        if (leftCount === 0 && rightCount === 0) {
            mismatchBadge.style.display = 'none';
            return;
        }

        mismatchBadge.style.display = 'inline-block';

        // S1000D XSD reordering: warning/caution float before para/table/figure.
        // Exclude them when checking element order — their movement is expected.
        var XSD_FLOAT_TYPES = { 'caution': true, 'warning': true };

        var leftFiltered = leftTypes.filter(function (e) { return !XSD_FLOAT_TYPES[e.type]; });
        var rightFiltered = rightTypes.filter(function (e) { return !XSD_FLOAT_TYPES[e.type]; });

        var floatCount = leftCount - leftFiltered.length;

        if (leftCount === rightCount) {
            // Check if non-floating types match in order (using normalized types
            // so paragraph=para, illustration=figure, numbered_list=unnumbered_list)
            var orderMatch = leftFiltered.length === rightFiltered.length;
            if (orderMatch) {
                for (var i = 0; i < leftFiltered.length; i++) {
                    if (normTypeForOrder(leftFiltered[i].type) !== normTypeForOrder(rightFiltered[i].type)) {
                        orderMatch = false;
                        break;
                    }
                }
            }
            if (orderMatch) {
                mismatchBadge.className = 'mismatch-badge ok';
                mismatchBadge.textContent = '\u2713 ' + leftCount + ' \u044D\u043B\u0435\u043C.';  // ✓ N элем.
            } else {
                mismatchBadge.className = 'mismatch-badge warn';
                mismatchBadge.textContent = '\u26A0 \u041F\u043E\u0440\u044F\u0434\u043E\u043A \u0440\u0430\u0437\u043B\u0438\u0447. (' + leftCount + ')';  // ⚠ Порядок различ. (N)
                highlightMismatches(leftTypes, rightTypes);
            }
        } else {
            mismatchBadge.className = 'mismatch-badge warn';
            // ⚠ Слева X, справа Y
            mismatchBadge.textContent = '\u26A0 \u0421\u043B\u0435\u0432\u0430 ' + leftCount + ', \u0441\u043F\u0440\u0430\u0432\u0430 ' + rightCount;
            highlightMismatches(leftTypes, rightTypes);
        }
    }

    /**
     * Highlight elements that don't match between panels.
     * Uses stable_id (data-element-id) for content-based matching,
     * falls back to LCS on types for elements without IDs.
     *
     * Three highlight levels:
     *   - anno-mismatch (red): no corresponding element found
     *   - anno-type-mismatch (orange): content matches but type differs
     *   - (no class): full match
     */
    function highlightMismatches(leftTypes, rightTypes) {
        // Build right-panel lookup by stable_id (data-element-id)
        var rightByEid = {};
        for (var i = 0; i < rightTypes.length; i++) {
            var el = s1000dPanel.querySelector('[data-anno-idx="' + rightTypes[i].idx + '"]');
            var eid = el ? (el.getAttribute('data-element-id') || '') : '';
            if (eid) rightByEid[eid] = { pos: i, type: rightTypes[i].type, idx: rightTypes[i].idx };
        }

        // Build left-panel lookup by stable_id
        var leftByEid = {};
        for (var i = 0; i < leftTypes.length; i++) {
            var el = docxPanel.querySelector('[data-anno-idx="' + leftTypes[i].idx + '"]');
            var eid = el ? (el.getAttribute('data-element-id') || '') : '';
            if (eid) leftByEid[eid] = { pos: i, type: leftTypes[i].type, idx: leftTypes[i].idx };
        }

        var leftMatched = {};
        var rightMatched = {};

        // Phase 1: Match by stable_id
        for (var eid in leftByEid) {
            if (rightByEid[eid]) {
                var li = leftByEid[eid].pos;
                var ri = rightByEid[eid].pos;
                leftMatched[li] = ri;
                rightMatched[ri] = li;

                // Check type match
                if (leftByEid[eid].type !== rightByEid[eid].type) {
                    var lEl = docxPanel.querySelector('[data-anno-idx="' + leftByEid[eid].idx + '"]');
                    var rEl = s1000dPanel.querySelector('[data-anno-idx="' + rightByEid[eid].idx + '"]');
                    if (lEl) lEl.classList.add('anno-type-mismatch');
                    if (rEl) rEl.classList.add('anno-type-mismatch');
                }
            }
        }

        // Phase 2: LCS fallback for unmatched elements
        var unmatchedLeft = [];
        var unmatchedRight = [];
        for (var i = 0; i < leftTypes.length; i++) {
            if (!(i in leftMatched)) unmatchedLeft.push(i);
        }
        for (var i = 0; i < rightTypes.length; i++) {
            if (!(i in rightMatched)) unmatchedRight.push(i);
        }

        if (unmatchedLeft.length > 0 && unmatchedRight.length > 0) {
            var ulSeq = unmatchedLeft.map(function (i) { return leftTypes[i].type; });
            var urSeq = unmatchedRight.map(function (i) { return rightTypes[i].type; });
            var lcsSet = computeLCS(ulSeq, urSeq);
            for (var ul in lcsSet.leftMatched) {
                leftMatched[unmatchedLeft[ul]] = unmatchedRight[lcsSet.leftMatched[ul]];
                rightMatched[unmatchedRight[lcsSet.leftMatched[ul]]] = unmatchedLeft[ul];
            }
        }

        // Mark unmatched elements as anno-mismatch (red)
        for (var i = 0; i < leftTypes.length; i++) {
            if (!(i in leftMatched)) {
                var el = docxPanel.querySelector('[data-anno-idx="' + leftTypes[i].idx + '"]');
                if (el) el.classList.add('anno-mismatch');
            }
        }
        for (var i = 0; i < rightTypes.length; i++) {
            if (!(i in rightMatched)) {
                var el = s1000dPanel.querySelector('[data-anno-idx="' + rightTypes[i].idx + '"]');
                if (el) el.classList.add('anno-mismatch');
            }
        }
    }

    /**
     * Compute LCS and return which indices in left/right are part of the match.
     */
    function computeLCS(a, b) {
        var m = a.length;
        var n = b.length;

        // DP table
        var dp = [];
        for (var i = 0; i <= m; i++) {
            dp[i] = [];
            for (var j = 0; j <= n; j++) {
                dp[i][j] = 0;
            }
        }
        for (var i = 1; i <= m; i++) {
            for (var j = 1; j <= n; j++) {
                if (a[i - 1] === b[j - 1]) {
                    dp[i][j] = dp[i - 1][j - 1] + 1;
                } else {
                    dp[i][j] = Math.max(dp[i - 1][j], dp[i][j - 1]);
                }
            }
        }

        // Backtrack to find matched indices
        var leftMatched = {};
        var rightMatched = {};
        var i = m, j = n;
        while (i > 0 && j > 0) {
            if (a[i - 1] === b[j - 1]) {
                leftMatched[i - 1] = true;
                rightMatched[j - 1] = true;
                i--;
                j--;
            } else if (dp[i - 1][j] > dp[i][j - 1]) {
                i--;
            } else {
                j--;
            }
        }

        return { leftMatched: leftMatched, rightMatched: rightMatched };
    }

    // ====================================================================
    // Issue navigation (расхождения)
    // ====================================================================

    /**
     * Check if two types are the same after normalization.
     * paragraph=para, illustration=figure, numbered_list=unnumbered_list, etc.
     */
    function isNormalizedSame(t1, t2) {
        function n(t) {
            if (t === 'paragraph' || t === 'para') return 'para';
            if (t === 'illustration' || t === 'figure') return 'figure';
            if (t === 'numbered_list' || t === 'unnumbered_list'
                || t === 'nested_numbered_list' || t === 'nested_unnumbered_list') return 'list';
            if (t === 'heading' || t === 'header') return 'heading';
            return t;
        }
        var n1 = n(t1), n2 = n(t2);
        if (n1 === n2) return true;
        // Section-numbered lists generate <levelledPara> (heading) in XML
        if ((n1 === 'list' && n2 === 'heading') || (n1 === 'heading' && n2 === 'list')) return true;
        return false;
    }

    /**
     * Human-readable explanation for a type mismatch.
     */
    function explainTypeMismatch(refType, xmlType) {
        if (refType.indexOf('nested_') === 0 &&
            (xmlType.indexOf('list') >= 0 || xmlType === 'unnumbered_list' || xmlType === 'numbered_list'))
            return '\u0422\u0438\u043F: \u0432\u043B\u043E\u0436\u0435\u043D\u043D\u044B\u0439 \u0441\u043F\u0438\u0441\u043E\u043A \u043F\u043E\u0433\u043B\u043E\u0449\u0451\u043D \u0440\u043E\u0434\u0438\u0442\u0435\u043B\u044C\u0441\u043A\u0438\u043C \u044D\u043B\u0435\u043C\u0435\u043D\u0442\u043E\u043C';  // Тип: вложенный список поглощён родительским элементом
        if ((refType === 'caution' || refType === 'warning') && xmlType === 'para')
            return '\u0422\u0438\u043F: ' + refType + ' \u0432 \u044D\u0442\u0430\u043B\u043E\u043D\u0435 \u2192 para \u0432 XML (\u043D\u0435 \u0440\u0430\u0441\u043F\u043E\u0437\u043D\u0430\u043D \u043A\u0430\u043A \u043F\u0440\u0435\u0434\u0443\u043F\u0440\u0435\u0436\u0434\u0435\u043D\u0438\u0435)';  // Тип: X в эталоне → para в XML (не распознан как предупреждение)
        if (refType === 'para' && (xmlType === 'caution' || xmlType === 'warning'))
            return '\u0422\u0438\u043F: para \u0432 \u044D\u0442\u0430\u043B\u043E\u043D\u0435 \u2192 ' + xmlType + ' \u0432 XML';  // Тип: para в эталоне → X в XML
        return '\u0422\u0438\u043F: ' + refType + ' \u0432 \u044D\u0442\u0430\u043B\u043E\u043D\u0435 \u2260 ' + xmlType + ' \u0432 XML';  // Тип: X в эталоне ≠ Y в XML
    }

    /**
     * Build issues list from a ComparisonReport (returned by /api/verify).
     * Each issue represents a factor reducing the score.
     */
    function buildIssuesList(report) {
        issuesList = [];
        var SIM_THRESHOLD = 0.95;

        // 1. Unmatched reference elements (reduce match_ratio)
        (report.left_unmatched || []).forEach(function (idx) {
            issuesList.push({
                idx: idx, side: 'left', category: 'unmatched',
                explanation: '\u042D\u043B\u0435\u043C\u0435\u043D\u0442 \u044D\u0442\u0430\u043B\u043E\u043D\u0430 [' + idx + '] \u043D\u0435 \u043D\u0430\u0439\u0434\u0435\u043D \u0432 XML'  // Элемент эталона [N] не найден в XML
            });
        });

        // 2. Unmatched XML elements (reduce match_ratio)
        (report.right_unmatched || []).forEach(function (idx) {
            issuesList.push({
                idx: idx, side: 'right', category: 'unmatched',
                explanation: '\u042D\u043B\u0435\u043C\u0435\u043D\u0442 XML [' + idx + '] \u043D\u0435 \u043D\u0430\u0439\u0434\u0435\u043D \u0432 \u044D\u0442\u0430\u043B\u043E\u043D\u0435'  // Элемент XML [N] не найден в эталоне
            });
        });

        // 3. Type mismatches (reduce type_ratio) — only non-normalized
        (report.type_mismatches || []).forEach(function (m) {
            var refIdx = m[0], xmlIdx = m[1], refType = m[2], xmlType = m[3];
            if (isNormalizedSame(refType, xmlType)) return;
            issuesList.push({
                idx: refIdx, side: 'both', category: 'type',
                explanation: explainTypeMismatch(refType, xmlType)
            });
        });

        // 4. Low text similarity (reduce avg_text_sim)
        var unmatchedSet = {};
        (report.left_unmatched || []).forEach(function (i) { unmatchedSet[i] = true; });

        (report.text_similarities || []).forEach(function (s) {
            var refIdx = s[0], xmlIdx = s[1], sim = s[2];
            if (sim >= SIM_THRESHOLD) return;
            if (unmatchedSet[refIdx]) return;  // already reported as unmatched
            var pct = (sim * 100).toFixed(0);
            issuesList.push({
                idx: refIdx, side: 'both', category: 'text',
                explanation: '\u0422\u0435\u043A\u0441\u0442\u043E\u0432\u043E\u0435 \u0441\u0445\u043E\u0434\u0441\u0442\u0432\u043E: ' + pct + '% (\u044D\u043B\u0435\u043C\u0435\u043D\u0442 [' + refIdx + '] \u2194 [' + xmlIdx + '])'  // Текстовое сходство: N% (элемент [X] ↔ [Y])
            });
        });

        // Sort by idx
        issuesList.sort(function (a, b) { return a.idx - b.idx; });

        // Merge issues sharing the same idx: combine explanations
        var merged = [];
        for (var i = 0; i < issuesList.length; i++) {
            var prev = merged.length > 0 ? merged[merged.length - 1] : null;
            if (prev && prev.idx === issuesList[i].idx) {
                prev.explanation += ' \u2502 ' + issuesList[i].explanation;  // │ separator
            } else {
                merged.push({
                    idx: issuesList[i].idx,
                    side: issuesList[i].side,
                    category: issuesList[i].category,
                    explanation: issuesList[i].explanation
                });
            }
        }
        issuesList = merged;
        currentIssuePos = -1;
        updateNavUI();
    }

    function navigateToNextIssue() {
        if (issuesList.length === 0) return;
        currentIssuePos = (currentIssuePos + 1) % issuesList.length;
        var issue = issuesList[currentIssuePos];
        navigateTo(issue.idx);
        updateNavUI();
        showIssueTooltip(issue);
    }

    function navigateToPrevIssue() {
        if (issuesList.length === 0) return;
        currentIssuePos = (currentIssuePos - 1 + issuesList.length) % issuesList.length;
        var issue = issuesList[currentIssuePos];
        navigateTo(issue.idx);
        updateNavUI();
        showIssueTooltip(issue);
    }

    function updateNavUI() {
        if (!positionSpan) return;
        if (navMode === 'issues') {
            if (issuesList.length === 0) {
                positionSpan.textContent = '0 \u0440\u0430\u0441\u0445.';  // 0 расх.
            } else if (currentIssuePos < 0) {
                positionSpan.textContent = '\u2014 / ' + issuesList.length + ' \u0440\u0430\u0441\u0445.';  // — / N расх.
            } else {
                positionSpan.textContent = (currentIssuePos + 1) + ' / ' + issuesList.length + ' \u0440\u0430\u0441\u0445.';  // K / N расх.
            }
        } else {
            updatePosition();
            hideIssueTooltip();
        }
    }

    function showIssueTooltip(issue) {
        if (!issueTooltip) return;
        var icons = { unmatched: '\u274C', type: '\uD83D\uDD36', text: '\uD83D\uDCCA' };
        issueTooltip.textContent = (icons[issue.category] || '') + ' ' + issue.explanation;
        issueTooltip.style.display = 'block';
    }

    function hideIssueTooltip() {
        if (issueTooltip) issueTooltip.style.display = 'none';
    }

    // Nav mode selector
    if (navModeSelect) {
        navModeSelect.addEventListener('change', function () {
            navMode = this.value;
            currentIssuePos = -1;
            updateNavUI();
        });
    }

    // Expose for the PDF module to call after all pages are rendered
    window.detectMismatch = function () {
        detectMismatchFn();
    };

    // ====================================================================
    // Reference editor (etalon editing)
    // ====================================================================

    var editRefBtn = document.getElementById('edit-ref-btn');
    var saveRefBtn = document.getElementById('save-ref-btn');
    var runVerifyBtn = document.getElementById('run-verify-btn');
    var runLoopBtn = document.getElementById('run-loop-btn');
    var verifyScore = document.getElementById('verify-score');

    // Click on score badge → switch to issues mode and navigate to first issue
    if (verifyScore) {
        verifyScore.style.cursor = 'pointer';
        verifyScore.addEventListener('click', function () {
            if (issuesList.length > 0) {
                navMode = 'issues';
                if (navModeSelect) navModeSelect.value = 'issues';
                currentIssuePos = 0;
                navigateTo(issuesList[0].idx);
                updateNavUI();
                showIssueTooltip(issuesList[0]);
            }
        });
    }

    var contextMenu = document.getElementById('anno-context-menu');
    var ctxLabel = document.getElementById('ctx-label');
    var ctxTypeSelect = document.getElementById('ctx-type-select');
    var ctxPreview = document.getElementById('ctx-preview');
    var ctxMergePrev = document.getElementById('ctx-merge-prev');
    var ctxMergeNext = document.getElementById('ctx-merge-next');
    var ctxDelete = document.getElementById('ctx-delete');
    var ctxSave = document.getElementById('ctx-save');
    var ctxSplit = document.getElementById('ctx-split');
    var ctxCreate = document.getElementById('ctx-create');

    var resetRefBtn = document.getElementById('reset-ref-btn');

    var refEditMode = false;
    var referenceData = null;  // {elements: [...], ...}
    var ctxTargetIdx = -1;     // idx of element being edited in context menu
    var _createDomPosition = -1; // DOM position for Create operation
    var _createBlock = null;     // DOM element for Create operation

    function loadReference() {
        if (refEditMode) return;  // already loaded
        var dmc = window.DMC_STRING;
        if (!dmc) return;

        fetch('/api/reference/' + dmc)
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.exists) {
                    referenceData = data.reference;
                    enterEditMode();
                } else {
                    // Init from auto
                    fetch('/api/reference/' + dmc + '/init', { method: 'POST' })
                        .then(function (r) { return r.json(); })
                        .then(function (data2) {
                            if (data2.reference) {
                                referenceData = data2.reference;
                                enterEditMode();
                            }
                        });
                }
            });
    }

    function enterEditMode() {
        refEditMode = true;
        document.body.classList.add('ref-editing');
        if (saveRefBtn) saveRefBtn.style.display = '';
        if (resetRefBtn) resetRefBtn.style.display = '';
        if (runVerifyBtn) runVerifyBtn.style.display = '';
        if (runLoopBtn) runLoopBtn.style.display = '';
        if (editRefBtn) editRefBtn.classList.add('active');

        // Make sure annotations are visible
        if (!annotationsVisible) {
            toggleAnnotations();
        }

        // Sync badges with referenceData (applies saved user changes)
        rebuildBadges(docxPanel);
        // Sync right panel indices to match reference and rebuild badges
        _syncS1000dElements();
        // Remove stale badges (injected before reference was loaded)
        var oldBadges = s1000dPanel.querySelectorAll('.anno-badge');
        for (var bi = oldBadges.length - 1; bi >= 0; bi--) {
            oldBadges[bi].parentNode.removeChild(oldBadges[bi]);
        }
        injectBadges(s1000dPanel);
        recalcMaxIdx();
        updatePosition();
    }

    function exitEditMode() {
        refEditMode = false;
        document.body.classList.remove('ref-editing');
        if (saveRefBtn) saveRefBtn.style.display = 'none';
        if (resetRefBtn) resetRefBtn.style.display = 'none';
        if (runVerifyBtn) runVerifyBtn.style.display = 'none';
        if (runLoopBtn) runLoopBtn.style.display = 'none';
        if (editRefBtn) editRefBtn.classList.remove('active');
        hideContextMenu();
    }

    function saveReference() {
        if (!referenceData || !window.DMC_STRING) return;

        fetch('/api/reference/' + window.DMC_STRING, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                elements: referenceData.elements,
                source: 'auto+manual'
            })
        })
        .then(function (r) { return r.json(); })
        .then(function (data) {
            if (data.reference) {
                referenceData = data.reference;
                // Rebuild badges to reflect any changes
                rebuildBadges(docxPanel);
                // Flash save button
                if (saveRefBtn) {
                    saveRefBtn.textContent = '\u2713 \u0421\u043E\u0445\u0440.';
                    setTimeout(function () { saveRefBtn.textContent = '\u0421\u043E\u0445\u0440\u0430\u043D\u0438\u0442\u044C'; }, 1500);
                }
            }
        });
    }

    function runVerification() {
        if (!window.DMC_STRING) return;
        if (verifyScore) {
            verifyScore.style.display = 'inline-block';
            verifyScore.className = 'mismatch-badge';
            verifyScore.textContent = '...';
        }

        fetch('/api/verify/' + window.DMC_STRING, { method: 'POST' })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.report && verifyScore) {
                    var score = data.report.score;
                    var matched = data.report.matched_pairs ? data.report.matched_pairs.length : 0;
                    var total = Math.max(data.report.left_count, data.report.right_count);
                    verifyScore.className = score >= 0.95 ? 'mismatch-badge ok' : 'mismatch-badge warn';
                    verifyScore.textContent = (score * 100).toFixed(0) + '% (' + matched + '/' + total + ')';

                    // Build issues list and auto-switch to issues mode if any
                    lastReport = data.report;
                    buildIssuesList(data.report);
                    if (issuesList.length > 0 && navModeSelect) {
                        navMode = 'issues';
                        navModeSelect.value = 'issues';
                        updateNavUI();
                    }
                } else if (data.error && verifyScore) {
                    verifyScore.className = 'mismatch-badge warn';
                    verifyScore.textContent = data.error;
                }
            });
    }

    function runVerifyLoop() {
        if (!window.DMC_STRING) return;

        var progressEl = document.getElementById('loop-progress');
        var progressBar = document.getElementById('loop-progress-bar');
        var progressText = document.getElementById('loop-progress-text');

        // Show progress bar, disable button
        if (progressEl) progressEl.style.display = 'inline-flex';
        if (runLoopBtn) {
            runLoopBtn.disabled = true;
            runLoopBtn.textContent = '\u0412\u044B\u043F\u043E\u043B\u043D\u044F\u0435\u0442\u0441\u044F...';  // Выполняется...
        }
        if (verifyScore) {
            verifyScore.style.display = 'inline-block';
            verifyScore.className = 'mismatch-badge';
            verifyScore.textContent = '\u0426\u0438\u043A\u043B...';  // Цикл...
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
            if (runLoopBtn) {
                runLoopBtn.disabled = false;
                runLoopBtn.textContent = '\u0424\u043E\u0440\u043C\u0430\u0442\u0438\u0440\u043E\u0432\u0430\u0442\u044C \u0441\u043E\u0433\u043B\u0430\u0441\u043D\u043E \u044D\u0442\u0430\u043B\u043E\u043D\u0443';  // Форматировать согласно эталону
            }
            if (progressEl) progressEl.style.display = 'none';
        }

        // Handle completion
        loopPromise.then(function (data) {
            onFinish();

            if (data.results && data.results.length > 0 && verifyScore) {
                var last = data.results[data.results.length - 1];
                if (last.error) {
                    verifyScore.className = 'mismatch-badge warn';
                    verifyScore.textContent = last.error;
                } else {
                    var finalScore = last.score;
                    var label = (finalScore * 100).toFixed(0) + '%';
                    if (!last.xsd_valid) {
                        var issueCount = (last.xsd_element_issues || []).length;
                        label += ' (XSD: ' + issueCount + ' \u043E\u0448.)';
                    }
                    verifyScore.className = finalScore >= 0.95 ? 'mismatch-badge ok' : 'mismatch-badge warn';
                    verifyScore.textContent = label;

                    // Build issues from the last cycle's report
                    if (last.report) {
                        lastReport = last.report;
                        buildIssuesList(last.report);
                        if (issuesList.length > 0 && navModeSelect) {
                            navMode = 'issues';
                            navModeSelect.value = 'issues';
                            updateNavUI();
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
            } else if (data.error && verifyScore) {
                verifyScore.className = 'mismatch-badge warn';
                verifyScore.textContent = data.error;
            }
        }).catch(function () {
            onFinish();
            if (verifyScore) {
                verifyScore.className = 'mismatch-badge warn';
                verifyScore.textContent = '\u041E\u0448\u0438\u0431\u043A\u0430';
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
            'heading': '\u0437\u0430\u0433\u043E\u043B.',     // загол.
            'para': '\u043F\u0430\u0440.',           // пар.
            'numbered_list': '\u043D\u0443\u043C.\u0441\u043F.', // нум.сп.
            'unnumbered_list': '\u0441\u043F\u0438\u0441.',   // спис.
            'table': '\u0442\u0430\u0431\u043B.',         // табл.
            'figure': '\u0440\u0438\u0441.',          // рис.
            'warning': '\u043F\u0440\u0435\u0434\u0443\u043F\u0440.',      // предупр.
            'caution': '\u0432\u043D\u0438\u043C.',        // вним.
            'note': '\u043F\u0440\u0438\u043C.',          // прим.
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
                // Simplify xpath: show last 2 path segments
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

    // Close button
    var xsdCloseBtn = document.getElementById('xsd-issues-close');
    if (xsdCloseBtn) {
        xsdCloseBtn.addEventListener('click', hideXsdIssues);
    }

    function refreshS1000dPanel() {
        var dmc = window.DMC_STRING;
        if (!dmc) return;

        fetch('/api/s1000d-html/' + dmc)
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.html) {
                    s1000dPanel.innerHTML = data.html;
                    // Sync right panel indices to match reference, then inject badges
                    _syncS1000dElements();
                    injectBadges(s1000dPanel);
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

    // Context menu
    function showContextMenu(idx, x, y) {
        if (!contextMenu) return;

        ctxTargetIdx = idx;
        var elem = referenceData ? findRefElement(idx) : null;

        // If reference doesn't have this idx, build a fallback from the DOM annotation
        if (!elem) {
            var domEl = docxPanel.querySelector('[data-anno-idx="' + idx + '"]');
            var type = domEl ? (domEl.getAttribute('data-anno-type') || 'para') : 'para';
            // Prefer data-anno-text (PDF markers) over textContent (which includes labels)
            var textContent = domEl ? (domEl.getAttribute('data-anno-text') || domEl.textContent || '').substring(0, 80) : '';
            elem = { idx: idx, type: type, text_start: textContent, text_end: '' };
            // Add to reference if it exists, so edits can be saved
            if (referenceData) {
                referenceData.elements.push(elem);
                referenceData.elements.sort(function (a, b) { return a.idx - b.idx; });
            }
        }

        // Normalize legacy 'list' type to 'unnumbered_list'
        if (elem.type === 'list') elem.type = 'unnumbered_list';

        // Position menu
        contextMenu.style.display = 'block';
        contextMenu.style.left = Math.min(x, window.innerWidth - 250) + 'px';
        contextMenu.style.top = Math.min(y, window.innerHeight - 250) + 'px';

        // Fill fields
        var nt = normType(elem.type);
        if (ctxLabel) ctxLabel.textContent = (ANNO_TYPE_LABELS[nt] || nt) + ' ' + elem.idx;
        if (ctxTypeSelect) {
            ctxTypeSelect.value = elem.type;

            // Enable/disable nested list options based on previous element type
            var prevIsListType = false;
            if (referenceData && referenceData.elements) {
                var arrIdx = findRefElementIndex(idx);
                if (arrIdx > 0) {
                    var prevType = referenceData.elements[arrIdx - 1].type;
                    prevIsListType = (prevType === 'numbered_list' || prevType === 'unnumbered_list' ||
                                     prevType === 'nested_unnumbered_list' || prevType === 'nested_numbered_list');
                }
            }
            var nestedOpts = ctxTypeSelect.querySelectorAll('option[value^="nested_"]');
            for (var ni = 0; ni < nestedOpts.length; ni++) {
                nestedOpts[ni].disabled = !prevIsListType;
            }
        }
        if (ctxPreview) {
            // Read actual text from DOM blocks for accurate preview
            var span = elem.span || 1;
            var subTexts = _collectSubTexts(elem.idx, span);
            var firstLine = (subTexts.length > 0 ? subTexts[0] : elem.text_start) || '';
            var lastLine = (subTexts.length > 1 ? subTexts[subTexts.length - 1] : '') || '';
            if (!lastLine || lastLine === firstLine) {
                ctxPreview.textContent = firstLine;
            } else {
                ctxPreview.textContent = firstLine + '\n\u2026\n' + lastLine;
            }
        }

        // Restore normal edit buttons, hide create button
        if (ctxMergePrev) ctxMergePrev.style.display = '';
        if (ctxMergeNext) ctxMergeNext.style.display = '';
        if (ctxDelete) ctxDelete.style.display = '';
        if (ctxCreate) ctxCreate.style.display = 'none';

        // Show/hide split button based on span
        if (ctxSplit) {
            if (elem && (elem.span || 1) > 1) {
                ctxSplit.style.display = '';
                ctxSplit.textContent = '\u21B3 \u0420\u0430\u0437\u0434\u0435\u043B\u0438\u0442\u044C (' + (elem.span) + ')'; // ↳ Разделить (N)
            } else {
                ctxSplit.style.display = 'none';
            }
        }
    }

    function hideContextMenu() {
        if (contextMenu) contextMenu.style.display = 'none';
        ctxTargetIdx = -1;
    }

    function findRefElement(idx) {
        if (!referenceData) return null;
        for (var i = 0; i < referenceData.elements.length; i++) {
            if (referenceData.elements[i].idx === idx) return referenceData.elements[i];
        }
        return null;
    }

    function findRefElementIndex(idx) {
        if (!referenceData) return -1;
        for (var i = 0; i < referenceData.elements.length; i++) {
            if (referenceData.elements[i].idx === idx) return i;
        }
        return -1;
    }

    function updateBadgeForElement(idx, newType) {
        var nt = normType(newType);
        var label = (ANNO_TYPE_LABELS[nt] || nt) + ' ' + idx;

        // Update HTML badges (.anno-badge-start)
        var badges = docxPanel.querySelectorAll('[data-badge-idx="' + idx + '"]');
        for (var i = 0; i < badges.length; i++) {
            var badge = badges[i];
            if (badge.classList.contains('anno-badge-start')) {
                badge.textContent = label;
            }
        }
        // Update PDF markers (.anno-marker) — use child .marker-label if present
        var markers = docxPanel.querySelectorAll('.anno-marker[data-anno-idx="' + idx + '"]');
        for (var j = 0; j < markers.length; j++) {
            var labelEl = markers[j].querySelector('.marker-label');
            if (labelEl) {
                labelEl.textContent = label;
            } else {
                markers[j].textContent = label;
            }
        }
        // Update the element's data-anno-type
        var el = docxPanel.querySelector('[data-anno-idx="' + idx + '"]');
        if (el) el.setAttribute('data-anno-type', newType);
    }

    // Context menu: change type
    if (ctxTypeSelect) {
        ctxTypeSelect.addEventListener('change', function () {
            if (ctxTargetIdx < 1 || !referenceData) return;
            var elem = findRefElement(ctxTargetIdx);
            if (elem) {
                elem.type = ctxTypeSelect.value;
                elem.type_source = 'user_override';
                updateBadgeForElement(ctxTargetIdx, ctxTypeSelect.value);
                var updNt = normType(elem.type);
                if (ctxLabel) ctxLabel.textContent = (ANNO_TYPE_LABELS[updNt] || updNt) + ' ' + elem.idx;
                rebuildBadges(docxPanel);
            }
        });
    }

    var _SENTINEL_TYPES = { '_skip': 1, '_extra_pdf': 1, '_unmatched_xml': 1 };

    /** Find index of nearest non-sentinel element before arrIdx. */
    function _findPrevReal(arrIdx) {
        for (var i = arrIdx - 1; i >= 0; i--) {
            if (!_SENTINEL_TYPES[referenceData.elements[i].type]) return i;
        }
        return -1;
    }

    /** Find index of nearest non-sentinel element after arrIdx. */
    function _findNextReal(arrIdx) {
        for (var i = arrIdx + 1; i < referenceData.elements.length; i++) {
            if (!_SENTINEL_TYPES[referenceData.elements[i].type]) return i;
        }
        return -1;
    }

    // Context menu: merge with previous
    if (ctxMergePrev) {
        ctxMergePrev.addEventListener('click', function () {
            if (ctxTargetIdx < 1 || !referenceData) return;
            var arrIdx = findRefElementIndex(ctxTargetIdx);
            if (arrIdx <= 0) return;

            var prevIdx = _findPrevReal(arrIdx);
            if (prevIdx < 0) return;

            var prev = referenceData.elements[prevIdx];
            var curr = referenceData.elements[arrIdx];
            // Merge: extend prev boundaries to cover current, track span.
            // Also absorb any sentinel elements between prev and curr.
            var absorbedSpan = 0;
            for (var bi = prevIdx + 1; bi < arrIdx; bi++) {
                absorbedSpan += (referenceData.elements[bi].span || 1);
            }
            prev.text_end = curr.text_end;
            prev.span = (prev.span || 1) + absorbedSpan + (curr.span || 1);
            // Remove all elements from prevIdx+1 to arrIdx (inclusive)
            referenceData.elements.splice(prevIdx + 1, arrIdx - prevIdx);

            renumberRefElements();
            hideContextMenu();
            rebuildBadges(docxPanel);
        });
    }

    // Context menu: merge with next
    if (ctxMergeNext) {
        ctxMergeNext.addEventListener('click', function () {
            if (ctxTargetIdx < 1 || !referenceData) return;
            var arrIdx = findRefElementIndex(ctxTargetIdx);
            if (arrIdx < 0) return;

            var nextIdx = _findNextReal(arrIdx);
            if (nextIdx < 0) return;

            var curr = referenceData.elements[arrIdx];
            var next = referenceData.elements[nextIdx];
            // Merge: extend current boundaries to cover next, track span.
            // Also absorb any sentinel elements between curr and next.
            var absorbedSpan = 0;
            for (var bi = arrIdx + 1; bi < nextIdx; bi++) {
                absorbedSpan += (referenceData.elements[bi].span || 1);
            }
            curr.text_end = next.text_end;
            curr.span = (curr.span || 1) + absorbedSpan + (next.span || 1);
            // Remove all elements from arrIdx+1 to nextIdx (inclusive)
            referenceData.elements.splice(arrIdx + 1, nextIdx - arrIdx);

            renumberRefElements();
            hideContextMenu();
            rebuildBadges(docxPanel);
        });
    }

    // Context menu: delete
    // Instead of splicing, mark as _skip to preserve positional mapping
    // with PDF/HTML blocks. The marker slot is consumed but hidden.
    if (ctxDelete) {
        ctxDelete.addEventListener('click', function () {
            if (ctxTargetIdx < 1 || !referenceData) return;
            var arrIdx = findRefElementIndex(ctxTargetIdx);
            if (arrIdx < 0) return;

            referenceData.elements[arrIdx].type = '_skip';
            renumberRefElements();
            hideContextMenu();
            rebuildBadges(docxPanel);
        });
    }

    // ====================================================================
    // Split: reverse a merge operation
    // ====================================================================

    function _collectSubTexts(idx, span) {
        var texts = [];
        var isPdf = window.RENDER_MODE === 'pdf';

        if (isPdf) {
            // PDF mode: collect from all markers (including hidden span markers)
            var allMarkers = docxPanel.querySelectorAll('.anno-marker');
            var sorted = [];
            for (var i = 0; i < allMarkers.length; i++) sorted.push(allMarkers[i]);

            // Find the position of the first marker with this idx
            var startPos = -1;
            for (var i = 0; i < sorted.length; i++) {
                var mIdx = parseInt(sorted[i].getAttribute('data-anno-idx'), 10);
                if (mIdx === idx) { startPos = i; break; }
            }
            if (startPos < 0) return texts;

            for (var s = 0; s < span && (startPos + s) < sorted.length; s++) {
                var t = sorted[startPos + s].getAttribute('data-anno-text') || '';
                texts.push(t);
            }
        } else {
            // HTML mode: collect from top-level blocks
            var allAnno = docxPanel.querySelectorAll('[data-anno-idx]');
            var annoEls = _filterTopLevel(allAnno, docxPanel);

            // Find first block with this idx
            var startPos = -1;
            for (var i = 0; i < annoEls.length; i++) {
                var bIdx = parseInt(annoEls[i].getAttribute('data-anno-idx'), 10);
                if (bIdx === idx) { startPos = i; break; }
            }
            if (startPos < 0) return texts;

            for (var s = 0; s < span && (startPos + s) < annoEls.length; s++) {
                texts.push(_getCleanText(annoEls[startPos + s]));
            }
        }
        return texts;
    }

    function splitElement(idx) {
        var arrIdx = findRefElementIndex(idx);
        if (arrIdx < 0) return;
        var elem = referenceData.elements[arrIdx];
        var span = elem.span || 1;
        if (span <= 1) return;

        var subTexts = _collectSubTexts(idx, span);
        var newElems = [];
        for (var s = 0; s < span; s++) {
            var t = subTexts[s] || '';
            newElems.push({
                idx: 0, type: elem.type,
                text_start: t.substring(0, 60),
                text_end: t.substring(Math.max(0, t.length - 40)),
                span: 1
            });
        }
        // ES5-safe splice to replace one element with multiple
        Array.prototype.splice.apply(referenceData.elements, [arrIdx, 1].concat(newElems));
        renumberRefElements();
        hideContextMenu();
        rebuildBadges(docxPanel);
    }

    if (ctxSplit) {
        ctxSplit.addEventListener('click', function () {
            if (ctxTargetIdx < 1 || !referenceData) return;
            splitElement(ctxTargetIdx);
        });
    }

    // ====================================================================
    // Create: add a new element from an unassigned block
    // ====================================================================

    function _determineInsertPosition(domPosition) {
        if (!referenceData || !referenceData.elements.length) return 0;
        // Only count elements that actually consume markers
        // (skip sentinel types that have no PDF marker)
        var cumulative = 0;
        for (var i = 0; i < referenceData.elements.length; i++) {
            var t = referenceData.elements[i].type;
            if (t === '_skip' || t === '_extra_pdf' || t === '_unmatched_xml') continue;
            cumulative += (referenceData.elements[i].span || 1);
            if (cumulative > domPosition) return i;
        }
        return referenceData.elements.length;
    }

    function showCreateMenu(block, domPosition, x, y) {
        if (!contextMenu) return;

        _createBlock = block;
        _createDomPosition = domPosition;
        ctxTargetIdx = -999; // special marker for create mode

        contextMenu.style.display = 'block';
        contextMenu.style.left = Math.min(x, window.innerWidth - 250) + 'px';
        contextMenu.style.top = Math.min(y, window.innerHeight - 250) + 'px';

        if (ctxLabel) ctxLabel.textContent = '\u0421\u043E\u0437\u0434\u0430\u0442\u044C \u044D\u043B\u0435\u043C\u0435\u043D\u0442'; // Создать элемент
        if (ctxTypeSelect) ctxTypeSelect.value = 'para';
        if (ctxPreview) ctxPreview.textContent = block.getAttribute('data-anno-text') || _getCleanText(block) || '';

        // Hide normal edit buttons, show create button
        if (ctxMergePrev) ctxMergePrev.style.display = 'none';
        if (ctxMergeNext) ctxMergeNext.style.display = 'none';
        if (ctxDelete) ctxDelete.style.display = 'none';
        if (ctxSplit) ctxSplit.style.display = 'none';
        if (ctxCreate) ctxCreate.style.display = '';
    }

    if (ctxCreate) {
        ctxCreate.addEventListener('click', function () {
            if (!referenceData) return;
            var type = ctxTypeSelect ? ctxTypeSelect.value : 'para';
            var text = '';
            if (_createBlock) {
                // For PDF markers, textContent is just the label ("+"),
                // so prefer data-anno-text which holds the actual block text.
                text = _createBlock.getAttribute('data-anno-text')
                    || _getCleanText(_createBlock) || '';
            }
            var insertAt = _determineInsertPosition(_createDomPosition);
            var newElem = {
                idx: 0, type: type,
                text_start: text.substring(0, 60),
                text_end: text.substring(Math.max(0, text.length - 40)),
                span: 1
            };
            referenceData.elements.splice(insertAt, 0, newElem);
            renumberRefElements();
            hideContextMenu();
            rebuildBadges(docxPanel);
        });
    }

    // Click handler for unassigned blocks in edit mode
    docxPanel.addEventListener('click', function (e) {
        if (!refEditMode || !referenceData) return;

        // Check for HTML unassigned blocks
        var clearedBlock = e.target.closest('[data-anno-idx-cleared]');
        // Check for PDF unassigned markers
        var unassignedMarker = e.target.closest('.anno-marker-unassigned');

        if (!clearedBlock && !unassignedMarker) return;

        e.stopPropagation();
        e.preventDefault();

        var block = clearedBlock || unassignedMarker;
        var domPosition = 0;

        if (clearedBlock) {
            // Compute position among all top-level blocks
            var allAnno = docxPanel.querySelectorAll('[data-anno-idx], [data-anno-idx-cleared]');
            var topLevel = _filterTopLevel(allAnno, docxPanel);
            for (var i = 0; i < topLevel.length; i++) {
                if (topLevel[i] === clearedBlock) { domPosition = i; break; }
            }
        } else {
            // PDF: compute position among all markers
            var allMarkers = docxPanel.querySelectorAll('.anno-marker');
            for (var i = 0; i < allMarkers.length; i++) {
                if (allMarkers[i] === unassignedMarker) { domPosition = i; break; }
            }
        }

        showCreateMenu(block, domPosition, e.clientX, e.clientY);
    }, true); // useCapture to intercept before other handlers

    // Context menu: save reference
    if (ctxSave) {
        ctxSave.addEventListener('click', function () {
            // Immediately rebuild badges to show pending changes
            rebuildBadges(docxPanel);
            saveReference();
            ctxSave.textContent = '\u2713 \u0421\u043E\u0445\u0440.';
            ctxSave.classList.add('saved');
            setTimeout(function () {
                ctxSave.textContent = '\uD83D\uDCBE \u0421\u043E\u0445\u0440\u0430\u043D\u0438\u0442\u044C';
                ctxSave.classList.remove('saved');
            }, 1500);
            hideContextMenu();
        });
    }

    function renumberRefElements() {
        var num = 0;
        for (var i = 0; i < referenceData.elements.length; i++) {
            if (referenceData.elements[i].type === '_skip') {
                referenceData.elements[i].idx = 0;
            } else {
                num++;
                referenceData.elements[i].idx = num;
            }
        }
    }

    // Close context menu on outside click (but not when clicking a badge/marker)
    document.addEventListener('click', function (e) {
        if (contextMenu && contextMenu.style.display !== 'none') {
            if (!contextMenu.contains(e.target) &&
                !e.target.closest('.anno-badge-start') &&
                !e.target.closest('.anno-marker')) {
                hideContextMenu();
            }
        }
    });

    // Hook badge/marker clicks in edit mode (capture phase to intercept before
    // the badge's own handler which calls stopPropagation).
    // Supports both HTML badges (.anno-badge-start) and PDF markers (.anno-marker).
    docxPanel.addEventListener('click', function (e) {
        if (!refEditMode) return;

        // Try HTML badge first, then PDF marker
        var badge = e.target.closest('.anno-badge-start');
        var marker = badge ? null : e.target.closest('.anno-marker');
        if (!badge && !marker) return;

        e.stopPropagation();
        e.preventDefault();
        e.stopImmediatePropagation();

        var idx;
        if (badge) {
            idx = parseInt(badge.getAttribute('data-badge-idx'), 10);
        } else {
            idx = parseInt(marker.getAttribute('data-anno-idx'), 10);
        }
        if (idx > 0) {
            showContextMenu(idx, e.clientX, e.clientY);
        }
    }, true);  // useCapture = true

    // Button handlers
    if (editRefBtn) {
        editRefBtn.addEventListener('click', function () {
            if (refEditMode) {
                exitEditMode();
            } else {
                loadReference();
            }
        });
    }

    if (saveRefBtn) {
        saveRefBtn.addEventListener('click', saveReference);
    }

    if (runVerifyBtn) {
        runVerifyBtn.addEventListener('click', runVerification);
    }

    if (runLoopBtn) {
        runLoopBtn.addEventListener('click', runVerifyLoop);
    }

    if (resetRefBtn) {
        resetRefBtn.addEventListener('click', function () {
            if (!window.DMC_STRING) return;
            if (!confirm('\u0423\u0434\u0430\u043B\u0438\u0442\u044C \u0442\u0435\u043A\u0443\u0449\u0438\u0439 \u044D\u0442\u0430\u043B\u043E\u043D \u0438 \u0441\u043E\u0437\u0434\u0430\u0442\u044C \u0437\u0430\u043D\u043E\u0432\u043E \u0438\u0437 \u0430\u0432\u0442\u043E\u043C\u0430\u0442\u0438\u0447\u0435\u0441\u043A\u043E\u0439 \u0440\u0430\u0437\u043C\u0435\u0442\u043A\u0438?')) return;

            resetRefBtn.disabled = true;
            resetRefBtn.textContent = '...';

            fetch('/api/reference/' + window.DMC_STRING, { method: 'DELETE' })
                .then(function (r) { return r.json(); })
                .then(function () {
                    return fetch('/api/reference/' + window.DMC_STRING + '/init', { method: 'POST' });
                })
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    if (data.reference) {
                        referenceData = data.reference;
                        rebuildBadges(docxPanel);
                    }
                    resetRefBtn.disabled = false;
                    resetRefBtn.textContent = '\u0421\u0431\u0440\u043E\u0441\u0438\u0442\u044C \u044D\u0442\u0430\u043B\u043E\u043D';
                })
                .catch(function () {
                    resetRefBtn.disabled = false;
                    resetRefBtn.textContent = '\u0421\u0431\u0440\u043E\u0441\u0438\u0442\u044C \u044D\u0442\u0430\u043B\u043E\u043D';
                    alert('\u041E\u0448\u0438\u0431\u043A\u0430 \u043F\u0440\u0438 \u0441\u0431\u0440\u043E\u0441\u0435 \u044D\u0442\u0430\u043B\u043E\u043D\u0430');
                });
        });
    }

    // ====================================================================
    // Reset XML button — regenerate XML from DOCX
    // ====================================================================
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
                splashText.textContent = isError ? 'Произошла ошибка' : 'Готово';
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

            showSplash('Генерация XML из DOCX…');

            var done = [];

            fetch('/api/regenerate/' + dmc, { method: 'POST' })
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    if (data.error) throw new Error(data.error);
                    done.push('✓ XML перегенерирован');
                    if (!resetRef) return Promise.resolve();
                    setSplashPhase('Сброс эталона…');
                    return fetch('/api/reference/' + dmc, { method: 'DELETE' })
                        .then(function () {
                            done.push('✓ Старый эталон удалён');
                            setSplashPhase('Инициализация эталона из XML…');
                            return fetch('/api/reference/' + dmc + '/init', { method: 'POST' });
                        })
                        .then(function (r) { return r.json(); })
                        .then(function (d) {
                            if (d.error) throw new Error(d.error);
                            done.push('✓ Эталон инициализирован по XML');
                        });
                })
                .then(function () {
                    done.push('Страница обновится через 2 секунды…');
                    finishSplash(done, false);
                    setTimeout(function () { location.reload(); }, 2000);
                })
                .catch(function (err) {
                    finishSplash([err.message], true);
                });
        });
    }

    // ====================================================================
    // Initialize
    // ====================================================================
    initAnnotations();

    // Auto-load reference if one already exists for this DMC
    (function autoLoadReference() {
        var dmc = window.DMC_STRING;
        if (!dmc) return;

        fetch('/api/reference/' + dmc)
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.exists) {
                    referenceData = data.reference;
                    enterEditMode();
                }
            })
            .catch(function () { /* silently fail */ });
    })();
})();
