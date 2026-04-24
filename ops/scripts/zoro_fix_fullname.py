"""Fix Zoro auth.users.raw_user_meta_data.full_name leftover from Hinata migration."""
from __future__ import annotations
import os, sys, json
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(r"C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\supabase\.env"), override=False)
from supabase import create_client
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
ZORO_AUTH_ID = "a57e1f2f-7d89-4cd7-ae39-72c440ed4b4e"
sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
cur = sb.auth.admin.get_user_by_id(ZORO_AUTH_ID)
meta = dict(cur.user.user_metadata or {})
before = meta.get("full_name")
meta["full_name"] = "Zoro"
sb.auth.admin.update_user_by_id(ZORO_AUTH_ID, {"user_metadata": meta})
after = sb.auth.admin.get_user_by_id(ZORO_AUTH_ID).user.user_metadata.get("full_name")
print(json.dumps({"auth_id": ZORO_AUTH_ID, "before": before, "after": after}))
