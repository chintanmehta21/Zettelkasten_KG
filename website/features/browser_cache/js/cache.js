(function () {
  'use strict';

  var VERSION = 'v1';
  var STATE_KEY = 'zk.bc.' + VERSION;
  var RETURN_KEY = 'zk.bc.return.' + VERSION;
  var STATE_TTL_MS = 180 * 24 * 60 * 60 * 1000; // 180 days
  var RETURN_TTL_MS = 15 * 60 * 1000; // 15 minutes
  var MAX_STATE_BYTES = 256;
  var MAX_RETURN_BYTES = 96;

  function now() {
    return Date.now();
  }

  function storageAvailable(storage) {
    try {
      return !!storage && typeof storage.getItem === 'function';
    } catch (_err) {
      return false;
    }
  }

  function isPath(value) {
    return typeof value === 'string' && value.length > 0 && value.length <= 128 && value[0] === '/' && value.indexOf('//') !== 0;
  }

  function cloneDefaultState() {
    return {
      a: 0,
      h: 0,
      l: '/home',
      t: '',
      u: 0,
    };
  }

  function safeParse(value) {
    if (!value) return null;
    try {
      return JSON.parse(value);
    } catch (_err) {
      return null;
    }
  }

  function safeGet(storage, key) {
    if (!storageAvailable(storage)) return null;
    try {
      return safeParse(storage.getItem(key));
    } catch (_err) {
      return null;
    }
  }

  function safeSet(storage, key, data, maxBytes) {
    if (!storageAvailable(storage)) return false;
    try {
      var payload = JSON.stringify(data);
      if (payload.length > maxBytes) return false;
      storage.setItem(key, payload);
      return true;
    } catch (_err) {
      return false;
    }
  }

  function safeRemove(storage, key) {
    if (!storageAvailable(storage)) return;
    try {
      storage.removeItem(key);
    } catch (_err) {
      // no-op
    }
  }

  function normalizeState(raw) {
    var state = cloneDefaultState();
    if (!raw || typeof raw !== 'object') {
      return state;
    }

    if (raw.a === 1 || raw.a === 0) {
      state.a = raw.a ? 1 : 0;
    } else if (raw.allowCredentialStorage === true) {
      state.a = 1;
    } else if (raw.allowCredentialStorage === false) {
      state.a = 0;
    }

    if (raw.h === 1 || raw.h === 0) {
      state.h = raw.h ? 1 : 0;
    } else if (raw.hasLoggedIn === true) {
      state.h = 1;
    } else if (raw.hasLoggedIn === false) {
      state.h = 0;
    }

    if (isPath(raw.l)) {
      state.l = raw.l;
    } else if (isPath(raw.landingPath)) {
      state.l = raw.landingPath;
    }

    if (typeof raw.t === 'string' && raw.t.length === 0) {
      state.t = '';
    } else if (typeof raw.theme === 'string' && raw.theme.length === 0) {
      state.t = '';
    }

    if (typeof raw.u === 'number' && raw.u > 0) {
      state.u = raw.u;
    } else if (typeof raw.updatedAt === 'number' && raw.updatedAt > 0) {
      state.u = raw.updatedAt;
    } else if (typeof raw.updated_at === 'number' && raw.updated_at > 0) {
      state.u = raw.updated_at;
    }

    return state;
  }

  function readState() {
    var state = safeGet(window.localStorage, STATE_KEY);
    if (!state) {
      return null;
    }

    if (typeof state.u === 'number' && state.u > 0 && now() - state.u > STATE_TTL_MS) {
      safeRemove(window.localStorage, STATE_KEY);
      return null;
    }

    return normalizeState(state);
  }

  function writeState(next) {
    var compact = {
      a: next.a ? 1 : 0,
      h: next.h ? 1 : 0,
      l: isPath(next.l) ? next.l : '/home',
      t: '',
      u: next.u || now(),
    };

    if (compact.a === 0 && compact.h === 0 && compact.l === '/home' && compact.t === '') {
      safeRemove(window.localStorage, STATE_KEY);
      return compact;
    }

    safeSet(window.localStorage, STATE_KEY, compact, MAX_STATE_BYTES);
    return compact;
  }

  function getDefaultPublicState() {
    return {
      allowCredentialStorage: false,
      hasLoggedIn: false,
      landingPath: '/home',
      theme: '',
      updatedAt: 0,
    };
  }

  function getState() {
    var state = readState();
    if (!state) {
      return getDefaultPublicState();
    }

    return {
      allowCredentialStorage: !!state.a,
      hasLoggedIn: !!state.h,
      landingPath: isPath(state.l) ? state.l : '/home',
      theme: '',
      updatedAt: state.u || 0,
    };
  }

  function patchState(partial) {
    if (!partial || typeof partial !== 'object') {
      return getState();
    }

    var current = readState() || cloneDefaultState();
    var next = {
      a: current.a ? 1 : 0,
      h: current.h ? 1 : 0,
      l: isPath(current.l) ? current.l : '/home',
      t: '',
      u: now(),
    };

    if (Object.prototype.hasOwnProperty.call(partial, 'allowCredentialStorage')) {
      next.a = partial.allowCredentialStorage ? 1 : 0;
    }
    if (Object.prototype.hasOwnProperty.call(partial, 'hasLoggedIn')) {
      next.h = partial.hasLoggedIn ? 1 : 0;
    }
    if (typeof partial.landingPath === 'string' && isPath(partial.landingPath)) {
      next.l = partial.landingPath;
    }

    if (next.a === 0 && next.h === 0 && next.l === '/home') {
      safeRemove(window.localStorage, STATE_KEY);
      return getDefaultPublicState();
    }

    writeState(next);
    return getState();
  }

  function readReturnPath() {
    var state = safeGet(window.sessionStorage, RETURN_KEY);
    if (!state || typeof state !== 'object') {
      return null;
    }
    if (typeof state.e !== 'number' || now() > state.e) {
      safeRemove(window.sessionStorage, RETURN_KEY);
      return null;
    }
    if (!isPath(state.p)) {
      safeRemove(window.sessionStorage, RETURN_KEY);
      return null;
    }
    return state.p;
  }

  function setReturnPath(path) {
    if (!isPath(path)) return false;
    return safeSet(window.sessionStorage, RETURN_KEY, {
      p: path,
      e: now() + RETURN_TTL_MS,
    }, MAX_RETURN_BYTES);
  }

  function consumeReturnPath() {
    var path = readReturnPath();
    safeRemove(window.sessionStorage, RETURN_KEY);
    return path;
  }

  function cleanup() {
    readState();
    readReturnPath();
  }

  var api = {
    getState: getState,
    patchState: patchState,
    setReturnPath: setReturnPath,
    consumeReturnPath: consumeReturnPath,
    cleanup: cleanup,

    markLoggedIn: function () {
      return patchState({
        hasLoggedIn: true,
        allowCredentialStorage: true,
        landingPath: '/home',
      });
    },

    markLoggedOut: function () {
      safeRemove(window.localStorage, STATE_KEY);
      safeRemove(window.sessionStorage, RETURN_KEY);
      return getDefaultPublicState();
    },

    isLoggedInHint: function () {
      return getState().hasLoggedIn;
    },

    getLandingPath: function () {
      return getState().landingPath;
    },

    setLandingPath: function (path) {
      return patchState({ landingPath: path });
    },

    getThemePlaceholder: function () {
      return '';
    },
  };

  cleanup();
  window.browserCache = api;
  window.ZKBrowserCache = api;
})();
