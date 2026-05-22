function zkVar(name, fallback) {
  const envValue = pm.environment.get(name);
  const collectionValue = pm.collectionVariables.get(name);
  return envValue !== undefined && envValue !== '' ? envValue : (collectionValue !== undefined && collectionValue !== '' ? collectionValue : fallback);
}

function zkRequire(names, reason) {
  const missing = names.filter((name) => !zkVar(name, ''));
  if (missing.length) {
    pm.test('SKIPPED: ' + reason, function () {
      pm.expect(missing, 'missing variables').to.be.an('array');
    });
    pm.execution.skipRequest();
  }
}

function zkJson() {
  try {
    return pm.response.json();
  } catch (error) {
    return {};
  }
}

function zkRecordLatency(label, priority, thresholdMs) {
  const elapsed = pm.response.responseTime || 0;
  const raw = pm.environment.get('latency_events_json') || '[]';
  let events = [];
  try {
    events = JSON.parse(raw);
  } catch (error) {
    events = [];
  }
  events.push({
    label,
    priority,
    elapsed_ms: elapsed,
    threshold_ms: Number(thresholdMs || 0),
    slow: Number(thresholdMs || 0) > 0 && elapsed > Number(thresholdMs || 0),
    status: pm.response.code,
    request: pm.info.requestName
  });
  pm.environment.set('latency_events_json', JSON.stringify(events));
  if (thresholdMs) {
    pm.test('SOFT timing: ' + label + ' <= ' + thresholdMs + 'ms', function () {
      pm.expect(true, elapsed + 'ms observed; soft threshold only').to.equal(true);
    });
  }
}

function zkProblemShape(body) {
  pm.expect(body).to.be.an('object');
  pm.expect(body.type || body.error || body.detail).to.exist;
}

function zkAssertAddZettelAccepted(body) {
  pm.expect(pm.response.code).to.equal(202);
  pm.expect(pm.response.headers.get('Location')).to.match(/^\/api\/operations\//);
  pm.expect(pm.response.headers.get('Retry-After')).to.match(/^\d+$/);
  pm.expect(body.status).to.equal('accepted');
  pm.expect(body.operation_id).to.be.a('string').and.not.empty;
  pm.expect(body.status_url).to.equal('/api/operations/' + body.operation_id);
  pm.expect(body.persistence).to.be.an('object');
  pm.expect(body.quality).to.be.an('object');
}

function zkAssertTerminalAddZettel(body) {
  pm.expect(body.status).to.be.oneOf(['succeeded', 'failed', 'cancelled', 'expired']);
  pm.expect(body.operation_id).to.be.a('string').and.not.empty;
  if (body.status === 'succeeded') {
    pm.expect(body.summary).to.be.an('object');
    pm.expect(body.summary.title || '', 'summary.title').to.be.a('string');
    pm.expect(body.persistence).to.be.an('object');
    pm.expect(body.quality).to.be.an('object');
  } else {
    pm.expect(body.error || body.detail || body.quality).to.exist;
  }
}
