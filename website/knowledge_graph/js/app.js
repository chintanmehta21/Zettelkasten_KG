/* ============================================
   Knowledge Graph — 3D Interactive Viewer
   ============================================ */

(function () {
  'use strict';

  // ---- Node colors by source (hex for Three.js) ----
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

  // ---- Starfield background ----
  function createStarfield(scene) {
    const starCount = 800;
    const geo = new THREE.BufferGeometry();
    const positions = new Float32Array(starCount * 3);
    const sizes = new Float32Array(starCount);

    for (let i = 0; i < starCount; i++) {
      positions[i * 3]     = (Math.random() - 0.5) * 2000;
      positions[i * 3 + 1] = (Math.random() - 0.5) * 2000;
      positions[i * 3 + 2] = (Math.random() - 0.5) * 2000;
      sizes[i] = Math.random() * 1.5 + 0.3;
    }

    geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geo.setAttribute('size', new THREE.BufferAttribute(sizes, 1));

    const mat = new THREE.PointsMaterial({
      color: 0x445577,
      size: 1.2,
      transparent: true,
      opacity: 0.4,
      sizeAttenuation: true
    });

    scene.add(new THREE.Points(geo, mat));
  }

  // ---- 3D Graph Initialization ----
  function initGraph() {
    graph = new ForceGraph3D(container)
      .graphData(graphData)
      .backgroundColor('#06060f')
      .showNavInfo(false)

      // ---- Node rendering: glowing 3D spheres + sprite labels ----
      .nodeThreeObject(node => {
        const group = new THREE.Group();
        const color = COLORS_INT[node.group] || 0x888888;

        const isSelected = selectedNode && selectedNode.id === node.id;
        const isHovered = hoverNode && hoverNode.id === node.id;
        const isHighlighted = highlightNodes.size === 0 || highlightNodes.has(node.id);
        const isActive = isSelected || isHovered;
        const opacity = isHighlighted ? 1.0 : 0.08;

        // Core sphere — larger for better visibility
        const radius = isActive ? 8 : 6;
        const coreGeo = new THREE.SphereGeometry(radius, 32, 32);
        const coreMat = new THREE.MeshStandardMaterial({
          color: color,
          emissive: color,
          emissiveIntensity: isActive ? 0.8 : 0.45,
          roughness: 0.25,
          metalness: 0.15,
          transparent: true,
          opacity: opacity
        });
        const core = new THREE.Mesh(coreGeo, coreMat);
        group.add(core);

        // Inner glow ring
        const innerGlowGeo = new THREE.SphereGeometry(radius * 1.3, 16, 16);
        const innerGlowMat = new THREE.MeshBasicMaterial({
          color: color,
          transparent: true,
          opacity: (isActive ? 0.2 : 0.08) * opacity
        });
        group.add(new THREE.Mesh(innerGlowGeo, innerGlowMat));

        // Outer glow halo — larger and softer
        const glowGeo = new THREE.SphereGeometry(radius * 2.0, 16, 16);
        const glowMat = new THREE.MeshBasicMaterial({
          color: color,
          transparent: true,
          opacity: (isActive ? 0.12 : 0.04) * opacity
        });
        group.add(new THREE.Mesh(glowGeo, glowMat));

        // Sprite text label — always readable
        const maxLen = 36;
        const label = node.name.length > maxLen ? node.name.slice(0, maxLen - 1) + '\u2026' : node.name;
        const sprite = new SpriteText(label);
        sprite.color = isHighlighted
          ? (isActive ? '#ffffff' : 'rgba(232, 234, 237, 0.9)')
          : 'rgba(232, 234, 237, 0.08)';
        sprite.textHeight = isActive ? 4.0 : 3.2;
        sprite.backgroundColor = isActive
          ? 'rgba(6, 6, 15, 0.85)'
          : 'rgba(6, 6, 15, 0.5)';
        sprite.padding = [1.0, 2.0];
        sprite.borderRadius = 4;
        sprite.position.set(0, -(radius + 8), 0);
        group.add(sprite);

        return group;
      })
      .nodeThreeObjectExtend(false)

      // ---- Link rendering ----
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
          return 2.0;
        }
        return 0.6;
      })
      .linkOpacity(0.6)
      .linkCurvature(0.15)
      .linkCurveRotation(0.4)
      .linkDirectionalParticles(2)
      .linkDirectionalParticleWidth(1.5)
      .linkDirectionalParticleSpeed(0.003)
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
        // Re-render to update link highlights
        graph.nodeThreeObject(graph.nodeThreeObject());
      })

      // ---- Physics — wider spread so all nodes are clearly visible ----
      .d3AlphaDecay(0.015)
      .d3VelocityDecay(0.3)
      .warmupTicks(300)
      .cooldownTime(5000);

    // ---- Scene enhancements ----
    const scene = graph.scene();

    // Starfield background
    createStarfield(scene);

    // Ambient light — warm cool blend
    scene.add(new THREE.AmbientLight(0x1a1a3e, 2.5));

    // Key light (bright, cool white from above-right)
    const keyLight = new THREE.PointLight(0x7799dd, 2.0, 800);
    keyLight.position.set(80, 250, 150);
    scene.add(keyLight);

    // Fill light (warm accent from below-left)
    const fillLight = new THREE.PointLight(0xcc8866, 0.8, 500);
    fillLight.position.set(-120, -120, -80);
    scene.add(fillLight);

    // Rim light (subtle accent from behind)
    const rimLight = new THREE.PointLight(0x4466aa, 0.5, 600);
    rimLight.position.set(0, 0, -200);
    scene.add(rimLight);

    // Very subtle fog — just enough for depth, never hides nodes
    scene.fog = new THREE.FogExp2(0x06060f, 0.0004);

    // Force layout: much wider spread for clear visibility
    graph.d3Force('charge').strength(-120).distanceMax(350);
    graph.d3Force('link').distance(70);

    // Center force — keep graph centered
    graph.d3Force('center', null); // re-add with gentle pull
    const d3 = window.d3 || null;
    if (d3 && d3.forceCenter) {
      graph.d3Force('center', d3.forceCenter(0, 0, 0).strength(0.05));
    }

    // ---- Camera: auto-orbit ----
    const controls = graph.controls();
    controls.autoRotate = true;
    controls.autoRotateSpeed = 0.3;
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.minDistance = 80;
    controls.maxDistance = 600;

    // Stop auto-rotation on user interaction
    const stopOrbit = () => { controls.autoRotate = false; };
    container.addEventListener('mousedown', stopOrbit);
    container.addEventListener('touchstart', stopOrbit);

    // Zoom to fit after physics settle — generous padding
    setTimeout(() => graph.zoomToFit(2000, 60), 3000);

    // Resize handler
    window.addEventListener('resize', () => {
      graph.width(window.innerWidth).height(window.innerHeight);
    });
  }

  // ---- Node click → fly to node + open panel ----
  function handleNodeClick(node) {
    selectedNode = node;
    openPanel(node);

    // Fly camera to node — closer for detail
    const dist = 80;
    const ratio = 1 + dist / Math.hypot(node.x, node.y, node.z || 1);
    graph.cameraPosition(
      { x: node.x * ratio, y: node.y * ratio, z: (node.z || 0) * ratio },
      node,
      1200
    );

    // Stop auto-orbit
    graph.controls().autoRotate = false;

    // Re-render to highlight selected
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

    // Tags
    tags.innerHTML = node.tags.map(
      t => `<span class="kg-tag">${escapeHtml(t)}</span>`
    ).join('');

    // Connected notes
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

    // Click on connections to navigate
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

    // Re-render nodes with updated highlights
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

    setTimeout(() => graph.zoomToFit(800, 80), 1000);
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
