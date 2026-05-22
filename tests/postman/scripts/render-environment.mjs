import fs from 'node:fs';
import path from 'node:path';

const [templatePath, outputPath] = process.argv.slice(2);
const sanitize = process.argv.includes('--sanitize');
if (!templatePath || !outputPath) {
  console.error('Usage: node render-environment.mjs <template> <output>');
  process.exit(1);
}

const replacements = {
  base_url: process.env.TARGET_URL || 'http://127.0.0.1:8000',
  run_live_requests: process.env.RUN_LIVE_REQUESTS || 'false',
  persist_live_writes: process.env.PERSIST_LIVE_WRITES || 'false',
  allow_slow_live_paths: process.env.ALLOW_SLOW_LIVE_PATHS || 'false',
  supabase_url: process.env.SUPABASE_URL || '',
  supabase_service_role_key: process.env.SUPABASE_SERVICE_ROLE_KEY || '',
  auth_token_user_a: process.env.AUTH_TOKEN_USER_A || '',
  auth_token_user_b: process.env.AUTH_TOKEN_USER_B || ''
};

const env = JSON.parse(fs.readFileSync(templatePath, 'utf8'));
env.name = `Zettelkasten Postman Runtime ${new Date().toISOString()}`;
env.values = env.values.map((entry) => {
  if (sanitize && entry.type === 'secret') {
    return { ...entry, value: '' };
  }
  if (Object.prototype.hasOwnProperty.call(replacements, entry.key)) {
    return { ...entry, value: replacements[entry.key] };
  }
  return entry;
});

fs.mkdirSync(path.dirname(outputPath), { recursive: true });
fs.writeFileSync(outputPath, JSON.stringify(env, null, 2) + '\n', 'utf8');
