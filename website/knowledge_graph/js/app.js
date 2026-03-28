/* ============================================
   Knowledge Graph — Lightweight 3D Viewer
   ============================================
   Performance targets:
   - < 2s full load (graph visible + interactive)
   - Single shared SphereGeometry for all nodes
   - MeshBasicMaterial (no lighting = flat circle at every angle)
   - Cached materials to avoid GC churn
   - Minimal draw calls: 1 mesh + 1 sprite per node
   ============================================ */

(function () {
  'use strict';

  // ---- Node colors by source (kept as-is) ----
  const COLORS = {
    youtube:  '#c75050',
    reddit:   '#d48a3c',
    github:   '#9c7bbd',
    substack: '#5a93c6',
    medium:   '#5daf6a'
  };

  const COLORS_INT = {
    youtube:  0xc75050,
    reddit:   0xd48a3c,
    github:   0x9c7bbd,
    substack: 0x5a93c6,
    medium:   0x5daf6a
  };

  function escapeHtml(str) {
    const el = document.createElement('span');
    el.textContent = str;
    return el.innerHTML;
  }

  // ---- DOM refs ----
  const container = document.getElementById('graph-container');
  const searchInput = document.getElementById('search-input');
  const filterBtn = document.getElementById('filter-btn');
  const filterDropdown = document.getElementById('filter-dropdown');
  const sidePanel = document.getElementById('side-panel');
  const panelClose = document.getElementById('panel-close');
  const statsEl = document.getElementById('graph-stats');

  // ---- State ----
  let graphData = { nodes: [], links: [] };
  let fullData = { nodes: [], links: [] };
  let graph = null;
  let selectedNode = null;
  let panelHideTimer = null;
  let highlightNodes = new Set();
  let hoverNode = null;
  let activeFilters = new Set(['youtube', 'reddit', 'github', 'substack', 'medium']);

  // ---- Shared geometry — ONE allocation for every node ----
  const _sphereGeo = new THREE.SphereGeometry(1, 24, 24);
  const _matCache = {};

  function getSphereMat(hexColor, dim) {
    const key = hexColor + (dim ? '_d' : '');
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

  // ---- Load data and init ----
  fetch('/kg/content/graph.json')
    .then(r => r.json())
    .then(data => {
      fullData = data;
      graphData = JSON.parse(JSON.stringify(data));
      initGraph();
      updateStats();
    })
    .catch(err => {
      console.error('Failed to load graph data:', err);
      statsEl.textContent = 'Failed to load data';
    });

  // ---- 3D Graph ----
  function initGraph() {
    graph = new ForceGraph3D(container)
      .graphData(graphData)
      .backgroundColor('#06060f')
      .showNavInfo(false)

      // ---- Node: clean flat sphere + text label (2 objects per node) ----
      .nodeThreeObject(node => {
        const group = new THREE.Group();
        const color = COLORS_INT[node.group] || 0x888888;

        const isSelected = selectedNode && selectedNode.id === node.id;
        const isHovered = hoverNode && hoverNode.id === node.id;
        const isHighlighted = highlightNodes.size === 0 || highlightNodes.has(node.id);
        const isActive = isSelected || isHovered;
        const dim = !isHighlighted;

        // Single sphere — MeshBasicMaterial = perfect solid circle at any zoom/angle
        const radius = isActive ? 5.5 : 4;
        const mesh = new THREE.Mesh(_sphereGeo, getSphereMat(color, dim));
        mesh.scale.setScalar(radius);
        group.add(mesh);

        // Text label — no background, minimal
        const maxLen = 30;
        const label = node.name.length > maxLen ? node.name.slice(0, maxLen - 1) + '\u2026' : node.name;
        const sprite = new SpriteText(label);
        sprite.color = isHighlighted
          ? (isActive ? '#ffffff' : 'rgba(200, 208, 220, 0.8)')
          : 'rgba(200, 208, 220, 0.08)';
        sprite.textHeight = isActive ? 3.2 : 2.5;
        sprite.backgroundColor = false;
        sprite.padding = 0;
        sprite.position.set(0, -(radius + 5), 0);
        group.add(sprite);

        return group;
      })
      .nodeThreeObjectExtend(false)

      // ---- Link rendering (colors kept as-is) ----
      .linkColor(link => {
        const src = typeof link.source === 'object' ? link.source : null;
        if (src && hoverNode && (src.id === hoverNode.id || (typeof link.target === 'object' && link.target.id === hoverNode.id))) {
          return COLORS[src.group] || 'rgba(160, 180, 240, 0.8)';
        }
        return 'rgba(100, 130, 200, 0.25)';
      })
      .linkWidth(link => {
        const src = typeof link.source === 'object' ? link.source : null;
        const tgt = typeof link.target === 'object' ? link.target : null;
        if (hoverNode && ((src && src.id === hoverNode.id) || (tgt && tgt.id === hoverNode.id))) {
          return 1.8;
        }
        return 0.5;
      })
      .linkOpacity(0.6)
      .linkCurvature(0.15)
      .linkCurveRotation(0.4)
      // Particles — 1 per link, fast travel speed
      .linkDirectionalParticles(1)
      .linkDirectionalParticleWidth(1.0)
      .linkDirectionalParticleSpeed(0.008)
      .linkDirectionalParticleColor(link => {
        const src = typeof link.source === 'object' ? link.source : null;
        return src ? (COLORS[src.group] || '#4466aa') : '#4466aa';
      })

      // ---- Interactions ----
      .onNodeClick(handleNodeClick)
      .onBackgroundClick(handleBackgroundClick)
      .onNodeHover(node => {
        hoverNode = node || null;
        container.style.cursor = node ? 'pointer' : 'default';
        graph.nodeThreeObject(graph.nodeThreeObject());
      })

      // ---- Physics — fast convergence ----
      .d3AlphaDecay(0.025)
      .d3VelocityDecay(0.35)
      .warmupTicks(100)
      .cooldownTime(2500);

    // ---- Minimal scene — no fog, no starfield, no point lights ----
    // MeshBasicMaterial ignores lights, so we only need ambient for any
    // future objects that might use lit materials
    graph.scene().add(new THREE.AmbientLight(0xffffff, 1));

    // Force layout — wide spread for clear visibility
    graph.d3Force('charge').strength(-100).distanceMax(300);
    graph.d3Force('link').distance(60);

    const d3 = window.d3 || null;
    if (d3 && d3.forceCenter) {
      graph.d3Force('center', d3.forceCenter(0, 0, 0).strength(0.05));
    }

    // ---- Camera ----
    const controls = graph.controls();
    controls.autoRotate = true;
    controls.autoRotateSpeed = 0.3;
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.minDistance = 60;
    controls.maxDistance = 500;

    const stopOrbit = () => { controls.autoRotate = false; };
    container.addEventListener('mousedown', stopOrbit);
    container.addEventListener('touchstart', stopOrbit);

    // Zoom to fit — fast
    setTimeout(() => graph.zoomToFit(1200, 50), 1800);

    window.addEventListener('resize', () => {
      graph.width(window.innerWidth).height(window.innerHeight);
    });
  }

  // ---- Node click → fly to node + open panel ----
  function handleNodeClick(node) {
    selectedNode = node;
    openPanel(node);

    const dist = 80;
    const ratio = 1 + dist / Math.hypot(node.x, node.y, node.z || 1);
    graph.cameraPosition(
      { x: node.x * ratio, y: node.y * ratio, z: (node.z || 0) * ratio },
      node,
      1000
    );

    graph.controls().autoRotate = false;
    graph.nodeThreeObject(graph.nodeThreeObject());
  }

  function handleBackgroundClick() {
    closePanel();
    selectedNode = null;
    highlightNodes.clear();
    graph.nodeThreeObject(graph.nodeThreeObject());
  }

  // ---- Side Panel ----
  function openPanel(node) {
    const badge = document.getElementById('panel-badge');
    const title = document.getElementById('panel-title');
    const date = document.getElementById('panel-date');
    const summary = document.getElementById('panel-summary');
    const tags = document.getElementById('panel-tags');
    const connections = document.getElementById('panel-connections');
    const link = document.getElementById('panel-link');

    badge.textContent = node.group;
    badge.className = 'kg-panel-badge ' + node.group;
    title.textContent = node.name;
    date.textContent = formatDate(node.date);
    summary.textContent = node.summary;
    link.href = node.url;

    tags.innerHTML = node.tags.map(
      t => `<span class="kg-tag">${escapeHtml(t)}</span>`
    ).join('');

    const nodeLinks = graphData.links.filter(
      l => l.source === node || l.target === node ||
           l.source?.id === node.id || l.target?.id === node.id
    );
    const connectedNodes = nodeLinks.map(l => {
      const other = (l.source === node || l.source?.id === node.id) ? l.target : l.source;
      return { node: other, relation: l.relation };
    });

    connections.innerHTML = connectedNodes.map(c => `
      <div class="kg-connection" data-id="${escapeHtml(c.node.id || c.node)}">
        <span class="kg-connection-dot" style="background: ${COLORS[c.node.group] || '#888'}"></span>
        <span class="kg-connection-name">${escapeHtml(c.node.name || c.node)}</span>
        <span class="kg-connection-relation">${escapeHtml(c.relation)}</span>
      </div>
    `).join('');

    connections.querySelectorAll('.kg-connection').forEach(el => {
      el.addEventListener('click', () => {
        const targetId = el.dataset.id;
        const targetNode = graphData.nodes.find(n => n.id === targetId);
        if (targetNode) handleNodeClick(targetNode);
      });
    });

    if (panelHideTimer) { clearTimeout(panelHideTimer); panelHideTimer = null; }
    sidePanel.classList.remove('hidden');
    requestAnimationFrame(() => sidePanel.classList.add('visible'));
  }

  function closePanel() {
    sidePanel.classList.remove('visible');
    if (panelHideTimer) clearTimeout(panelHideTimer);
    panelHideTimer = setTimeout(() => { sidePanel.classList.add('hidden'); panelHideTimer = null; }, 350);
  }

  function formatDate(dateStr) {
    const d = new Date(dateStr);
    return d.toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' });
  }

  // ---- Search ----
  searchInput.addEventListener('input', (e) => {
    const query = e.target.value.toLowerCase().trim();
    highlightNodes.clear();
    selectedNode = null;

    if (query.length > 0) {
      graphData.nodes.forEach(node => {
        const match = node.name.toLowerCase().includes(query) ||
                      node.tags.some(t => t.toLowerCase().includes(query)) ||
                      node.summary.toLowerCase().includes(query);
        if (match) highlightNodes.add(node.id);
      });
    }

    graph.nodeThreeObject(graph.nodeThreeObject());
  });

  // ---- Filter ----
  filterBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    filterDropdown.classList.toggle('hidden');
    filterBtn.classList.toggle('active');
  });

  document.addEventListener('click', (e) => {
    if (!filterDropdown.contains(e.target) && e.target !== filterBtn) {
      filterDropdown.classList.add('hidden');
      filterBtn.classList.remove('active');
    }
  });

  filterDropdown.querySelectorAll('input[type="checkbox"]').forEach(cb => {
    cb.addEventListener('change', () => {
      activeFilters.clear();
      filterDropdown.querySelectorAll('input:checked').forEach(
        checked => activeFilters.add(checked.value)
      );
      applyFilters();
    });
  });

  function applyFilters() {
    const filteredNodes = fullData.nodes.filter(n => activeFilters.has(n.group));
    const nodeIds = new Set(filteredNodes.map(n => n.id));
    const filteredLinks = fullData.links.filter(l => {
      const src = typeof l.source === 'object' ? l.source.id : l.source;
      const tgt = typeof l.target === 'object' ? l.target.id : l.target;
      return nodeIds.has(src) && nodeIds.has(tgt);
    });

    graphData = { nodes: filteredNodes, links: filteredLinks };
    graph.graphData(graphData);
    updateStats();

    closePanel();
    selectedNode = null;
    highlightNodes.clear();

    setTimeout(() => graph.zoomToFit(800, 60), 800);
  }

  // ---- Stats ----
  function updateStats() {
    const n = graphData.nodes.length;
    const l = graphData.links.length;
    statsEl.textContent = `${n} notes \u00B7 ${l} connections`;
  }

  // ---- Close panel button ----
  panelClose.addEventListener('click', () => {
    closePanel();
    selectedNode = null;
    highlightNodes.clear();
    graph.nodeThreeObject(graph.nodeThreeObject());
  });

  // ---- Keyboard: Escape ----
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      closePanel();
      selectedNode = null;
      highlightNodes.clear();
      hoverNode = null;
      searchInput.value = '';
      graph.nodeThreeObject(graph.nodeThreeObject());
    }
  });

})();
