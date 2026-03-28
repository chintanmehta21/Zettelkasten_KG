/* ═══════════════════════════════════════════════════════════
   Mobile 3D Knowledge Graph — ForceGraph3D (same as desktop)
   Optimized for mobile: bottom sheet, smaller nodes, lower
   poly geometry, capped pixel ratio, touch-optimized
   ═══════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  // ── Colors ──────────────────────────────────────────────
  var COLORS = {
    youtube:  '#E05565',
    reddit:   '#E09040',
    github:   '#56C8D8',
    substack: '#60A5FA',
    medium:   '#4ADE80'
  };
  var COLORS_INT = {
    youtube:  0xE05565,
    reddit:   0xE09040,
    github:   0x56C8D8,
    substack: 0x60A5FA,
    medium:   0x4ADE80
  };

  // ── DOM refs ────────────────────────────────────────────
  var container    = document.getElementById('graph-container');
  var searchInput  = document.getElementById('search-input');
  var filterToggle = document.getElementById('filter-toggle');
  var chips        = document.getElementById('filter-chips');
  var statsEl      = document.getElementById('stats');
  var sheet        = document.getElementById('sheet');

  // ── URL params ──────────────────────────────────────────
  var urlParams   = new URLSearchParams(window.location.search);
  var spotlightId = urlParams.get('node');

  // ── State ───────────────────────────────────────────────
  var graphData = { nodes: [], links: [] };
  var fullData  = { nodes: [], links: [] };
  var graph     = null;
  var selectedNode = null;
  var hoverNode    = null;
  var highlightNodes = new Set();
  var activeFilters  = new Set(['youtube', 'reddit', 'github', 'substack', 'medium']);
  var nodeDegrees = {};

  // ── Smart label shortening (same as desktop) ────────────
  var SEP = ' \u2014 ';
  var LEAD_FILLER = new Set(['the', 'a', 'an', 'my', 'why', 'how', 'what']);
  var TAIL_FILLER = new Set([
    'of', 'at', 'is', 'for', 'in', 'the', 'a', 'an', 'that', 'with',
    'and', 'or', 'to', 'by', 'on', 'as', 'after', 'before', 'from'
  ]);

  function getShortLabel(node) {
    var name = node.name;
    var sepIdx = name.indexOf(SEP);
    if (node.group === 'github') {
      return sepIdx > -1 ? name.slice(0, sepIdx) : name.split(' ').slice(0, 2).join(' ');
    }
    if ((node.group === 'reddit' || node.group === 'substack' || node.group === 'medium') && sepIdx > -1) {
      return _truncate(name.slice(sepIdx + SEP.length), 2);
    }
    return _truncate(sepIdx > -1 ? name.slice(0, sepIdx) : name, 2);
  }

  function _truncate(str, maxWords) {
    var words = str.trim().split(/\s+/);
    if (words.length <= maxWords) return str.trim();
    while (words.length > 1 && LEAD_FILLER.has(words[0].toLowerCase())) words.shift();
    var label = words.slice(0, maxWords);
    while (label.length > 1 && TAIL_FILLER.has(label[label.length - 1].toLowerCase())) label.pop();
    if (label.length === 1 && words.length > 1) {
      for (var i = 1; i < Math.min(words.length, 4); i++) {
        if (!TAIL_FILLER.has(words[i].toLowerCase())) { label.push(words[i]); break; }
      }
    }
    return label.join(' ');
  }

  function escapeHtml(str) {
    var el = document.createElement('span');
    el.textContent = str;
    return el.innerHTML;
  }

  // ── Degree computation ──────────────────────────────────
  function computeDegrees(data) {
    var deg = {};
    data.nodes.forEach(function (n) { deg[n.id] = 0; });
    data.links.forEach(function (l) {
      var s = typeof l.source === 'object' ? l.source.id : l.source;
      var t = typeof l.target === 'object' ? l.target.id : l.target;
      deg[s] = (deg[s] || 0) + 1;
      deg[t] = (deg[t] || 0) + 1;
    });
    return deg;
  }

  // ── Shared geometry — low-poly for mobile (24 segments vs 48 on desktop) ──
  var _sphereGeo = new THREE.SphereGeometry(1, 24, 24);
  var _matCache = {};

  // Ring sprite texture
  (function () {
    var s = 128, c = document.createElement('canvas');  // 128px vs 256px on desktop
    c.width = s; c.height = s;
    var ctx = c.getContext('2d'), h = s / 2;
    ctx.clearRect(0, 0, s, s);
    ctx.beginPath();
    ctx.arc(h, h, h * 0.94, 0, Math.PI * 2);
    ctx.arc(h, h, h * 0.76, 0, Math.PI * 2, true);
    ctx.closePath();
    ctx.fillStyle = '#ffffff';
    ctx.fill();
    _matCache['_ringTex'] = new THREE.CanvasTexture(c);
  })();

  function getSphereMat(hexColor, dim) {
    var key = hexColor + (dim ? '_d' : '');
    if (!_matCache[key]) {
      _matCache[key] = new THREE.MeshBasicMaterial({
        color: hexColor,
        transparent: dim,
        opacity: dim ? 0.12 : 1.0,
        depthWrite: !dim
      });
    }
    return _matCache[key];
  }

  // ── Load data and init ──────────────────────────────────
  fetch('/api/graph')
    .then(function (r) { return r.ok ? r.json() : Promise.reject('api'); })
    .catch(function () { return fetch('/kg/content/graph.json').then(function (r) { return r.json(); }); })
    .then(function (data) {
      fullData = data;
      graphData = JSON.parse(JSON.stringify(data));
      nodeDegrees = computeDegrees(fullData);
      initGraph();
      updateStats();
    })
    .catch(function () {
      statsEl.textContent = 'Failed to load data';
    });

  // ── 3D Graph ────────────────────────────────────────────
  function initGraph() {
    graph = new ForceGraph3D(container)
      .graphData(graphData)
      .backgroundColor('#06060f')
      .showNavInfo(false)
      .width(window.innerWidth)
      .height(window.innerHeight)

      // ── Node rendering (same approach as desktop, slightly smaller) ──
      .nodeThreeObject(function (node) {
        var group = new THREE.Group();
        var color = COLORS_INT[node.group] || 0x888888;

        var isSelected = selectedNode && selectedNode.id === node.id;
        var isHovered = hoverNode && hoverNode.id === node.id;
        var isHighlighted = highlightNodes.size === 0 || highlightNodes.has(node.id);
        var isActive = isSelected || isHovered;
        var dim = !isHighlighted;

        // Smaller base radius for mobile (1.5 vs 2 on desktop)
        var deg = nodeDegrees[node.id] || 1;
        var isSpotlight = spotlightId && spotlightId === node.id;
        var baseRadius = Math.min(1.5 + deg * 0.25, 4);
        var radius = isActive ? baseRadius + 0.8 : (isSpotlight ? baseRadius + 0.4 : baseRadius);
        var mesh = new THREE.Mesh(_sphereGeo, getSphereMat(color, dim));
        mesh.scale.setScalar(radius);
        group.add(mesh);

        // Spotlight ring
        if (isSpotlight) {
          var ringKey = 'ringSpr_' + color;
          if (!_matCache[ringKey]) {
            _matCache[ringKey] = new THREE.SpriteMaterial({
              map: _matCache['_ringTex'],
              color: new THREE.Color(color).multiplyScalar(0.65),
              transparent: true,
              opacity: 0.8,
              depthWrite: false
            });
          }
          var ring = new THREE.Sprite(_matCache[ringKey]);
          ring.scale.set(radius * 3, radius * 3, 1);
          group.add(ring);
        }

        // Text label — smaller for mobile
        var label = isActive ? node.name : getShortLabel(node);
        if (label.length > 22) label = label.substring(0, 20) + '...';
        var sprite = new SpriteText(label);
        sprite.fontFace = 'Inter, -apple-system, sans-serif';
        sprite.fontWeight = '500';
        sprite.fontSize = 80;   // smaller than desktop (90)
        sprite.textHeight = 1.5; // smaller than desktop (1.8)
        sprite.__isLabel = true;

        if (isActive) {
          sprite.color = '#ffffff';
          sprite.backgroundColor = 'rgba(8, 12, 24, 0.92)';
          sprite.padding = 0.8;
          sprite.borderWidth = 0.1;
          sprite.borderColor = 'rgba(255, 255, 255, 0.14)';
          sprite.borderRadius = 0.6;
        } else {
          sprite.color = isHighlighted ? 'rgba(210, 216, 228, 0.7)' : 'rgba(200, 208, 220, 0.06)';
          sprite.backgroundColor = false;
          sprite.padding = 0;
        }
        sprite.position.set(0, -(radius + 2.5), 0);
        group.add(sprite);

        return group;
      })
      .nodeThreeObjectExtend(false)

      // ── Links ──
      .linkColor(function (link) {
        var src = typeof link.source === 'object' ? link.source : null;
        if (src && hoverNode && (src.id === hoverNode.id || (typeof link.target === 'object' && link.target.id === hoverNode.id))) {
          return COLORS[src.group] || 'rgba(160, 180, 240, 0.8)';
        }
        return 'rgba(100, 130, 200, 0.25)';
      })
      .linkWidth(function (link) {
        var src = typeof link.source === 'object' ? link.source : null;
        var tgt = typeof link.target === 'object' ? link.target : null;
        if (hoverNode && ((src && src.id === hoverNode.id) || (tgt && tgt.id === hoverNode.id))) {
          return 1.5;
        }
        return 0.4;
      })
      .linkOpacity(0.6)
      .linkCurvature(0.15)
      .linkCurveRotation(0.4)
      // Fewer particles for mobile performance
      .linkDirectionalParticles(1)
      .linkDirectionalParticleWidth(0.8)
      .linkDirectionalParticleSpeed(0.008)
      .linkDirectionalParticleColor(function (link) {
        var src = typeof link.source === 'object' ? link.source : null;
        return src ? (COLORS[src.group] || '#4466aa') : '#4466aa';
      })

      // ── Interactions ──
      .nodeLabel(function () { return ''; })
      .onNodeClick(handleNodeClick)
      .onBackgroundClick(handleBackgroundClick)
      .onNodeHover(function (node) {
        hoverNode = node || null;
        container.style.cursor = node ? 'pointer' : 'default';
        // Only refresh node rendering, not the whole graph
        graph.nodeThreeObject(graph.nodeThreeObject());
      })

      // ── Physics — faster cooldown for mobile ──
      .d3AlphaDecay(0.03)
      .d3VelocityDecay(0.4)
      .warmupTicks(80)
      .cooldownTime(2000);

    // ── Renderer — cap pixel ratio for mobile perf ──
    graph.renderer().setPixelRatio(Math.min(window.devicePixelRatio, 2));

    // ── Scene ──
    graph.scene().add(new THREE.AmbientLight(0xffffff, 1));

    // ── Forces — tighter for smaller screens ──
    graph.d3Force('charge').strength(-120).distanceMax(300);
    graph.d3Force('link').distance(60);

    var d3 = window.d3 || null;
    if (d3 && d3.forceCenter) {
      graph.d3Force('center', d3.forceCenter(0, 0, 0).strength(0.05));
    }

    // ── Camera controls ──
    var controls = graph.controls();
    controls.autoRotate = true;
    controls.autoRotateSpeed = 0.3;
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.minDistance = 60;
    controls.maxDistance = 400;

    var stopOrbit = function () { controls.autoRotate = false; };
    container.addEventListener('touchstart', stopOrbit, { passive: true });
    container.addEventListener('mousedown', stopOrbit);

    // ── Initial zoom ──
    if (spotlightId) {
      setTimeout(function () {
        var sNode = graphData.nodes.find(function (n) { return n.id === spotlightId; });
        if (sNode) handleNodeClick(sNode);
        else graph.zoomToFit(1000, 40);
      }, 1800);
    } else {
      setTimeout(function () { graph.zoomToFit(1000, 40); }, 1500);
    }

    // ── Resize ──
    window.addEventListener('resize', function () {
      graph.width(window.innerWidth).height(window.innerHeight);
    });

    // ── Label scale clamping ──
    var _v3 = new THREE.Vector3();
    var MAX_LABEL_FRAC = 0.025;

    function clampLabelScales() {
      requestAnimationFrame(clampLabelScales);
      var cam = graph.camera();
      if (!cam) return;
      graphData.nodes.forEach(function (node) {
        var obj = node.__threeObj;
        if (!obj || !obj.children) return;
        for (var i = 0; i < obj.children.length; i++) {
          var child = obj.children[i];
          if (!child.__isLabel) continue;
          if (child.__origSy === undefined) {
            child.__origSy = child.scale.y;
            child.__origSx = child.scale.x;
          }
          obj.getWorldPosition(_v3);
          var dist = cam.position.distanceTo(_v3);
          var maxH = dist * MAX_LABEL_FRAC;
          if (child.__origSy > maxH && maxH > 0) {
            var r = maxH / child.__origSy;
            child.scale.set(child.__origSx * r, child.__origSy * r, 1);
          } else {
            child.scale.set(child.__origSx, child.__origSy, 1);
          }
        }
      });
    }
    requestAnimationFrame(clampLabelScales);
  }

  // ── Node click → fly camera + open bottom sheet ─────────
  var _sheetTimer = null;

  function handleNodeClick(node) {
    selectedNode = node;
    graph.controls().autoRotate = false;
    graph.nodeThreeObject(graph.nodeThreeObject());

    if (_sheetTimer) { clearTimeout(_sheetTimer); _sheetTimer = null; }

    var cam = graph.camera();
    var nx = node.x || 0, ny = node.y || 0, nz = node.z || 0;
    var dx = cam.position.x - nx;
    var dy = cam.position.y - ny;
    var dz = cam.position.z - nz;
    var len = Math.sqrt(dx * dx + dy * dy + dz * dz) || 1;
    var targetDist = 70; // closer than desktop (90)

    graph.cameraPosition({
      x: nx + (dx / len) * targetDist,
      y: ny + (dy / len) * targetDist,
      z: nz + (dz / len) * targetDist
    }, node, 800);

    _sheetTimer = setTimeout(function () {
      openSheet(node);
      _sheetTimer = null;
    }, 600);
  }

  function handleBackgroundClick() {
    if (_sheetTimer) { clearTimeout(_sheetTimer); _sheetTimer = null; }
    closeSheet();
    selectedNode = null;
    highlightNodes.clear();
    graph.nodeThreeObject(graph.nodeThreeObject());
  }

  // ── Bottom Sheet ────────────────────────────────────────
  function openSheet(node) {
    var badge = document.getElementById('sheet-badge');
    badge.textContent = node.group || 'generic';
    badge.style.background = COLORS[node.group] || '#888';
    badge.style.color = (node.group === 'github' || node.group === 'substack' || node.group === 'medium') ? '#000' : '#fff';

    document.getElementById('sheet-title').textContent = node.name;
    document.getElementById('sheet-date').textContent = formatDate(node.date);
    document.getElementById('sheet-summary').textContent = node.summary || 'No summary available.';

    // Tags
    var tagsEl = document.getElementById('sheet-tags');
    tagsEl.innerHTML = '';
    if (node.tags && node.tags.length) {
      node.tags.forEach(function (t) {
        var tag = document.createElement('span');
        tag.className = 'm-tag';
        tag.textContent = t;
        tagsEl.appendChild(tag);
      });
    }

    // Connections
    var connList = document.getElementById('sheet-conn-list');
    var connSection = document.getElementById('sheet-connections');
    connList.innerHTML = '';
    var connections = graphData.links.filter(function (l) {
      var s = typeof l.source === 'object' ? l.source.id : l.source;
      var t = typeof l.target === 'object' ? l.target.id : l.target;
      return s === node.id || t === node.id;
    });

    if (connections.length === 0) {
      connSection.classList.add('hidden');
    } else {
      connSection.classList.remove('hidden');
      connections.forEach(function (l) {
        var s = typeof l.source === 'object' ? l.source.id : l.source;
        var t = typeof l.target === 'object' ? l.target.id : l.target;
        var otherId = s === node.id ? t : s;
        var other = graphData.nodes.find(function (n) { return n.id === otherId; });
        if (!other) return;
        var el = document.createElement('div');
        el.className = 'kg-m-connection';
        el.textContent = other.name || other.id;
        el.addEventListener('click', function () { handleNodeClick(other); });
        connList.appendChild(el);
      });
    }

    // Source link
    document.getElementById('sheet-link').href = node.url || '#';

    // Show
    sheet.classList.add('open');
    chips.classList.add('hidden');
  }

  function closeSheet() {
    sheet.classList.remove('open');
    selectedNode = null;
    chips.classList.remove('hidden');
  }

  function formatDate(dateStr) {
    if (!dateStr) return '';
    var d = new Date(dateStr);
    return d.toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' });
  }

  // ── Swipe down to close sheet ───────────────────────────
  var sheetTouchY = 0;
  sheet.addEventListener('touchstart', function (e) {
    sheetTouchY = e.touches[0].clientY;
  }, { passive: true });
  sheet.addEventListener('touchend', function (e) {
    if (e.changedTouches[0].clientY - sheetTouchY > 60) closeSheet();
  }, { passive: true });

  // ── Search ──────────────────────────────────────────────
  searchInput.addEventListener('input', function () {
    var query = searchInput.value.toLowerCase().trim();
    highlightNodes.clear();
    selectedNode = null;

    if (query.length > 0) {
      graphData.nodes.forEach(function (node) {
        var match = node.name.toLowerCase().indexOf(query) > -1 ||
                    (node.tags || []).some(function (t) { return t.toLowerCase().indexOf(query) > -1; }) ||
                    (node.summary || '').toLowerCase().indexOf(query) > -1;
        if (match) highlightNodes.add(node.id);
      });
    }

    graph.nodeThreeObject(graph.nodeThreeObject());
  });

  // ── Filters ─────────────────────────────────────────────
  filterToggle.addEventListener('click', function () {
    chips.classList.toggle('hidden');
  });

  chips.addEventListener('click', function (e) {
    var chip = e.target.closest('.kg-m-chip');
    if (!chip) return;
    var src = chip.dataset.source;
    chip.classList.toggle('active');
    if (chip.classList.contains('active')) {
      activeFilters.add(src);
    } else {
      activeFilters.delete(src);
    }
    applyFilters();
  });

  function applyFilters() {
    var filteredNodes = fullData.nodes.filter(function (n) { return activeFilters.has(n.group); });
    var nodeIds = new Set(filteredNodes.map(function (n) { return n.id; }));
    var filteredLinks = fullData.links.filter(function (l) {
      var src = typeof l.source === 'object' ? l.source.id : l.source;
      var tgt = typeof l.target === 'object' ? l.target.id : l.target;
      return nodeIds.has(src) && nodeIds.has(tgt);
    });

    graphData = { nodes: filteredNodes, links: filteredLinks };
    nodeDegrees = computeDegrees(graphData);
    graph.graphData(graphData);
    updateStats();

    closeSheet();
    selectedNode = null;
    highlightNodes.clear();

    setTimeout(function () { graph.zoomToFit(600, 40); }, 600);
  }

  // ── Stats ───────────────────────────────────────────────
  function updateStats() {
    statsEl.textContent = graphData.nodes.length + ' notes \u00B7 ' + graphData.links.length + ' connections';
  }
})();
