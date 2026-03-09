/**
 * MyRisk 공통 JavaScript 유틸리티.
 * 숫자·날짜·금액 포맷, 심야 시간 판정, fetch 래퍼 등 전 모듈에서 사용하는 함수.
 */

/* ── 숫자 포맷 ─────────────────────────────────── */

function formatNumber(num) {
    return num.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

function formatAmount(value) {
    if (value === null || value === undefined || value === '') return '0';
    const num = parseFloat(value);
    if (isNaN(num)) return '0';
    return Math.round(num).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

/* ── 날짜·시간 포맷 ────────────────────────────── */

function formatDate(dateStr, useDot) {
    if (useDot === undefined) useDot = false;
    if (!dateStr || dateStr === null || dateStr === undefined || dateStr === '') return '';
    try {
        var date = new Date(dateStr);
        if (isNaN(date.getTime())) {
            if (typeof dateStr === 'string') {
                if (useDot && dateStr.includes('.')) return dateStr;
                if (!useDot && dateStr.includes('/')) return dateStr;
            }
            return dateStr;
        }
        var year = date.getFullYear().toString().slice(-2);
        var month = (date.getMonth() + 1).toString().padStart(2, '0');
        var day = date.getDate().toString().padStart(2, '0');
        var sep = useDot ? '.' : '/';
        return year + sep + month + sep + day;
    } catch (e) {
        return dateStr;
    }
}

function formatTime(timeStr) {
    if (!timeStr || timeStr === null || timeStr === undefined || timeStr === '') return '';
    var str = timeStr.toString().trim();
    if (/^\d{2}:\d{2}:\d{2}$/.test(str)) return str;
    if (/^\d{2}:\d{2}$/.test(str)) return str + ':00';
    return str;
}

/* ── 심야 시간 판정 ────────────────────────────── */

function timeToSeconds(s) {
    if (!s || s === null || s === undefined) return null;
    var str = String(s).trim();
    var h, m, sec;
    if (str.includes(':')) {
        var p = str.split(':');
        h = parseInt(p[0], 10) || 0;
        m = parseInt(p[1], 10) || 0;
        sec = parseInt(p[2], 10) || 0;
    } else {
        var cleaned = str.replace(/\D/g, '');
        if (cleaned.length >= 6) {
            h = parseInt(cleaned.substr(0, 2), 10) || 0;
            m = parseInt(cleaned.substr(2, 2), 10) || 0;
            sec = parseInt(cleaned.substr(4, 2), 10) || 0;
        } else return null;
    }
    return h * 3600 + m * 60 + sec;
}

function isTimeInSimyaRanges(timeStr, ranges) {
    if (!ranges || ranges.length === 0) return false;
    var t = timeToSeconds(timeStr);
    if (t === null || t === 0) return false;
    for (var i = 0; i < ranges.length; i++) {
        var start = timeToSeconds(ranges[i].start);
        var end = timeToSeconds(ranges[i].end);
        if (start === null || end === null) continue;
        if (end >= start) {
            if (t >= start && t <= end) return true;
        } else {
            if (t >= start || t <= end) return true;
        }
    }
    return false;
}

/* ── Fetch 래퍼 ────────────────────────────────── */

var FETCH_TIMEOUT_MS = 120000;

function fetchWithTimeout(url, options, timeoutMs) {
    var ms = timeoutMs || FETCH_TIMEOUT_MS;
    var ctrl = new AbortController();
    var id = setTimeout(function() { ctrl.abort(); }, ms);
    return fetch(url, Object.assign({}, options, { signal: ctrl.signal }))
        .finally(function() { clearTimeout(id); });
}
