/* ============================================
   Knowledge Graph Viewer — Interactive App
   ============================================ */

(function () {
  'use strict';

  // ---- Color map (matches CSS variables) ----
  const COLORS = {
    youtube:  'hsl(355, 65%, 62%)',
    reddit:   'hsl(24, 70%, 58%)',
    github:   'hsl(265, 45%, 68%)',
    substack: 'hsl(205, 55%, 58%)',
    medium:   'hsl(155, 45%, 52%)'
  };

  const COLORS_DIM = {
    youtube:  'hsla(355, 65%, 62%, 0.2)',
    reddit:   'hsla(24, 70%, 58%, 0.2)',
    github:   'hsla(265, 45%, 68%, 0.2)',
    substack: 'hsla(205, 55%, 58%, 0.2)',
    medium:   'hsla(155, 45%, 52%, 0.2)'
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
  let highlightNodes = new Set();
  let highlightLinks = new Set();
  let hoverNode = null;
  let selectedNode = null;
  let activeFilters = new Set(['youtube', 'reddit', 'github', 'substack', 'medium']);

  // ---- Load data and init ----
  fetch('/kg/data/graph.json')
    .then(r => r.json())
    .then(data => {
      fullData = data;
      graphData = structuredClone(data);
      initGraph();
      updateStats();
    })
    .catch(err => {
      console.error('Failed to load graph data:', err);
      statsEl.textContent = 'Failed to load data';
    });

  function initGraph() {
    graph = new ForceGraph(container)
      .graphData(graphData)
      .backgroundColor('hsl(224, 28%, 4%)')
      .nodeRelSize(6)
      .nodeColor(node => {
        if (highlightNodes.size > 0 && !highlightNodes.has(node)) {
          return COLORS_DIM[node.group] || 'hsla(220, 14%, 30%, 0.2)';
        }
        return COLORS[node.group] || 'hsl(220, 14%, 50%)';
      })
      .nodeLabel('')  // We handle tooltips via canvas
      .linkColor(link => {
        if (highlightLinks.size > 0 && !highlightLinks.has(link)) {
          return 'hsla(220, 16%, 14%, 0.15)';
        }
        return 'hsla(220, 16%, 50%, 0.3)';
      })
      .linkWidth(link => highlightLinks.has(link) ? 2 : 1)
      .linkDirectionalParticles(link => highlightLinks.has(link) ? 2 : 0)
      .linkDirectionalParticleWidth(2)
      .linkDirectionalParticleColor(() => 'hsl(172, 66%, 50%)')
      .onNodeHover(handleNodeHover)
      .onNodeClick(handleNodeClick)
      .onBackgroundClick(handleBackgroundClick)
      .nodeCanvasObject(drawNode)
      .nodeCanvasObjectMode(() => 'replace')
      .d3AlphaDecay(0.02)
      .d3VelocityDecay(0.3)
      .warmupTicks(80)
      .cooldownTime(3000);

    // Resize on window resize
    window.addEventListener('resize', () => {
      graph.width(window.innerWidth).height(window.innerHeight);
    });

    // Initial zoom to fit after settling
    setTimeout(() => {
      graph.zoomToFit(600, 60);
    }, 1500);
  }

  // ---- Node rendering ----
  function drawNode(node, ctx, globalScale) {
    const isHighlighted = highlightNodes.size === 0 || highlightNodes.has(node);
    const isSelected = selectedNode === node;
    const isHovered = hoverNode === node;
    const baseR = 5;
    const r = isSelected ? baseR * 1.4 : isHovered ? baseR * 1.2 : baseR;
    const color = COLORS[node.group] || 'hsl(220, 14%, 50%)';
    const alpha = isHighlighted ? 1 : 0.15;

    ctx.save();
    ctx.globalAlpha = alpha;

    // Glow for selected/hovered
    if ((isSelected || isHovered) && isHighlighted) {
      ctx.beginPath();
      ctx.arc(node.x, node.y, r + 4, 0, 2 * Math.PI);
      ctx.fillStyle = COLORS_DIM[node.group] || 'hsla(220, 14%, 50%, 0.2)';
      ctx.fill();
    }

    // Main circle
    ctx.beginPath();
    ctx.arc(node.x, node.y, r, 0, 2 * Math.PI);
    ctx.fillStyle = color;
    ctx.fill();

    // Border for selected
    if (isSelected) {
      ctx.strokeStyle = 'hsl(172, 66%, 50%)';
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }

    // Label
    const showLabel = globalScale > 0.8 || isHovered || isSelected;
    if (showLabel && isHighlighted) {
      const fontSize = Math.max(11 / globalScale, 3);
      ctx.font = `500 ${fontSize}px Inter, sans-serif`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';

      const label = truncateLabel(node.name, 40);
      const textWidth = ctx.measureText(label).width;

      // Background pill behind text
      const padding = 3 / globalScale;
      ctx.fillStyle = 'hsla(224, 28%, 4%, 0.8)';
      ctx.beginPath();
      const pillY = node.y + r + 3;
      const pillH = fontSize + padding * 2;
      const pillW = textWidth + padding * 4;
      const pillR = pillH / 2;
      roundRect(ctx, node.x - pillW / 2, pillY, pillW, pillH, pillR);
      ctx.fill();

      // Text
      ctx.fillStyle = isSelected ? 'hsl(172, 66%, 50%)' : 'hsl(210, 20%, 88%)';
      ctx.fillText(label, node.x, pillY + padding);
    }

    ctx.restore();
  }

  function roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + w - r, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + r);
    ctx.lineTo(x + w, y + h - r);
    ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    ctx.lineTo(x + r, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - r);
    ctx.lineTo(x, y + r);
    ctx.quadraticCurveTo(x, y, x + r, y);
    ctx.closePath();
  }

  function truncateLabel(text, maxLen) {
    if (text.length <= maxLen) return text;
    return text.slice(0, maxLen - 1) + '\u2026';
  }

  // ---- Interactions ----
  function handleNodeHover(node) {
    container.style.cursor = node ? 'pointer' : 'default';
    hoverNode = node;

    highlightNodes.clear();
    highlightLinks.clear();

    if (node) {
      highlightNodes.add(node);
      const nodeLinks = graphData.links.filter(
        l => l.source === node || l.target === node
      );
      nodeLinks.forEach(link => {
        highlightLinks.add(link);
        highlightNodes.add(link.source);
        highlightNodes.add(link.target);
      });
    }
  }

  function handleNodeClick(node) {
    selectedNode = node;
    openPanel(node);

    // Highlight the selected node's neighborhood
    highlightNodes.clear();
    highlightLinks.clear();
    highlightNodes.add(node);
    const nodeLinks = graphData.links.filter(
      l => l.source === node || l.target === node
    );
    nodeLinks.forEach(link => {
      highlightLinks.add(link);
      highlightNodes.add(link.source);
      highlightNodes.add(link.target);
    });

    // Center on node
    graph.centerAt(node.x, node.y, 600);
    graph.zoom(2.5, 600);
  }

  function handleBackgroundClick() {
    closePanel();
    selectedNode = null;
    highlightNodes.clear();
    highlightLinks.clear();
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

    // Connections
    const nodeLinks = graphData.links.filter(
      l => l.source === node || l.target === node
    );
    const connectedNodes = nodeLinks.map(l => ({
      node: l.source === node ? l.target : l.source,
      relation: l.relation
    }));

    connections.innerHTML = connectedNodes.map(c => `
      <div class="kg-connection" data-id="${escapeHtml(c.node.id)}">
        <span class="kg-connection-dot" style="background: ${COLORS[c.node.group] || '#888'}"></span>
        <span class="kg-connection-name">${escapeHtml(c.node.name)}</span>
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

    sidePanel.classList.remove('hidden');
    requestAnimationFrame(() => sidePanel.classList.add('visible'));
  }

  function closePanel() {
    sidePanel.classList.remove('visible');
    setTimeout(() => sidePanel.classList.add('hidden'), 350);
  }

  function formatDate(dateStr) {
    const d = new Date(dateStr);
    return d.toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'long',
      day: 'numeric'
    });
  }

  // ---- Search ----
  searchInput.addEventListener('input', (e) => {
    const query = e.target.value.toLowerCase().trim();

    highlightNodes.clear();
    highlightLinks.clear();
    selectedNode = null;

    if (query.length === 0) return;

    graphData.nodes.forEach(node => {
      const nameMatch = node.name.toLowerCase().includes(query);
      const tagMatch = node.tags.some(t => t.toLowerCase().includes(query));
      const summaryMatch = node.summary.toLowerCase().includes(query);
      if (nameMatch || tagMatch || summaryMatch) {
        highlightNodes.add(node);
      }
    });

    // Also highlight links between matched nodes
    if (highlightNodes.size > 0) {
      graphData.links.forEach(link => {
        if (highlightNodes.has(link.source) && highlightNodes.has(link.target)) {
          highlightLinks.add(link);
        }
      });
    }
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
    highlightLinks.clear();

    setTimeout(() => graph.zoomToFit(600, 60), 500);
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
    highlightLinks.clear();
  });

  // ---- Keyboard shortcut: Escape to close panel ----
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      closePanel();
      selectedNode = null;
      highlightNodes.clear();
      highlightLinks.clear();
      searchInput.value = '';
    }
  });

})();
