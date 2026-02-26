/**
 * config.js — Constants and type definitions for the comparison module.
 *
 * This is a pure data module with no side effects.
 * All other modules import constants from here.
 */

/** Russian labels for annotation types */
export const ANNO_TYPE_LABELS = {
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

/** Types that represent nested lists (merged into parent during XML generation) */
export const NESTED_LIST_TYPES = {
    nested_unnumbered_list: 'unnumbered_list',
    nested_numbered_list: 'numbered_list'
};

/** Sentinel types — not real elements, filtered in sync/edit operations */
export const SENTINEL_TYPES = {
    _skip: 1,
    _extra_pdf: 1,
    _unmatched_xml: 1
};

/** 10-color palette for annotation badges */
export const ANNO_COLORS = [
    '#e74c3c', '#3498db', '#27ae60', '#f39c12', '#9b59b6',
    '#1abc9c', '#e67e22', '#2980b9', '#c0392b', '#16a085'
];
