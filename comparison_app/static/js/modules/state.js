/**
 * state.js — Centralized shared state for the comparison module.
 *
 * All mutable state lives here. Other modules import getters/setters.
 * DOM element references are cached in `dom` after initState().
 */

// ── DOM element references (populated by initState) ─────────────────
export const dom = {
    docxPanel: null,
    s1000dPanel: null,
    syncCheckbox: null,
    frameCheckbox: null,
    divider: null,
    leftPanel: null,
    rightPanel: null,
    toggleBtn: null,
    prevBtn: null,
    nextBtn: null,
    positionSpan: null,
    mismatchBadge: null,
    navModeSelect: null,
    issueTooltip: null,
    // Edit mode UI
    contextMenu: null,
    ctxLabel: null,
    ctxTypeSelect: null,
    ctxPreview: null,
    ctxMergePrev: null,
    ctxMergeNext: null,
    ctxDelete: null,
    ctxSplit: null,
    ctxCreate: null,
    ctxSave: null,
    // Toolbar buttons
    editRefBtn: null,
    saveRefBtn: null,
    verifyBtn: null,
    loopBtn: null,
    resetRefBtn: null,
    resetXmlBtn: null,
    verifyScore: null
};

/** Cache all DOM references. Call once on DOMContentLoaded. */
export function initState() {
    dom.docxPanel = document.getElementById('content-docx');
    dom.s1000dPanel = document.getElementById('content-s1000d');
    dom.syncCheckbox = document.getElementById('sync-scroll');
    dom.frameCheckbox = document.getElementById('anno-frame');
    dom.divider = document.getElementById('divider');
    dom.leftPanel = document.getElementById('panel-docx');
    dom.rightPanel = document.getElementById('panel-s1000d');
    dom.toggleBtn = document.getElementById('toggle-anno');
    dom.prevBtn = document.getElementById('anno-prev');
    dom.nextBtn = document.getElementById('anno-next');
    dom.positionSpan = document.getElementById('anno-position');
    dom.mismatchBadge = document.getElementById('mismatch-badge');
    dom.navModeSelect = document.getElementById('nav-mode');
    dom.issueTooltip = document.getElementById('issue-tooltip');
    dom.contextMenu = document.getElementById('ref-context-menu');
    dom.ctxLabel = document.getElementById('ctx-label');
    dom.ctxTypeSelect = document.getElementById('ctx-type-select');
    dom.ctxPreview = document.getElementById('ctx-preview');
    dom.ctxMergePrev = document.getElementById('ctx-merge-prev');
    dom.ctxMergeNext = document.getElementById('ctx-merge-next');
    dom.ctxDelete = document.getElementById('ctx-delete');
    dom.ctxSplit = document.getElementById('ctx-split');
    dom.ctxCreate = document.getElementById('ctx-create');
    dom.ctxSave = document.getElementById('ctx-save');
    dom.editRefBtn = document.getElementById('edit-ref-btn');
    dom.saveRefBtn = document.getElementById('save-ref-btn');
    dom.verifyBtn = document.getElementById('run-verify-btn');
    dom.loopBtn = document.getElementById('run-loop-btn');
    dom.resetRefBtn = document.getElementById('reset-ref-btn');
    dom.resetXmlBtn = document.getElementById('reset-xml-btn');
    dom.verifyScore = document.getElementById('verify-score');
}

// ── Navigation state ────────────────────────────────────────────────
let _currentIdx = 0;
let _maxLeftIdx = 0;
let _maxRightIdx = 0;
let _maxIdx = 0;
let _annotationsVisible = false;

export function getCurrentIdx() { return _currentIdx; }
export function setCurrentIdx(v) { _currentIdx = v; }
export function getMaxIdx() { return _maxIdx; }
export function getMaxLeftIdx() { return _maxLeftIdx; }
export function getMaxRightIdx() { return _maxRightIdx; }
export function setMaxIdx(left, right) {
    _maxLeftIdx = left;
    _maxRightIdx = right;
    _maxIdx = Math.max(left, right);
}
export function isAnnotationsVisible() { return _annotationsVisible; }
export function setAnnotationsVisible(v) { _annotationsVisible = v; }

// ── Issue navigation state ──────────────────────────────────────────
let _navMode = 'all';        // 'all' | 'issues'
let _issuesList = [];         // [{idx, side, category, explanation}, ...]
let _currentIssuePos = -1;
let _lastReport = null;

export function getNavMode() { return _navMode; }
export function setNavMode(v) { _navMode = v; }
export function getIssuesList() { return _issuesList; }
export function setIssuesList(v) { _issuesList = v; }
export function getCurrentIssuePos() { return _currentIssuePos; }
export function setCurrentIssuePos(v) { _currentIssuePos = v; }
export function getLastReport() { return _lastReport; }
export function setLastReport(v) { _lastReport = v; }

// ── Scroll sync state ───────────────────────────────────────────────
let _isSyncing = false;
let _manualNavActive = false;

export function isSyncing() { return _isSyncing; }
export function setSyncing(v) { _isSyncing = v; }
export function isManualNavActive() { return _manualNavActive; }
export function setManualNavActive(v) { _manualNavActive = v; }

// ── Divider drag state ──────────────────────────────────────────────
let _isDragging = false;
let _startX = 0;
let _startLeftWidth = 0;

export function isDragging() { return _isDragging; }
export function setDragging(v) { _isDragging = v; }
export function getStartX() { return _startX; }
export function setStartX(v) { _startX = v; }
export function getStartLeftWidth() { return _startLeftWidth; }
export function setStartLeftWidth(v) { _startLeftWidth = v; }

// ── Reference editing state ─────────────────────────────────────────
let _refEditMode = false;
let _referenceData = null;
let _ctxTargetIdx = -1;
let _createDomPosition = 0;
let _createBlock = null;

export function isEditMode() { return _refEditMode; }
export function setEditMode(v) { _refEditMode = v; }
export function getReferenceData() { return _referenceData; }
export function setReferenceData(v) { _referenceData = v; }
export function getCtxTargetIdx() { return _ctxTargetIdx; }
export function setCtxTargetIdx(v) { _ctxTargetIdx = v; }
export function getCreateDomPosition() { return _createDomPosition; }
export function setCreateDomPosition(v) { _createDomPosition = v; }
export function getCreateBlock() { return _createBlock; }
export function setCreateBlock(v) { _createBlock = v; }
