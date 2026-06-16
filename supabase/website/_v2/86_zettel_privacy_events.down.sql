-- Reverse migration 86. Idempotent.
BEGIN;
  DROP TABLE IF EXISTS content.zettel_privacy_events;
COMMIT;
NOTIFY pgrst, 'reload schema';
